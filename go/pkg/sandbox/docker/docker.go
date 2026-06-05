package docker

import (
	"context"
	"fmt"

	"github.com/albert-lv/agent-arena/go/pkg/sandbox"
)

// Provider implements the sandbox.Provider interface using Docker.
type Provider struct{}

// NewProvider creates a new Docker sandbox provider.
func NewProvider() *Provider {
	return &Provider{}
}

// Create starts a new Docker container from the given image.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	return nil, fmt.Errorf("docker provider: not yet implemented")
}

// Start starts an existing container.
func (p *Provider) Start(ctx context.Context, id string) error {
	return fmt.Errorf("docker provider: not yet implemented")
}

// Stop stops a running container.
func (p *Provider) Stop(ctx context.Context, id string) error {
	return fmt.Errorf("docker provider: not yet implemented")
}

// Destroy removes a container and its resources.
func (p *Provider) Destroy(ctx context.Context, id string) error {
	return fmt.Errorf("docker provider: not yet implemented")
}

// Exec runs a command inside a container.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	return nil, fmt.Errorf("docker provider: not yet implemented")
}

// WaitForDone blocks until the sandbox signals completion
// (e.g., by writing /sandbox/.arena/done or exiting).
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	return fmt.Errorf("docker provider: not yet implemented")
}
