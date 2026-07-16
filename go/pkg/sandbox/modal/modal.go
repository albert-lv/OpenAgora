// Package modal implements a sandbox.Provider skeleton for Modal cloud sandboxes.
//
// Modal (https://modal.com) exposes sandboxes via its Python SDK or CLI. A full
// implementation would shell out to `modal sandbox create/exec/kill` or run a
// small Python sidecar. This package defines the interface and registers the
// provider name so `arena run --env modal` is recognized.
package modal

import (
	"context"
	"fmt"
	"os"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Provider is a Modal sandbox provider skeleton.
type Provider struct {
	apiKey string
}

func init() {
	sandbox.RegisterProvider("modal", func(config map[string]string) (sandbox.Provider, error) {
		return NewProvider(config), nil
	})
}

// NewProvider creates a new Modal provider.
func NewProvider(config map[string]string) *Provider {
	apiKey := config["api_key"]
	if apiKey == "" {
		apiKey = os.Getenv("MODAL_API_KEY")
	}
	return &Provider{apiKey: apiKey}
}

// Capabilities returns the Modal provider capability set.
func (p *Provider) Capabilities() sandbox.CapabilitySet {
	return sandbox.CapabilitySet{
		FileTransfer:         true,
		GPUs:                 true,
		DisableInternet:      false,
		NetworkAllowlist:     false,
		DynamicNetworkPolicy: false,
		Windows:              false,
		Mounted:              false,
		DockerCompose:        false,
	}
}

func (p *Provider) notImplemented(method string) error {
	return fmt.Errorf("modal provider %s not implemented; set MODAL_API_KEY and implement via modal CLI/Python SDK", method)
}

// Create is not yet implemented.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("MODAL_API_KEY not configured")
	}
	return nil, p.notImplemented("Create")
}

// Start is not yet implemented.
func (p *Provider) Start(ctx context.Context, id string) error {
	return p.notImplemented("Start")
}

// Stop is not yet implemented.
func (p *Provider) Stop(ctx context.Context, id string) error {
	return p.notImplemented("Stop")
}

// Destroy is not yet implemented.
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	return p.notImplemented("Destroy")
}

// Exec is not yet implemented.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	return nil, p.notImplemented("Exec")
}

// WaitForDone is not yet implemented.
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	return p.notImplemented("WaitForDone")
}

// Logs is not yet implemented.
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return nil, p.notImplemented("Logs")
}
