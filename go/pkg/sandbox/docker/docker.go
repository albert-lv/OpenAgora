package docker

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Provider implements the sandbox.Provider interface by shelling out to the Docker CLI.
// This avoids the heavy dependency chain of the Docker SDK and works cross-platform
// as long as the docker binary is on $PATH.
type Provider struct{}

func init() {
	sandbox.RegisterProvider("docker", func(_ map[string]string) (sandbox.Provider, error) {
		return NewProvider(), nil
	})
}

// NewProvider creates a new Docker sandbox provider.
func NewProvider() *Provider {
	return &Provider{}
}

// Capabilities returns the Docker provider capability set.
func (p *Provider) Capabilities() sandbox.CapabilitySet {
	return sandbox.CapabilitySet{
		FileTransfer:         true,
		GPUs:                 true,
		DisableInternet:      true,
		NetworkAllowlist:     true,
		DynamicNetworkPolicy: false,
		Windows:              true,
		Mounted:              true,
		DockerCompose:        true,
	}
}

// run executes a docker command and returns (stdout, stderr, error).
func (p *Provider) run(ctx context.Context, args ...string) ([]byte, []byte, error) {
	cmd := exec.CommandContext(ctx, "docker", args...)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	return []byte(stdout.String()), []byte(stderr.String()), err
}

// Create pulls the image if necessary and creates a container with a bind mount.
func (p *Provider) Create(ctx context.Context, config *sandbox.Config) (*sandbox.Sandbox, error) {
	// Ensure image is available.
	// Some Docker daemon configurations cause 'image inspect' to fail even when
	// the image is locally present (e.g. registry auth issues). We fall back to
	// 'docker images' and then 'docker pull' only if truly missing.
	_, _, inspectErr := p.run(ctx, "image", "inspect", config.Image)
	if inspectErr != nil {
		// Double-check with 'docker images' before attempting pull.
		stdout, _, imagesErr := p.run(ctx, "images", "--format", "{{.Repository}}:{{.Tag}}", config.Image)
		if imagesErr != nil || !strings.Contains(string(stdout), config.Image) {
			_, stderr, pullErr := p.run(ctx, "pull", config.Image)
			if pullErr != nil {
				return nil, fmt.Errorf("docker pull %s: %w (stderr: %s)", config.Image, pullErr, string(stderr))
			}
		}
	}

	// Prepare host directory for /sandbox mount.
	hostDir, err := os.MkdirTemp("", "arena-sandbox-*")
	if err != nil {
		return nil, fmt.Errorf("mkdtemp: %w", err)
	}
	arenaDir := filepath.Join(hostDir, ".arena")
	if err := os.MkdirAll(arenaDir, 0755); err != nil {
		return nil, fmt.Errorf("mkdir .arena: %w", err)
	}

	// Write task.json if provided.
	if len(config.TaskFile) > 0 {
		if err := os.WriteFile(filepath.Join(arenaDir, "task.json"), config.TaskFile, 0644); err != nil {
			return nil, fmt.Errorf("write task.json: %w", err)
		}
	}

	// Build docker run arguments.
	args := []string{
		"create",
		"--label", "arena.sandbox=true",
		"--mount", fmt.Sprintf("type=bind,source=%s,target=/sandbox", hostDir),
	}

	if network := os.Getenv("ARENA_DOCKER_NETWORK"); network != "" {
		args = append(args, "--network", network)
	}

	if config.Memory != "" {
		mem, err := parseMemory(config.Memory)
		if err != nil {
			return nil, fmt.Errorf("parse memory: %w", err)
		}
		args = append(args, "--memory", strconv.FormatInt(mem, 10))
	}
	if config.CPUs > 0 {
		args = append(args, "--cpus", strconv.FormatFloat(config.CPUs, 'f', -1, 64))
	}

	for k, v := range config.EnvVars {
		args = append(args, "--env", k+"="+v)
	}

	args = append(args, config.Image)
	if len(config.Command) > 0 {
		args = append(args, config.Command...)
	}

	stdout, stderr, err := p.run(ctx, args...)
	if err != nil {
		_ = os.RemoveAll(hostDir)
		return nil, fmt.Errorf("docker create: %w (stderr: %s)", err, string(stderr))
	}

	containerID := strings.TrimSpace(string(stdout))
	return &sandbox.Sandbox{
		ID:      containerID,
		Status:  "created",
		Config:  config,
		Created: time.Now(),
		HostDir: hostDir,
	}, nil
}

