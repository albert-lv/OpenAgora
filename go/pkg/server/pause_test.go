package server

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
	"go.uber.org/zap"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// pausableProvider is a sandbox provider with pause support whose WaitForDone
// blocks until released, letting tests control rollout completion.
type pausableProvider struct {
	*mockSandboxProvider
	mu      sync.Mutex
	paused  map[string]bool
	release chan struct{}
}

func newPausableProvider() *pausableProvider {
	return &pausableProvider{
		mockSandboxProvider: newMockSandboxProvider(),
		paused:              make(map[string]bool),
		release:             make(chan struct{}),
	}
}

func (p *pausableProvider) WaitForDone(ctx context.Context, id string) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-p.release:
		return nil
	}
}

func (p *pausableProvider) Pause(ctx context.Context, id string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.paused[id] = true
	return nil
}

func (p *pausableProvider) Unpause(ctx context.Context, id string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	delete(p.paused, id)
	return nil
}

func (p *pausableProvider) isPaused(id string) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.paused[id]
}

func (p *pausableProvider) anySandboxID() string {
	for id := range p.created {
		return id
	}
	return ""
}

func createPausableRollout(t *testing.T, srv *ArenaServer, timeoutSeconds int32) *arena_pb.CreateRolloutResponse {
	t.Helper()
	resp, err := srv.CreateRollout(context.Background(), &arena_pb.CreateRolloutRequest{
		TaskId: "task-1",
		Sandbox: &arena_pb.SandboxConfig{
			Image:          "test-image",
			TimeoutSeconds: timeoutSeconds,
		},
		LlmBackend: "http://localhost:8000/v1",
	})
	if err != nil {
		t.Fatalf("CreateRollout failed: %v", err)
	}
	return resp
}

func rolloutStatus(t *testing.T, srv *ArenaServer, id string) string {
	t.Helper()
	r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: id})
	if err != nil {
		t.Fatalf("GetRollout failed: %v", err)
	}
	return r.Status
}

func TestPauseResumeRollout(t *testing.T) {
	logger := zap.NewNop()
	sp := newPausableProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	resp := createPausableRollout(t, srv, 10)

	if _, err := srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId, Mode: "freeze"}); err != nil {
		t.Fatalf("PauseRollout failed: %v", err)
	}
	if got := rolloutStatus(t, srv, resp.RolloutId); got != "paused" {
		t.Fatalf("expected paused, got %s", got)
	}
	if !sp.isPaused(sp.anySandboxID()) {
		t.Fatal("expected provider Pause to be called")
	}

	resume, err := srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: resp.RolloutId})
	if err != nil {
		t.Fatalf("ResumeRollout failed: %v", err)
	}
	if resume.ProxyUrl != resp.ProxyUrl || resume.Token != resp.Token {
		t.Fatalf("resume returned %q/%q, want unchanged %q/%q", resume.ProxyUrl, resume.Token, resp.ProxyUrl, resp.Token)
	}
	if got := rolloutStatus(t, srv, resp.RolloutId); got != "running" {
		t.Fatalf("expected running after resume, got %s", got)
	}
	if sp.isPaused(sp.anySandboxID()) {
		t.Fatal("expected provider Unpause to be called")
	}

	// Let the rollout finish; it must reach a terminal status.
	close(sp.release)
	waitForCondition(t, "terminal status", func() bool {
		return rolloutStatus(t, srv, resp.RolloutId) == "success"
	})
}

func TestPauseSuspendsTimeout(t *testing.T) {
	logger := zap.NewNop()
	sp := newPausableProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	// 1 second timeout; pausing must suspend the clock.
	resp := createPausableRollout(t, srv, 1)
	if _, err := srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId}); err != nil {
		t.Fatalf("PauseRollout failed: %v", err)
	}

	// Wait well past the timeout; a paused rollout must not be killed.
	time.Sleep(1500 * time.Millisecond)
	if got := rolloutStatus(t, srv, resp.RolloutId); got != "paused" {
		t.Fatalf("expected paused after timeout elapsed, got %s", got)
	}

	// After resume the remaining budget is nearly exhausted, so the rollout
	// times out shortly and is marked failed.
	if _, err := srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: resp.RolloutId}); err != nil {
		t.Fatalf("ResumeRollout failed: %v", err)
	}
	waitForCondition(t, "timeout after resume", func() bool {
		return rolloutStatus(t, srv, resp.RolloutId) == "failed"
	})
}

