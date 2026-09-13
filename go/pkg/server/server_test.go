package server

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
	"github.com/albert-lv/OpenAgora/go/pkg/trajectory/backend"
	"github.com/albert-lv/OpenAgora/go/pkg/verify"
	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
	"go.uber.org/zap"
	"google.golang.org/grpc/metadata"
)

// mockSandboxProvider is a sandbox provider for testing.
type mockSandboxProvider struct {
	created   map[string]*sandbox.Config
	started   map[string]bool
	stopped   map[string]bool
	destroyed map[string]bool
	execs     map[string][]*sandbox.ExecResult
	waitErr   error
}

func newMockSandboxProvider() *mockSandboxProvider {
	return &mockSandboxProvider{
		created:   make(map[string]*sandbox.Config),
		started:   make(map[string]bool),
		stopped:   make(map[string]bool),
		destroyed: make(map[string]bool),
		execs:     make(map[string][]*sandbox.ExecResult),
	}
}

func (m *mockSandboxProvider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	id := fmt.Sprintf("sandbox-%d", len(m.created))
	m.created[id] = config
	return &sandbox.Sandbox{ID: id, Status: "created", Config: config}, nil
}

func (m *mockSandboxProvider) Start(ctx context.Context, id string) error {
	m.started[id] = true
	return nil
}

func (m *mockSandboxProvider) Stop(ctx context.Context, id string) error {
	m.stopped[id] = true
	return nil
}

func (m *mockSandboxProvider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	m.destroyed[sb.ID] = true
	return nil
}

func (m *mockSandboxProvider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	if res, ok := m.execs[id]; ok && len(res) > 0 {
		r := res[0]
		m.execs[id] = res[1:]
		return r, nil
	}
	return &sandbox.ExecResult{ExitCode: 0}, nil
}

func (m *mockSandboxProvider) WaitForDone(ctx context.Context, id string) error {
	if m.waitErr != nil {
		return m.waitErr
	}
	// Simulate a short wait.
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(10 * time.Millisecond):
		return nil
	}
}

func (m *mockSandboxProvider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return []byte("mock logs"), nil
}

func (m *mockSandboxProvider) Capabilities() sandbox.CapabilitySet {
	return sandbox.CapabilitySet{FileTransfer: true, Mounted: true}
}

// mockVerifyRunner is a verification runner for testing.
type mockVerifyRunner struct {
	report *verify.VerificationReport
	err    error
}

func (m *mockVerifyRunner) Run(ctx context.Context, provider sandbox.Provider, spec *verify.VerificationSpec, sandboxID string) (*verify.VerificationReport, error) {
	return m.report, m.err
}

func TestCreateRollout(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	vr := &mockVerifyRunner{report: &verify.VerificationReport{
		TotalReward: 0.95,
		Reward:      0.95, //nolint:staticcheck // SA1019: mirrors real runners that still set the legacy field
		Rewards:     []verify.Reward{{Name: "test", Value: 0.95}},
	}}

	srv := New(logger, &ServerConfig{
		SandboxProvider: sp,
		VerifyRunner:    vr,
	})

	req := &arena_pb.CreateRolloutRequest{
		TaskId: "task-1",
		Sandbox: &arena_pb.SandboxConfig{
			Image:   "test-image",
			Memory:  "1g",
			Cpus:    1.0,
			EnvVars: map[string]string{"FOO": "bar"},
		},
		Sampling: &arena_pb.SamplingConfig{
			Temperature:     0.5,
			TopP:            0.9,
			Seed:            42,
			MaxTokensBudget: 100,
		},
		Verify: &arena_pb.VerifyConfig{
			Command: "pytest",
		},
		LlmBackend: "http://localhost:8000/v1",
	}

	resp, err := srv.CreateRollout(context.Background(), req)
	if err != nil {
		t.Fatalf("CreateRollout failed: %v", err)
	}
	if resp.RolloutId == "" {
		t.Fatal("expected non-empty rollout ID")
	}

	// Wait for lifecycle goroutine.
	time.Sleep(100 * time.Millisecond)

	// Verify rollout state.
	rollout, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: resp.RolloutId})
	if err != nil {
		t.Fatalf("GetRollout failed: %v", err)
	}
	if rollout.TaskId != "task-1" {
		t.Fatalf("expected task-1, got %s", rollout.TaskId)
	}
	if rollout.Status != "success" {
		t.Fatalf("expected success, got %s", rollout.Status)
	}
	if rollout.Reward != 0.95 {
		t.Fatalf("expected reward 0.95, got %f", rollout.Reward)
	}
	if rollout.VerificationReport == nil {
		t.Fatal("expected verification report")
	}
	if len(rollout.VerificationReport.Rewards) != 1 {
		t.Fatalf("expected 1 reward, got %d", len(rollout.VerificationReport.Rewards))
	}

	// Verify sandbox provider calls.
	if len(sp.created) != 1 {
		t.Fatalf("expected 1 sandbox created, got %d", len(sp.created))
	}
	for id := range sp.created {
		if !sp.started[id] {
			t.Fatal("expected sandbox to be started")
		}
		if !sp.stopped[id] {
			t.Fatal("expected sandbox to be stopped")
		}
	}
}

