package server

import (
	"context"
	"fmt"
	"io"
	"testing"
	"time"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox"
	"github.com/albert-lv/agent-arena/go/pkg/trajectory"
	"github.com/albert-lv/agent-arena/go/pkg/trajectory/backend"
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

func (m *mockSandboxProvider) Destroy(ctx context.Context, id string) error {
	m.destroyed[id] = true
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

// mockVerifyRunner is a verification runner for testing.
type mockVerifyRunner struct {
	rewards []float64
	err     error
}

func (m *mockVerifyRunner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	return m.rewards, m.err
}

func TestCreateRollout(t *testing.T) {
	logger := zap.NewNop()
	sp := newMockSandboxProvider()
	vr := &mockVerifyRunner{rewards: []float64{0.95}}

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

func (m *mockStream) SendMsg(msg any) error   { return nil }
func (m *mockStream) RecvMsg(msg any) error   { return nil }
func (m *mockStream) SetHeader(md metadata.MD) error  { return nil }
func (m *mockStream) SendHeader(md metadata.MD) error { return nil }
func (m *mockStream) SetTrailer(md metadata.MD)      {}

// mockWriter for testing.
type mockWriter struct{}

func (m *mockWriter) Write(ctx context.Context, step *trajectory.Step) error { return nil }
func (m *mockWriter) Close(ctx context.Context) error                        { return nil }

// mockBackend for testing.
type mockBackend struct {
	data map[string]io.Reader
}

func (m *mockBackend) Write(ctx context.Context, rolloutID string, step *trajectory.Step) error {
	return nil
}

func (m *mockBackend) Read(ctx context.Context, rolloutID string, w io.Writer) error {
	if r, ok := m.data[rolloutID]; ok {
		_, err := io.Copy(w, r)
		return err
	}
	return nil
}

func (m *mockBackend) Close(ctx context.Context) error { return nil }
