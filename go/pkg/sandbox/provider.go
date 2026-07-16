package sandbox

import (
	"context"
	"fmt"
	"sync"
	"time"
)

// Provider defines the interface for sandbox lifecycle management.
type Provider interface {
	Create(ctx context.Context, config *Config) (*Sandbox, error)
	Start(ctx context.Context, id string) error
	Stop(ctx context.Context, id string) error
	Destroy(ctx context.Context, sb *Sandbox) error
	Exec(ctx context.Context, id string, cmd []string) (*ExecResult, error)
	WaitForDone(ctx context.Context, id string) error
	Logs(ctx context.Context, id string, tail int) ([]byte, error)
	// Capabilities returns the feature set supported by this provider.
	Capabilities() CapabilitySet
}

// Config describes the sandbox configuration.
type Config struct {
	Image    string
	Memory   string
	CPUs     float64
	EnvVars  map[string]string
	TaskFile []byte
	Timeout  time.Duration
	Command  []string // Optional agent adapter override for the container/command entrypoint.
}

// Sandbox represents a running sandbox instance.
type Sandbox struct {
	ID      string
	Status  string
	Config  *Config
	Created time.Time
	HostDir string // host directory bind-mounted to /sandbox; cleaned up on Destroy
}

// ExecResult holds the output of a command execution.
type ExecResult struct {
	ExitCode int
	Stdout   []byte
	Stderr   []byte
}

// CapabilitySet describes the features a sandbox provider supports.
// Modeled after Harbor's environment capabilities so OpenAgora can reason
// about whether a provider can run GPU workloads, block egress, etc.
type CapabilitySet struct {
	// FileTransfer indicates the provider supports Exec-based file operations.
	// True for Docker and local; remote providers may need upload/download.
	FileTransfer bool `json:"file_transfer"`

	// GPUs indicates the provider can expose GPU devices to sandboxes.
	GPUs bool `json:"gpus"`

	// DisableInternet indicates the provider can block outbound traffic.
	DisableInternet bool `json:"disable_internet"`

	// NetworkAllowlist indicates the provider supports a per-sandbox host allowlist.
	NetworkAllowlist bool `json:"network_allowlist"`

	// DynamicNetworkPolicy indicates the provider supports runtime firewall changes.
	DynamicNetworkPolicy bool `json:"dynamic_network_policy"`

	// Windows indicates Windows container/worker support.
	Windows bool `json:"windows"`

	// Mounted indicates the sandbox is mounted to a host path (bind mount).
	Mounted bool `json:"mounted"`

	// DockerCompose indicates the provider can run docker-compose environments.
	DockerCompose bool `json:"docker_compose"`
}

// ProviderConstructor creates a provider from optional config.
type ProviderConstructor func(config map[string]string) (Provider, error)

// ProviderFactory creates named sandbox providers.
// New providers can be registered at init time without changing the server CLI.
type ProviderFactory struct {
	mu       sync.RWMutex
	registry map[string]ProviderConstructor
}

// NewProviderFactory creates an empty factory.
func NewProviderFactory() *ProviderFactory {
	return &ProviderFactory{registry: make(map[string]ProviderConstructor)}
}

// Register adds or replaces a provider constructor.
func (f *ProviderFactory) Register(name string, ctor ProviderConstructor) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.registry[name] = ctor
}

// Create builds a provider by name. Returns an error if the name is unknown.
func (f *ProviderFactory) Create(name string, config map[string]string) (Provider, error) {
	f.mu.RLock()
	ctor, ok := f.registry[name]
	f.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("unknown sandbox provider %q (registered: %s)", name, f.registeredNames())
	}
	return ctor(config)
}

// Names returns the list of registered provider names.
func (f *ProviderFactory) Names() []string {
	f.mu.RLock()
	defer f.mu.RUnlock()
	names := make([]string, 0, len(f.registry))
	for name := range f.registry {
		names = append(names, name)
	}
	return names
}

func (f *ProviderFactory) registeredNames() string {
	names := f.Names()
	if len(names) == 0 {
		return "none"
	}
	return fmt.Sprintf("%v", names)
}

// defaultFactory is the global provider registry used by the server and CLI.
var defaultFactory = NewProviderFactory()

// Register registers a provider constructor with the global factory.
// Provider packages should call this from their init() function.
func RegisterProvider(name string, ctor ProviderConstructor) {
	defaultFactory.Register(name, ctor)
}

// DefaultProviderFactory returns the global provider factory.
func DefaultProviderFactory() *ProviderFactory {
	return defaultFactory
}