func TestGetRolloutNotFound(t *testing.T) {
	logger := zap.NewNop()
	srv := New(logger, nil)
	_, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: "nonexistent"})
	if err == nil {
		t.Fatal("expected error for nonexistent rollout")
	}
}

func TestStopRollout(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	req := &arena_pb.CreateRolloutRequest{
		TaskId: "task-1",
		Sandbox: &arena_pb.SandboxConfig{
			Image: "test-image",
		},
	}
	resp, err := srv.CreateRollout(context.Background(), req)
	if err != nil {
		t.Fatalf("CreateRollout failed: %v", err)
	}

	_, err = srv.StopRollout(context.Background(), &arena_pb.StopRolloutRequest{RolloutId: resp.RolloutId})
	if err != nil {
		t.Fatalf("StopRollout failed: %v", err)
	}

	rollout, _ := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: resp.RolloutId})
	if rollout.Status != "stopped" {
		t.Fatalf("expected stopped, got %s", rollout.Status)
	}
}

func TestListRollouts(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	srv := New(logger, &ServerConfig{SandboxProvider: sp})

	for i := 0; i < 3; i++ {
		_, _ = srv.CreateRollout(context.Background(), &arena_pb.CreateRolloutRequest{
			TaskId:  fmt.Sprintf("task-%d", i),
			Sandbox: &arena_pb.SandboxConfig{Image: "test-image"},
		})
	}

	resp, err := srv.ListRollouts(context.Background(), &arena_pb.ListRolloutsRequest{})
	if err != nil {
		t.Fatalf("ListRollouts failed: %v", err)
	}
	if len(resp.Rollouts) != 3 {
		t.Fatalf("expected 3 rollouts, got %d", len(resp.Rollouts))
	}
}

func TestGetTrajectory(t *testing.T) {
	logger := zap.NewNop()
	tmpDir := t.TempDir()
	be := backend.NewLocalJSONL(tmpDir)

	// Write a fake trajectory.
	step := &trajectory.Step{
		RolloutID: "r1",
		Timestamp: time.Now(),
		Request: &trajectory.LLMRequest{
			Endpoint: "/v1/chat/completions",
			Messages: []byte(`{"messages":[]}`),
		},
		Response: &trajectory.LLMResponse{
			Choices: []byte(`{"choices":[]}`),
			Usage:   &trajectory.Usage{PromptTokens: 10, CompletionTokens: 5},
		},
	}
	_ = be.Write(context.Background(), "r1", step)

	srv := New(logger, &ServerConfig{
		TrajBackend: be,
		TrajDir:     tmpDir,
	})

	resp, err := srv.GetTrajectory(context.Background(), &arena_pb.GetTrajectoryRequest{RolloutId: "r1"})
	if err != nil {
		t.Fatalf("GetTrajectory failed: %v", err)
	}
	if len(resp.Steps) != 1 {
		t.Fatalf("expected 1 step, got %d", len(resp.Steps))
	}
	if resp.Steps[0].Response.Usage.PromptTokens != 10 {
		t.Fatalf("expected 10 prompt tokens, got %d", resp.Steps[0].Response.Usage.PromptTokens)
	}
}

func TestStreamTrajectory(t *testing.T) {
	logger := zap.NewNop()
	tmpDir := t.TempDir()
	be := backend.NewLocalJSONL(tmpDir)

	for i := 0; i < 3; i++ {
		step := &trajectory.Step{
			RolloutID: "r1",
			Timestamp: time.Now(),
			Request:   &trajectory.LLMRequest{Endpoint: "/v1/chat/completions"},
			Response:  &trajectory.LLMResponse{Choices: []byte(fmt.Sprintf(`{"i":%d}`, i))},
		}
		_ = be.Write(context.Background(), "r1", step)
	}

	srv := New(logger, &ServerConfig{
		TrajBackend: be,
		TrajDir:     tmpDir,
	})

	stream := &mockStream{ctx: context.Background()}
	err := srv.StreamTrajectory(&arena_pb.StreamTrajectoryRequest{RolloutId: "r1"}, stream)
	if err != nil {
		t.Fatalf("StreamTrajectory failed: %v", err)
	}
	if len(stream.steps) != 3 {
		t.Fatalf("expected 3 streamed steps, got %d", len(stream.steps))
	}
}

func TestProtoToInternalSampling(t *testing.T) {
	cfg := &arena_pb.SamplingConfig{
		Temperature:     0.5,
		TopP:            0.9,
		Seed:            42,
		MaxTokensBudget: 100,
	}
	internal := protoToInternalSampling(cfg)
	if internal.Temperature != 0.5 {
		t.Fatalf("temperature mismatch")
	}
	if internal.TopP < 0.89 || internal.TopP > 0.91 {
		t.Fatalf("top_p mismatch: %v", internal.TopP)
	}
	if internal.Seed != 42 {
		t.Fatalf("seed mismatch")
	}
	if internal.MaxTokensBudget != 100 {
		t.Fatalf("max_tokens_budget mismatch")
	}
}