func TestPauseRolloutInvalidTransitions(t *testing.T) {
	logger := zap.NewNop()
	sp := newPausableProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	// Unknown rollout.
	_, err := srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: "nope"})
	if status.Code(err) != codes.NotFound {
		t.Fatalf("expected NotFound, got %v", err)
	}
	_, err = srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: "nope"})
	if status.Code(err) != codes.NotFound {
		t.Fatalf("expected NotFound, got %v", err)
	}

	resp := createPausableRollout(t, srv, 30)
	finished := false
	defer func() {
		if !finished {
			close(sp.release)
		}
	}()

	// Unknown pause mode.
	_, err = srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId, Mode: "snapshot"})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("expected InvalidArgument, got %v", err)
	}

	// Resume a running rollout.
	_, err = srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: resp.RolloutId})
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("expected FailedPrecondition, got %v", err)
	}

	// Double pause.
	if _, err := srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId}); err != nil {
		t.Fatalf("PauseRollout failed: %v", err)
	}
	_, err = srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId})
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("expected FailedPrecondition, got %v", err)
	}

	// Pause after terminal status.
	if _, err := srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: resp.RolloutId}); err != nil {
		t.Fatalf("ResumeRollout failed: %v", err)
	}
	close(sp.release)
	finished = true
	waitForCondition(t, "terminal status", func() bool {
		return rolloutStatus(t, srv, resp.RolloutId) == "success"
	})
	_, err = srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId})
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("expected FailedPrecondition, got %v", err)
	}
}

func TestPauseRolloutUnimplemented(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider() // no Pauser
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	resp := createPausableRollout(t, srv, 10)
	_, err := srv.PauseRollout(context.Background(), &arena_pb.PauseRolloutRequest{RolloutId: resp.RolloutId})
	if status.Code(err) != codes.Unimplemented {
		t.Fatalf("expected Unimplemented, got %v", err)
	}
	_, err = srv.ResumeRollout(context.Background(), &arena_pb.ResumeRolloutRequest{RolloutId: resp.RolloutId})
	if status.Code(err) != codes.Unimplemented {
		t.Fatalf("expected Unimplemented, got %v", err)
	}
}

// fakeSyncer records WeightSyncer calls and can fail the update step.
type fakeSyncer struct {
	mu        sync.Mutex
	calls     []string
	updateErr error
}

func (f *fakeSyncer) PauseGeneration(ctx context.Context, mode string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, "pause:"+mode)
	return nil
}

func (f *fakeSyncer) UpdateWeightsFromDisk(ctx context.Context, modelPath, version string, abortInFlight bool) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, "update:"+modelPath+":"+version)
	return f.updateErr
}

func (f *fakeSyncer) ContinueGeneration(ctx context.Context) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, "continue")
	return nil
}

func (f *fakeSyncer) recordedCalls() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.calls...)
}

func TestUpdateWeights(t *testing.T) {
	logger := zap.NewNop()
	fs := &fakeSyncer{}
	sp := newPausableProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp, WeightSyncer: fs})

	resp, err := srv.UpdateWeights(context.Background(), &arena_pb.UpdateWeightsRequest{
		ModelPath:     "/ckpt/step-10",
		WeightVersion: "step-10",
		AbortInFlight: true,
	})
	if err != nil {
		t.Fatalf("UpdateWeights failed: %v", err)
	}
	if !resp.Success || resp.WeightVersion != "step-10" {
		t.Fatalf("unexpected response: %+v", resp)
	}

	want := []string{"pause:", "update:/ckpt/step-10:step-10", "continue"}
	got := fs.recordedCalls()
	if len(got) != len(want) {
		t.Fatalf("syncer calls = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("syncer calls = %v, want %v", got, want)
		}
	}

	// New rollouts are stamped with the current weight version.
	createResp := createPausableRollout(t, srv, 30)
	defer close(sp.release)
	r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: createResp.RolloutId})
	if err != nil {
		t.Fatalf("GetRollout failed: %v", err)
	}
	if r.WeightVersion != "step-10" {
		t.Fatalf("expected weight_version step-10, got %q", r.WeightVersion)
	}
}

func TestUpdateWeightsFailureStillContinues(t *testing.T) {
	logger := zap.NewNop()
	fs := &fakeSyncer{updateErr: status.Error(codes.Internal, "refit exploded")}
	srv := New(logger, &ServerConfig{WeightSyncer: fs})

	resp, err := srv.UpdateWeights(context.Background(), &arena_pb.UpdateWeightsRequest{
		ModelPath:     "/ckpt/bad",
		WeightVersion: "step-x",
	})
	if err != nil {
		t.Fatalf("expected response with success=false, got error %v", err)
	}
	if resp.Success || !strings.Contains(resp.Message, "refit exploded") {
		t.Fatalf("unexpected response: %+v", resp)
	}
	// Generation must be resumed even though the refit failed.
	got := fs.recordedCalls()
	if len(got) != 3 || got[2] != "continue" {
		t.Fatalf("syncer calls = %v, want pause/update/continue", got)
	}
}

func TestUpdateWeightsPreconditions(t *testing.T) {
	logger := zap.NewNop()
	srv := New(logger, nil)

	_, err := srv.UpdateWeights(context.Background(), &arena_pb.UpdateWeightsRequest{ModelPath: "/ckpt"})
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("expected FailedPrecondition, got %v", err)
	}

	srv = New(logger, &ServerConfig{WeightSyncer: &fakeSyncer{}})
	_, err = srv.UpdateWeights(context.Background(), &arena_pb.UpdateWeightsRequest{WeightVersion: "v1"})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("expected InvalidArgument, got %v", err)
	}
}

// Ensure the test pausable provider satisfies the optional interface.
var _ sandbox.Pauser = (*pausableProvider)(nil)
