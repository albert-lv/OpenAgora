// Package daytona implements a sandbox.Provider skeleton for Daytona workspaces.
//
// A full implementation would use the Daytona SDK or REST API to create workspaces,
// execute commands, and destroy them. This package registers the provider name so
// `arena run --env daytona` is recognized.
package daytona

import (
	"context"
	"fmt"
	"os"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Provider is a Daytona sandbox provider skeleton.
type Provider struct {
	apiKey string
}

func init() {
	sandbox.RegisterProvider("daytona", func(config map[string]string) (sandbox.Provider, error) {
		return NewProvider(config), nil
	})
}

// NewProvider creates a new Daytona provider.
func NewProvider(config map[string]string) *Provider {
	apiKey := config["api_key"]
	if apiKey == "" {
		apiKey = os.Getenv("DAYTONA_API_KEY")
	}
	return &Provider{apiKey: apiKey}
}

// Capabilities returns the Daytona provider capability set.
func (p *Provider) Capabilities() sandbox.CapabilitySet {
	return sandbox.CapabilitySet{
		FileTransfer:         true,
		GPUs:                 false,
		DisableInternet:      true,
		NetworkAllowlist:     true,
		DynamicNetworkPolicy: false,
		Windows:              false,
		Mounted:              false,
		DockerCompose:        false,
	}
}

func (p *Provider) notImplemented(method string) error {
	return fmt.Errorf("daytona provider %s not implemented; set DAYTONA_API_KEY and implement via Daytona SDK/REST API", method)
}

func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("DAYTONA_API_KEY not configured")
	}
	return nil, p.notImplemented("Create")
}

func (p *Provider) Start(ctx context.Context, id string) error { return p.notImplemented("Start") }
func (p *Provider) Stop(ctx context.Context, id string) error  { return p.notImplemented("Stop") }
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	return p.notImplemented("Destroy")
}
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	return nil, p.notImplemented("Exec")
}
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	return p.notImplemented("WaitForDone")
}
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return nil, p.notImplemented("Logs")
}
