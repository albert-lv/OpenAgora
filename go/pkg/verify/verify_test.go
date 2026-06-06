package verify

import (
	"context"
	"testing"

	"github.com/albert-lv/agent-arena/go/pkg/sandbox"
)

type mockProvider struct {
	execResult *sandbox.ExecResult
	execErr    error
}

func (m *mockProvider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	return nil, nil
}
func (m *mockProvider) Start(ctx context.Context, id string) error  { return nil }
func (m *mockProvider) Stop(ctx context.Context, id string) error   { return nil }
func (m *mockProvider) Destroy(ctx context.Context, id string) error { return nil }
func (m *mockProvider) WaitForDone(ctx context.Context, id string) error { return nil }
func (m *mockProvider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	return m.execResult, m.execErr
}

func TestRunnerSuccess(t *testing.T) {
	mp := &mockProvider{
		execResult: &sandbox.ExecResult{ExitCode: 0, Stdout: []byte("ok"), Stderr: []byte("")},
	}
	r := NewRunner(mp)
	rewards, err := r.Run(context.Background(), "sb1", "echo ok")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rewards) != 1 || rewards[0] != 1.0 {
		t.Fatalf("expected [1.0], got %v", rewards)
	}
}

func TestRunnerFailure(t *testing.T) {
	mp := &mockProvider{
		execResult: &sandbox.ExecResult{ExitCode: 1, Stdout: []byte(""), Stderr: []byte("fail")},
	}
	r := NewRunner(mp)
	rewards, err := r.Run(context.Background(), "sb1", "false")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rewards) != 1 || rewards[0] != 0.0 {
		t.Fatalf("expected [0.0], got %v", rewards)
	}
}

func TestRunnerWithCustomRewards(t *testing.T) {
	mpWithRewards := &mockProviderWithCounter{}

	r := NewRunner(mpWithRewards)
	rewards, err := r.Run(context.Background(), "sb1", "pytest")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rewards) != 2 || rewards[0] != 1.0 || rewards[1] != 0.8 {
		t.Fatalf("expected [1.0, 0.8], got %v", rewards)
	}
}

type mockProviderWithCounter struct {
	callCount int
}

func (m *mockProviderWithCounter) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	return nil, nil
}
func (m *mockProviderWithCounter) Start(ctx context.Context, id string) error  { return nil }
func (m *mockProviderWithCounter) Stop(ctx context.Context, id string) error   { return nil }
func (m *mockProviderWithCounter) Destroy(ctx context.Context, id string) error { return nil }
func (m *mockProviderWithCounter) WaitForDone(ctx context.Context, id string) error { return nil }
func (m *mockProviderWithCounter) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	m.callCount++
	if m.callCount == 1 {
		return &sandbox.ExecResult{ExitCode: 0}, nil
	}
	return &sandbox.ExecResult{
		ExitCode: 0,
		Stdout:   []byte(`{"type":"task_complete","value":0.8,"source":"agent"}` + "\n"),
	}, nil
}

func TestRunnerNoProvider(t *testing.T) {
	r := NewRunner(nil)
	_, err := r.Run(context.Background(), "sb1", "echo ok")
	if err == nil {
		t.Fatal("expected error when provider is nil")
	}
}

func TestParsePytestOutput(t *testing.T) {
	cases := []struct {
		input    string
		expected float64
	}{
		{"1 passed in 0.01s", 1.0},
		{"1 failed in 0.01s", 0.0},
		{"random output", 0.0},
	}
	for _, tc := range cases {
		got := ParsePytestOutput(tc.input)
		if got != tc.expected {
			t.Fatalf("ParsePytestOutput(%q) = %f, want %f", tc.input, got, tc.expected)
		}
	}
}