// Start starts an existing container.
func (p *Provider) Start(ctx context.Context, id string) error {
	_, stderr, err := p.run(ctx, "start", id)
	if err != nil {
		return fmt.Errorf("docker start %s: %w (stderr: %s)", id, err, string(stderr))
	}
	return nil
}

// Stop stops a running container.
func (p *Provider) Stop(ctx context.Context, id string) error {
	_, stderr, err := p.run(ctx, "stop", "-t", "30", id)
	if err != nil {
		return fmt.Errorf("docker stop %s: %w (stderr: %s)", id, err, string(stderr))
	}
	return nil
}

// Destroy removes a container and its resources.
func (p *Provider) Destroy(ctx context.Context, sb *sandbox.Sandbox) error {
	_, stderr, err := p.run(ctx, "rm", "-f", "-v", sb.ID)
	if err != nil {
		return fmt.Errorf("docker rm %s: %w (stderr: %s)", sb.ID, err, string(stderr))
	}
	if sb.HostDir != "" {
		if rmErr := os.RemoveAll(sb.HostDir); rmErr != nil {
			return fmt.Errorf("docker rm %s succeeded but cleanup host dir failed: %w", sb.ID, rmErr)
		}
	}
	return nil
}

// Exec runs a command inside a container.
func (p *Provider) Exec(ctx context.Context, id string, cmd []string) (*sandbox.ExecResult, error) {
	args := append([]string{"exec", id}, cmd...)
	stdout, stderr, err := p.run(ctx, args...)
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			return nil, fmt.Errorf("docker exec %s: %w", id, err)
		}
	}
	return &sandbox.ExecResult{
		ExitCode: exitCode,
		Stdout:   stdout,
		Stderr:   stderr,
	}, nil
}

// WaitForDone blocks until the sandbox signals completion
// (by writing /sandbox/.arena/done or by exiting).
func (p *Provider) WaitForDone(ctx context.Context, id string) error {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			// Check container status.
			stdout, _, err := p.run(ctx, "inspect", "-f", "{{.State.Status}}", id)
			if err != nil {
				return fmt.Errorf("docker inspect: %w", err)
			}
			status := strings.TrimSpace(string(stdout))
			if status == "exited" || status == "dead" {
				return nil
			}

			// Check for done file.
			res, err := p.Exec(ctx, id, []string{"test", "-f", "/sandbox/.arena/done"})
			if err == nil && res.ExitCode == 0 {
				return nil
			}
		}
	}
}

// Logs retrieves the stdout/stderr logs of a sandbox container.
func (p *Provider) Logs(ctx context.Context, id string, tail int) ([]byte, error) {
	stdout, stderr, err := p.run(ctx, "logs", "--tail", strconv.Itoa(tail), id)
	if err != nil {
		return nil, fmt.Errorf("docker logs: %w (stderr: %s)", err, string(stderr))
	}
	return stdout, nil
}

// parseMemory converts human-readable memory strings (e.g. "8g", "512m") to bytes.
func parseMemory(s string) (int64, error) {
	s = strings.TrimSpace(strings.ToLower(s))
	if s == "" {
		return 0, nil
	}

	var multiplier int64 = 1
	switch {
	case strings.HasSuffix(s, "gb") || strings.HasSuffix(s, "g"):
		multiplier = 1024 * 1024 * 1024
		s = strings.TrimSuffix(s, "gb")
		s = strings.TrimSuffix(s, "g")
	case strings.HasSuffix(s, "mb") || strings.HasSuffix(s, "m"):
		multiplier = 1024 * 1024
		s = strings.TrimSuffix(s, "mb")
		s = strings.TrimSuffix(s, "m")
	case strings.HasSuffix(s, "kb") || strings.HasSuffix(s, "k"):
		multiplier = 1024
		s = strings.TrimSuffix(s, "kb")
		s = strings.TrimSuffix(s, "k")
	}

	n, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid memory %q", s)
	}
	return n * multiplier, nil
}
