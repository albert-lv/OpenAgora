package sandbox

import (
	"context"
	"time"
)

// Provider defines the interface for sandbox lifecycle management.
type Provider interface {
	Create(ctx context.Context, config *Config) (*Sandbox, error)
	Start(ctx context.Context, id string) error
	Stop(ctx context.Context, id string) error
	Destroy(ctx context.Context, id string) error
	Exec(ctx context.Context, id string, cmd []string) (*ExecResult, error)
	WaitForDone(ctx context.Context, id string) error
	Logs(ctx context.Context, id string, tail int) ([]byte, error)
}

// Config describes the sandbox configuration.
type Config struct {
	Image    string
	Memory   string
	CPUs     float64
	EnvVars  map[string]string
	TaskFile []byte
	Timeout  time.Duration
}

// Sandbox represents a running sandbox instance.
type Sandbox struct {
	ID      string
	Status  string
	Config  *Config
	Created time.Time
}

// ExecResult holds the output of a command execution.
type ExecResult struct {
	ExitCode int
	Stdout   []byte
	Stderr   []byte
}
