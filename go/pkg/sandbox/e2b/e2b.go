// Package e2b implements a sandbox.Provider backed by E2B cloud sandboxes.
package e2b

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

const defaultAPIURL = "https://api.e2b.app"

// Provider implements sandbox.Provider for E2B cloud microVMs.
type Provider struct {
	apiKey string
	apiURL string
	client *http.Client
}

func init() {
	sandbox.RegisterProvider("e2b", func(config map[string]string) (sandbox.Provider, error) {
		return NewProvider(config), nil
	})
}

// NewProvider creates an E2B sandbox provider.
func NewProvider(config map[string]string) *Provider {
	apiKey := config["api_key"]
	if apiKey == "" {
		apiKey = os.Getenv("E2B_API_KEY")
	}
	apiURL := config["api_url"]
	if apiURL == "" {
		apiURL = os.Getenv("E2B_API_URL")
	}
	if apiURL == "" {
		apiURL = defaultAPIURL
	}
	return &Provider{
		apiKey: apiKey,
		apiURL: apiURL,
		client: &http.Client{Timeout: 60 * time.Second},
	}
}

// Capabilities returns the E2B provider capability set.
func (p *Provider) Capabilities() sandbox.CapabilitySet {
	return sandbox.CapabilitySet{
		FileTransfer:         true,
		GPUs:                 false,
		DisableInternet:      false,
		NetworkAllowlist:     true,
		DynamicNetworkPolicy: false,
		Windows:              false,
		Mounted:              false,
		DockerCompose:        false,
	}
}

func (p *Provider) auth(req *http.Request) {
	req.Header.Set("X-API-Key", p.apiKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
}

func (p *Provider) url(path string) string {
	return p.apiURL + path
}

type createRequest struct {
	Template string            `json:"template"`
	Timeout  int               `json:"timeout"`
	EnvVars  map[string]string `json:"env_vars,omitempty"`
}

type createResponse struct {
	ID string `json:"id"`
}

// Create starts a new E2B sandbox.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	if p.apiKey == "" {
		return nil, fmt.Errorf("E2B_API_KEY not configured")
	}

	template := config.Image
	if template == "" {
		template = "base"
	}
	timeout := int(config.Timeout.Seconds())
	if timeout == 0 {
		timeout = 300
	}

	body, err := json.Marshal(createRequest{
		Template: template,
		Timeout:  timeout,
		EnvVars:  config.EnvVars,
	})
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, p.url("/sandboxes"), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	p.auth(req)

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("e2b create sandbox: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusCreated {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("e2b create sandbox: status %d: %s", resp.StatusCode, string(b))
	}

	var cr createResponse
	if err := json.NewDecoder(resp.Body).Decode(&cr); err != nil {
		return nil, fmt.Errorf("e2b decode create response: %w", err)
	}

	// E2B sandboxes do not expose a host mount. We create a local staging dir
	// for metadata and upload task.json via a command after creation.
	hostDir, err := os.MkdirTemp("", "arena-e2b-*")
	if err != nil {
		return nil, fmt.Errorf("mkdtemp: %w", err)
	}
	if len(config.TaskFile) > 0 {
		if err := os.WriteFile(filepath.Join(hostDir, "task.json"), config.TaskFile, 0644); err != nil {
			_ = os.RemoveAll(hostDir)
			return nil, err
		}
		// Upload task.json into the sandbox via a command.
		encoded := strconv.Quote(string(config.TaskFile))
		if _, err := p.Exec(ctx, cr.ID, []string{"sh", "-c", "mkdir -p /sandbox/.arena && printf '%s' " + encoded + " > /sandbox/.arena/task.json"}); err != nil {
			_ = os.RemoveAll(hostDir)
			return nil, fmt.Errorf("e2b upload task.json: %w", err)
		}
	}

	return &sandbox.Sandbox{
		ID:      cr.ID,
		Status:  "created",
		Config:  config,
		Created: time.Now(),
		HostDir: hostDir,
	}, nil
}

// Start is a no-op for E2B; the sandbox is already running after Create.
func (p *Provider) Start(ctx context.Context, id string) error {
	return nil
}

// Stop kills the E2B sandbox.
func (p *Provider) Stop(ctx context.Context, id string) error {
	return p.kill(ctx, id)
}

// Destroy kills the sandbox and removes local staging files.
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	if sb != nil && sb.HostDir != "" {
		_ = os.RemoveAll(sb.HostDir)
	}
	return p.kill(ctx, sb.ID)
}

func (p *Provider) kill(ctx context.Context, id string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, p.url("/sandboxes/"+id), nil)
	if err != nil {
		return err
	}
	p.auth(req)
	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("e2b kill sandbox: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("e2b kill sandbox: status %d: %s", resp.StatusCode, string(b))
	}
	return nil
}

type execRequest struct {
	Cmd  string            `json:"cmd"`
	Args []string          `json:"args,omitempty"`
	Env  map[string]string `json:"env,omitempty"`
	Cwd  string            `json:"cwd,omitempty"`
}

type execResponse struct {
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	ExitCode int    `json:"exit_code"`
}

// Exec runs a command inside the E2B sandbox.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	if len(cmd) == 0 {
		return nil, fmt.Errorf("e2b exec: empty command")
	}
	var args []string
	if len(cmd) > 1 {
		args = cmd[1:]
	}
	body, err := json.Marshal(execRequest{
		Cmd:  cmd[0],
		Args: args,
		Cwd:  "/sandbox",
	})
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, p.url("/sandboxes/"+id+"/commands"), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	p.auth(req)

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("e2b exec: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return &sandbox.ExecResult{ExitCode: 1, Stderr: b}, fmt.Errorf("e2b exec: status %d: %s", resp.StatusCode, string(b))
	}

	var er execResponse
	if err := json.Unmarshal(b, &er); err != nil {
		return &sandbox.ExecResult{ExitCode: 0, Stdout: b}, nil
	}
	return &sandbox.ExecResult{
		ExitCode: er.ExitCode,
		Stdout:   []byte(er.Stdout),
		Stderr:   []byte(er.Stderr),
	}, nil
}

// WaitForDone polls the sandbox until it is no longer alive.
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	// E2B sandboxes have a fixed lifetime; we poll /sandboxes/{id} until gone.
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.url("/sandboxes/"+id), nil)
			if err != nil {
				return err
			}
			p.auth(req)
			resp, err := p.client.Do(req)
			if err != nil {
				return nil // assume gone
			}
			_ = resp.Body.Close()
			if resp.StatusCode == http.StatusNotFound {
				return nil
			}
		}
	}
}

// Logs is not supported by the E2B REST API in this minimal implementation.
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return nil, fmt.Errorf("e2b provider does not support logs")
}
