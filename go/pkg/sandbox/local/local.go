// Package local provides a sandbox provider that runs the agent directly on the
// host machine. It is useful for local development and demos when Docker is not
// available, but it sacrifices the isolation guarantees of containerized
// sandboxes. Use it only in trusted environments.
package local

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Provider implements sandbox.Provider by executing the agent as a subprocess
// on the host. The sandbox ID is a random directory under the system temp dir.
type Provider struct {
	mu       sync.Mutex
	hostDirs map[string]*sandbox.Sandbox
	procs    map[string]*exec.Cmd
}

// NewProvider creates a new local sandbox provider.
func NewProvider() *Provider {
	return &Provider{
		hostDirs: make(map[string]*sandbox.Sandbox),
		procs:    make(map[string]*exec.Cmd),
	}
}

// Create prepares a temporary directory that acts as /sandbox.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	hostDir, err := os.MkdirTemp("", "arena-local-sandbox-*")
	if err != nil {
		return nil, fmt.Errorf("mkdtemp: %w", err)
	}
	arenaDir := filepath.Join(hostDir, ".arena")
	if err := os.MkdirAll(arenaDir, 0755); err != nil {
		return nil, fmt.Errorf("mkdir .arena: %w", err)
	}

	if len(config.TaskFile) > 0 {
		if err := os.WriteFile(filepath.Join(arenaDir, "task.json"), config.TaskFile, 0644); err != nil {
			return nil, fmt.Errorf("write task.json: %w", err)
		}
	}

	sb := &sandbox.Sandbox{
		ID:      hostDir,
		Status:  "created",
		Config:  config,
		Created: time.Now(),
	}

	p.mu.Lock()
	p.hostDirs[hostDir] = sb
	p.mu.Unlock()

	return sb, nil
}

// Start runs the agent image/command as a background process in the sandbox dir.
func (p *Provider) Start(ctx context.Context, id string) error {
	sb, err := p.getSandbox(id)
	if err != nil {
		return err
	}

	// Interpret Image as the command to run. If it looks like a file path,
	// execute it directly; otherwise run it through sh -c.
	image := sb.Config.Image
	if image == "" {
		return fmt.Errorf("local sandbox requires a command in the image field")
	}

	var cmd *exec.Cmd
	if strings.Contains(image, " ") {
		cmd = exec.CommandContext(context.Background(), "sh", "-c", image)
	} else {
		cmd = exec.CommandContext(context.Background(), image)
	}
	cmd.Dir = id
	cmd.Env = os.Environ()
	for k, v := range sb.Config.EnvVars {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	cmd.Env = append(cmd.Env, "SANDBOX_DIR="+id, "ARENA_SANDBOX_DIR="+id)

	p.mu.Lock()
	p.procs[id] = cmd
	p.mu.Unlock()

	if err := cmd.Start(); err != nil {
		p.mu.Lock()
		delete(p.procs, id)
		p.mu.Unlock()
		return fmt.Errorf("start local agent: %w", err)
	}

	// Detach the process so WaitForDone can poll the done file.
	go func() {
		_ = cmd.Wait()
		p.mu.Lock()
		delete(p.procs, id)
		p.mu.Unlock()
	}()

	return nil
}

// Stop terminates the local agent process if it is still running.
func (p *Provider) Stop(ctx context.Context, id string) error {
	p.mu.Lock()
	cmd := p.procs[id]
	p.mu.Unlock()
	if cmd != nil && cmd.Process != nil {
		_ = cmd.Process.Kill()
	}
	return nil
}

// Destroy removes the temporary sandbox directory and stops the process.
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	id := sb.ID
	_ = p.Stop(ctx, id)
	p.mu.Lock()
	delete(p.hostDirs, id)
	delete(p.procs, id)
	p.mu.Unlock()
	return os.RemoveAll(id)
}

// Exec runs a shell command inside the sandbox directory.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	if _, err := p.getSandbox(id); err != nil {
		return nil, err
	}

	var c *exec.Cmd
	if len(cmd) == 3 && cmd[0] == "sh" && cmd[1] == "-c" {
		c = exec.CommandContext(ctx, "sh", "-c", cmd[2])
	} else {
		c = exec.CommandContext(ctx, cmd[0], cmd[1:]...)
	}
	c.Dir = id
	c.Env = os.Environ()
	c.Env = append(c.Env, "SANDBOX_DIR="+id, "ARENA_SANDBOX_DIR="+id)

	out, err := c.CombinedOutput()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			return nil, fmt.Errorf("exec %v: %w", cmd, err)
		}
	}
	return &sandbox.ExecResult{
		ExitCode: exitCode,
		Stdout:   out,
		Stderr:   []byte{},
	}, nil
}

// WaitForDone blocks until the sandbox signals completion by writing
// /sandbox/.arena/done.
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	doneFile := filepath.Join(id, ".arena", "done")
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if _, err := os.Stat(doneFile); err == nil {
				return nil
			}
		}
	}
}

// Logs returns a mock log line for local sandboxes.
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	return []byte("[local] agent running...\n[local] task complete\n"), nil
}

func (p *Provider) getSandbox(id string) (*sandbox.Sandbox, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	sb, ok := p.hostDirs[id]
	if !ok {
		return nil, fmt.Errorf("local sandbox not found: %s", id)
	}
	return sb, nil
}
