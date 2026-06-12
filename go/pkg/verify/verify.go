package verify

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// Runner executes verification commands and produces reward signals.
type Runner struct {
	provider sandbox.Provider
}

// NewRunner creates a new verification runner.
func NewRunner(provider sandbox.Provider) *Runner {
	return &Runner{provider: provider}
}

// VerifyMode describes how a verify command should be interpreted.
type VerifyMode int

const (
	ModeUnknown   VerifyMode = iota
	ModePytest               // pytest with detailed pass/fail parsing
	ModeUnittest             // python -m unittest
	ModeScript               // generic shell script (exit code only)
	ModeCustom               // agent-written rewards.jsonl only
)

// DetectMode guesses the verify mode from the command string.
func DetectMode(command string) VerifyMode {
	lower := strings.ToLower(command)
	if strings.Contains(lower, "pytest") {
		return ModePytest
	}
	if strings.Contains(lower, "unittest") {
		return ModeUnittest
	}
	if strings.TrimSpace(command) == "true" || strings.TrimSpace(command) == "" {
		return ModeCustom
	}
	return ModeScript
}

// Run executes the verification command in the given sandbox and returns rewards.
// It also reads any custom rewards written by the agent to /sandbox/.arena/rewards.jsonl.
func (r *Runner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	if r.provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}

	mode := DetectMode(command)

	// Execute the verification command.
	res, err := r.provider.Exec(ctx, sandboxID, []string{"sh", "-c", command})
	if err != nil {
		return nil, fmt.Errorf("exec verify command: %w", err)
	}

	var rewards []float64

	switch mode {
	case ModePytest:
		reward := ParsePytestDetailedOutput(string(res.Stdout) + "\n" + string(res.Stderr))
		rewards = append(rewards, reward)

	case ModeUnittest:
		reward := ParseUnittestOutput(string(res.Stdout) + "\n" + string(res.Stderr))
		rewards = append(rewards, reward)

	case ModeScript, ModeCustom:
		// Primary reward: command success = 1.0, failure = 0.0.
		if res.ExitCode == 0 {
			rewards = append(rewards, 1.0)
		} else {
			rewards = append(rewards, 0.0)
		}
	}

	// Read agent-written custom rewards (always append if present).
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

// ParsePytestDetailedOutput scans pytest stdout/stderr for pass/fail counts
// and returns a fractional reward (passed / total).
//
// Matches lines like:
//   "5 passed, 2 failed, 1 skipped in 0.03s"
//   "1 passed in 0.01s"
//   "3 failed in 0.02s"
func ParsePytestDetailedOutput(output string) float64 {
	// Look for the summary line.
	re := regexp.MustCompile(`(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?(?:, (\d+) error)? in `)
	lines := strings.Split(output, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		matches := re.FindStringSubmatch(line)
		if matches == nil {
			continue
		}
		passed, _ := strconv.Atoi(matches[1])
		failed := 0
		if matches[2] != "" {
			failed, _ = strconv.Atoi(matches[2])
		}
		skipped := 0
		if matches[3] != "" {
			skipped, _ = strconv.Atoi(matches[3])
		}
		errors := 0
		if matches[4] != "" {
			errors, _ = strconv.Atoi(matches[4])
		}
		total := passed + failed + skipped + errors
		if total == 0 {
			return 0.0
		}
		return float64(passed) / float64(total)
	}

	// Fallback: binary pass/fall based on presence of "passed" without "failed".
	return ParsePytestOutput(output)
}

// ParseUnittestOutput scans unittest stdout/stderr for OK/FAIL and returns reward.
func ParseUnittestOutput(output string) float64 {
	// Look for "OK" or "FAILED (failures=N, errors=M)" or "Ran N tests in ...".
	lines := strings.Split(output, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "OK") {
			return 1.0
		}
		if strings.HasPrefix(line, "FAILED") || strings.HasPrefix(line, "FAIL") {
			// Try to extract counts.
			re := regexp.MustCompile(`failures=(\d+)|errors=(\d+)`)
			matches := re.FindAllStringSubmatch(line, -1)
			failures := 0
			errors := 0
			for _, m := range matches {
				if m[1] != "" {
					v, _ := strconv.Atoi(m[1])
					failures += v
				}
				if m[2] != "" {
					v, _ := strconv.Atoi(m[2])
					errors += v
				}
			}
			// If we cannot parse counts, return 0.
			if failures == 0 && errors == 0 {
				return 0.0
			}
			return 0.0 // partial failure; unittest doesn't give total count easily.
		}
	}
	return 0.0
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
