package verify

import (
	"context"
	"fmt"
)

// Runner executes verification commands and produces reward signals.
type Runner struct{}

// NewRunner creates a new verification runner.
func NewRunner() *Runner {
	return &Runner{}
}

// Run executes the verification command in the given sandbox and returns rewards.
func (r *Runner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	return nil, fmt.Errorf("verify: not yet implemented")
}
