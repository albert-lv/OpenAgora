package verify

import (
	"context"
	"fmt"
	"strings"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Verifier is a pluggable verification backend.
type Verifier interface {
	// Name returns the verifier identifier, e.g. "swe-bench".
	Name() string

	// Run executes verification in the given sandbox and returns a structured report.
	Run(ctx context.Context, provider sandbox.Provider, spec *VerificationSpec, sandboxID string) (*VerificationReport, error)
}

var registry = make(map[string]Verifier)

// Register adds a verifier to the global registry.
func Register(name string, v Verifier) {
	registry[strings.ToLower(name)] = v
}

// Get retrieves a verifier by name.
func Get(name string) (Verifier, bool) {
	v, ok := registry[strings.ToLower(name)]
	return v, ok
}

// Default returns the default SWE-bench verifier if registered.
func Default() (Verifier, bool) {
	return Get("swe-bench")
}

// Resolve selects a verifier for the given spec.
// If spec.Framework is empty and spec.Command is non-empty, it falls back to
// the legacy single-command runner.
func Resolve(spec *VerificationSpec) (Verifier, error) {
	if spec == nil {
		return nil, fmt.Errorf("verification spec is nil")
	}

	// Multi-reward path: run multiple independent verifiers and aggregate.
	if len(spec.Rewards) > 1 {
		return &multiRewardVerifier{}, nil
	}

	// If a structured SWE-bench spec is provided, use the SWE-bench verifier.
	if spec.BaselineCommand != "" && spec.PatchCommand != "" {
		if v, ok := Default(); ok {
			return v, nil
		}
		return nil, fmt.Errorf("SWE-bench verifier not registered")
	}

	// Legacy path: single verify command.
	return &legacyVerifier{}, nil
}
