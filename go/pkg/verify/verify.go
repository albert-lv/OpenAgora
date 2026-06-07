package verify

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/albert-lv/agent-arena/go/pkg/sandbox"
)

// Runner executes verification commands and produces reward signals.
type Runner struct {
	provider sandbox.Provider
}

// NewRunner creates a new verification runner.
func NewRunner(provider sandbox.Provider) *Runner {
	return &Runner{provider: provider}
}

// Run executes the verification command in the given sandbox and returns rewards.
// It also reads any custom rewards written by the agent to /sandbox/.arena/rewards.jsonl.
func (r *Runner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	if r.provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}

	// Execute the verification command.
	res, err := r.provider.Exec(ctx, sandboxID, []string{"sh", "-c", command})
	if err != nil {
		return nil, fmt.Errorf("exec verify command: %w", err)
	}

	var rewards []float64

	// Primary reward: command success = 1.0, failure = 0.0.
	if res.ExitCode == 0 {
		rewards = append(rewards, 1.0)
	} else {
		rewards = append(rewards, 0.0)
	}

	// Read agent-written custom rewards.
	customRewards, err := r.readRewardsJSONL(ctx, sandboxID)
	if err == nil {
		rewards = append(rewards, customRewards...)
	}

	return rewards, nil
}

// readRewardsJSONL reads /sandbox/.arena/rewards.jsonl from the sandbox.
func (r *Runner) readRewardsJSONL(ctx context.Context, sandboxID string) ([]float64, error) {
	res, err := r.provider.Exec(ctx, sandboxID, []string{"cat", "/sandbox/.arena/rewards.jsonl"})
	if err != nil {
		return nil, err
	}
	if res.ExitCode != 0 {
		return nil, fmt.Errorf("rewards.jsonl not found")
	}

	var rewards []float64
	scanner := bufio.NewScanner(strings.NewReader(string(res.Stdout)))
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry struct {
			Type   string  `json:"type"`
			Value  float64 `json:"value"`
			Source string  `json:"source"`
		}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		rewards = append(rewards, entry.Value)
	}
	return rewards, scanner.Err()
}

// ParsePytestOutput scans pytest stdout for pass/fail counts and returns a reward.
// This is a convenience helper; Run() itself does not call it automatically.
func ParsePytestOutput(stdout string) float64 {
	lines := strings.Split(stdout, "\n")
	for _, line := range lines {
		// Look for summary line like "1 passed in 0.01s"
		if strings.Contains(line, "passed") && !strings.Contains(line, "failed") {
			return 1.0
		}
		if strings.Contains(line, "failed") && !strings.Contains(line, "passed") {
			return 0.0
		}
	}
	// Default: if no clear summary, return 0.
	return 0.0
}

// ReadDoneSignal reads and parses the /sandbox/.arena/done file.
func ReadDoneSignal(ctx context.Context, provider sandbox.Provider, sandboxID string) (map[string]any, error) {
	res, err := provider.Exec(ctx, sandboxID, []string{"cat", "/sandbox/.arena/done"})
	if err != nil {
		return nil, err
	}
	if res.ExitCode != 0 {
		return nil, fmt.Errorf("done file not found")
	}
	var signal map[string]any
	if err := json.Unmarshal(res.Stdout, &signal); err != nil {
		return nil, fmt.Errorf("parse done signal: %w", err)
	}
	return signal, nil
}

// LocalRewardsReader reads rewards.jsonl from a local directory (for testing/debugging).
func LocalRewardsReader(dir string) ([]float64, error) {
	fpath := filepath.Join(dir, ".arena", "rewards.jsonl")
	data, err := os.ReadFile(fpath)
	if err != nil {
		return nil, err
	}
	var rewards []float64
	scanner := bufio.NewScanner(strings.NewReader(string(data)))
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry struct {
			Value float64 `json:"value"`
		}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		rewards = append(rewards, entry.Value)
	}
	return rewards, scanner.Err()
}
