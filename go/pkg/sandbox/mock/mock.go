// Package mock provides a sandbox provider for demos and testing.
// The mock agent waits for a configurable duration, allowing external
// callers to simulate LLM interactions through the proxy.
package mock

import (
	"context"
	"os"
	"strconv"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Provider is a mock sandbox provider that never creates real containers.
type Provider struct {
	waitDuration time.Duration
}

// NewProvider creates a new mock provider.
// It reads ARENA_MOCK_WAIT_MS from the environment (default 3000ms).
func NewProvider() *Provider {
	ms := 3000
	if v := os.Getenv("ARENA_MOCK_WAIT_MS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			ms = n
		}
	}
	return &Provider{waitDuration: time.Duration(ms) * time.Millisecond}
}

// Create returns a fake sandbox immediately.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	return &sandbox.Sandbox{ID: "mock-sandbox", Status: "created", Config: config}, nil
}

// Start is a no-op.
func (p *Provider) Start(ctx context.Context, id string) error { return nil }

// Stop is a no-op.
func (p *Provider) Stop(ctx context.Context, id string) error { return nil }

// Destroy is a no-op.
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error { return nil }

// Exec returns success.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	return &sandbox.ExecResult{ExitCode: 0}, nil
}

// WaitForDone sleeps for the configured duration then returns.
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(p.waitDuration):
		return nil
	}
}

// Logs returns mock log output.
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return []byte("[mock] agent running...\n[mock] task complete\n"), nil
}