// mockStream implements ArenaService_StreamTrajectoryServer for testing.
type mockStream struct {
	ctx   context.Context
	steps []*arena_pb.TrajectoryStep
}

func (m *mockStream) Send(step *arena_pb.TrajectoryStep) error {
	m.steps = append(m.steps, step)
	return nil
}

func (m *mockStream) Context() context.Context { return m.ctx }

func (m *mockStream) SendMsg(msg any) error           { return nil }
func (m *mockStream) RecvMsg(msg any) error           { return nil }
func (m *mockStream) SetHeader(md metadata.MD) error  { return nil }
func (m *mockStream) SendHeader(md metadata.MD) error { return nil }
func (m *mockStream) SetTrailer(md metadata.MD)       {}

// blockingVerifyRunner blocks until released, simulating a slow verification.
type blockingVerifyRunner struct {
	release chan struct{}
	report  *verify.VerificationReport
}

func (m *blockingVerifyRunner) Run(ctx context.Context, provider sandbox.Provider, spec *verify.VerificationSpec, sandboxID string) (*verify.VerificationReport, error) {
	select {
	case <-m.release:
		return m.report, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func createTestRollout(t *testing.T, srv *ArenaServer) string {
	t.Helper()
	resp, err := srv.CreateRollout(context.Background(), &arena_pb.CreateRolloutRequest{
		TaskId:     "task-1",
		Sandbox:    &arena_pb.SandboxConfig{Image: "test-image"},
		Verify:     &arena_pb.VerifyConfig{Command: "pytest"},
		LlmBackend: "http://localhost:8000/v1",
	})
	if err != nil {
		t.Fatalf("CreateRollout failed: %v", err)
	}
	return resp.RolloutId
}

func waitForCondition(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func TestAsyncVerify(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	vr := &blockingVerifyRunner{
		release: make(chan struct{}),
		report: &verify.VerificationReport{
			TotalReward: 0.5,
			Rewards:     []verify.Reward{{Name: "test", Value: 0.5}},
		},
	}
	srv := New(logger, &ServerConfig{SandboxProvider: sp, VerifyRunner: vr})

	rolloutID := createTestRollout(t, srv)

	// The rollout reaches its terminal generation status without waiting
	// for verification.
	waitForCondition(t, "terminal status", func() bool {
		r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
		return err == nil && r.Status == "success"
	})

	// Verification is still blocked: no report attached yet.
	r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
	if err != nil {
		t.Fatalf("GetRollout failed: %v", err)
	}
	if r.VerificationReport != nil {
		t.Fatal("expected verification report to be pending")
	}

	close(vr.release)
	waitForCondition(t, "verify results", func() bool {
		r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
		return err == nil && r.VerificationReport != nil
	})
	r, _ = srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
	if r.Status != "success" {
		t.Fatalf("expected status to remain success, got %s", r.Status)
	}
	if r.Reward != 0.5 {
		t.Fatalf("expected reward 0.5, got %f", r.Reward)
	}

	// Sandbox is stopped and destroyed after verification completes.
	for id := range sp.created {
		if !sp.stopped[id] || !sp.destroyed[id] {
			t.Fatalf("expected sandbox %s stopped and destroyed", id)
		}
	}
}

func TestSyncVerify(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	vr := &blockingVerifyRunner{
		release: make(chan struct{}),
		report:  &verify.VerificationReport{TotalReward: 0.5},
	}
	srv := New(logger, &ServerConfig{SandboxProvider: sp, VerifyRunner: vr, SyncVerify: true})

	rolloutID := createTestRollout(t, srv)

	// While verification is blocked the rollout must not reach a terminal
	// status (legacy inline behavior).
	time.Sleep(100 * time.Millisecond)
	r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
	if err != nil {
		t.Fatalf("GetRollout failed: %v", err)
	}
	if r.Status != "running" {
		t.Fatalf("expected running while verify blocked, got %s", r.Status)
	}

	close(vr.release)
	waitForCondition(t, "terminal status with reward", func() bool {
		r, err := srv.GetRollout(context.Background(), &arena_pb.GetRolloutRequest{RolloutId: rolloutID})
		return err == nil && r.Status == "success" && r.Reward == 0.5
	})
}

func TestResolveProxyTimeout(t *testing.T) {
	logger := zap.NewNop()

	if d := resolveProxyTimeout(logger, 3*time.Minute); d != 3*time.Minute {
		t.Fatalf("expected configured 3m, got %v", d)
	}

	t.Setenv("ARENA_PROXY_TIMEOUT", "")
	if d := resolveProxyTimeout(logger, 0); d != 0 {
		t.Fatalf("expected 0 when unset, got %v", d)
	}

	t.Setenv("ARENA_PROXY_TIMEOUT", "45s")
	if d := resolveProxyTimeout(logger, 0); d != 45*time.Second {
		t.Fatalf("expected 45s from env, got %v", d)
	}

	t.Setenv("ARENA_PROXY_TIMEOUT", "bogus")
	if d := resolveProxyTimeout(logger, 0); d != 0 {
		t.Fatalf("expected 0 for invalid env, got %v", d)
	}
}
