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

// init registers the built-in verifiers.
func init() {
	Register("swe-bench", NewSWEBenchVerifier())
	Register("legacy", &legacyVerifier{})
}

// RegisterDefault registers the default verifiers. It is safe to call multiple times.
func RegisterDefault() {
	Register("swe-bench", NewSWEBenchVerifier())
	Register("legacy", &legacyVerifier{})
}

// multiRewardVerifier runs multiple independent verifiers and aggregates their
// scores into a single VerificationReport with multiple Reward dimensions.
type multiRewardVerifier struct{}

func (m *multiRewardVerifier) Name() string { return "multi-reward" }

func (m *multiRewardVerifier) Run(ctx context.Context, provider sandbox.Provider, spec *VerificationSpec, sandboxID string) (*VerificationReport, error) {
	if provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}
	if spec == nil || len(spec.Rewards) == 0 {
		return nil, fmt.Errorf("multi-reward verifier requires at least one reward spec")
	}

	var rewards []Reward
	var stdout, stderr strings.Builder

	for _, rw := range spec.Rewards {
		cmd := rw.Command
		if cmd == "" {
			// Default to running tests under the verifier dir.
			cmd = fmt.Sprintf("cd %s && pytest", rw.VerifierDir)
		}

		res, err := provider.Exec(ctx, sandboxID, []string{"sh", "-c", cmd})
		if err != nil {
			return nil, fmt.Errorf("exec reward %q: %w", rw.Name, err)
		}

		_, _ = fmt.Fprintf(&stdout, "\n=== %s ===\n", rw.Name)
		stdout.Write(res.Stdout)
		_, _ = fmt.Fprintf(&stderr, "\n=== %s ===\n", rw.Name)
		stderr.Write(res.Stderr)

		value := m.aggregate(rw.Aggregation, res.ExitCode, string(res.Stdout)+"\n"+string(res.Stderr))
		rewards = append(rewards, Reward{
			Name:   rw.Name,
			Value:  value,
			Weight: rw.Weight,
			Source: fmt.Sprintf("verifier:%s", rw.Name),
		})
	}

	total := TotalReward(rewards)
	return &VerificationReport{
		Reward:      total,
		TotalReward: total,
		Rewards:     rewards,
		Stdout:      stdout.String(),
		Stderr:      stderr.String(),
	}, nil
}

func (m *multiRewardVerifier) aggregate(mode string, exitCode int, output string) float64 {
	switch mode {
	case "all_pass":
		if exitCode == 0 {
			return 1.0
		}
		return 0.0
	case "max":
		if exitCode == 0 {
			return 1.0
		}
		return 0.0
	case "mean":
		// Try to parse a fraction from test output, fall back to pass/fail.
		if v := ParsePytestDetailedOutput(output); v >= 0 {
			return v
		}
		if exitCode == 0 {
			return 1.0
		}
		return 0.0
	default:
		if exitCode == 0 {
			return 1.0
		}
		return 0.0
	}
}

// legacyVerifier implements the original single-command verification behavior.
type legacyVerifier struct{}

func (l *legacyVerifier) Name() string { return "legacy" }

func (l *legacyVerifier) Run(ctx context.Context, provider sandbox.Provider, spec *VerificationSpec, sandboxID string) (*VerificationReport, error) {
	if provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}
	if spec == nil || spec.Command == "" {
		return nil, fmt.Errorf("legacy verifier requires a command")
	}

	res, err := provider.Exec(ctx, sandboxID, []string{"sh", "-c", spec.Command})
	if err != nil {
		return nil, fmt.Errorf("exec verify command: %w", err)
	}

	mode := DetectMode(spec.Command)
	stdout := string(res.Stdout)
	stderr := string(res.Stderr)
	combined := stdout + "\n" + stderr

	var rewards []Reward
	switch mode {
	case ModePytest:
		rewards = append(rewards, Reward{Name: "pytest", Value: ParsePytestDetailedOutput(combined), Source: "verifier:pytest"})
	case ModeUnittest:
		rewards = append(rewards, Reward{Name: "unittest", Value: ParseUnittestOutput(combined), Source: "verifier:unittest"})
	case ModeScript, ModeCustom:
		if res.ExitCode == 0 {
			rewards = append(rewards, Reward{Name: "script", Value: 1.0, Source: "verifier:exit_code"})
		} else {
			rewards = append(rewards, Reward{Name: "script", Value: 0.0, Source: "verifier:exit_code"})
		}
	}

	// Append agent-written custom rewards if present.
	customRewards, _ := readRewardsJSONL(ctx, provider, sandboxID)
	rewards = append(rewards, customRewards...)

	total := TotalReward(rewards)
	return &VerificationReport{
		Reward:      total,
		TotalReward: total,
		Rewards:     rewards,
		Stdout:      stdout,
		Stderr:      stderr,
	}, nil
}

// Runner is the original verification runner. It is kept for backward compatibility
// and now delegates to the legacy verifier internally.
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
	ModeUnknown  VerifyMode = iota
	ModePytest              // pytest with detailed pass/fail parsing
	ModeUnittest            // python -m unittest
	ModeScript              // generic shell script (exit code only)
	ModeCustom              // agent-written rewards.jsonl only
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

// Run executes the verification command in the given sandbox and returns reward signals.
// Deprecated: use a Verifier implementation instead.
func (r *Runner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	if r.provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}

	mode := DetectMode(command)
	res, err := r.provider.Exec(ctx, sandboxID, []string{"sh", "-c", command})
	if err != nil {
		return nil, fmt.Errorf("exec verify command: %w", err)
	}

	combined := string(res.Stdout) + "\n" + string(res.Stderr)
	var rewards []float64

	switch mode {
	case ModePytest:
		rewards = append(rewards, ParsePytestDetailedOutput(combined))
	case ModeUnittest:
		rewards = append(rewards, ParseUnittestOutput(combined))
	case ModeScript, ModeCustom:
		if res.ExitCode == 0 {
			rewards = append(rewards, 1.0)
		} else {
			rewards = append(rewards, 0.0)
		}
	}

	customRewards, _ := readRewardsJSONL(ctx, r.provider, sandboxID)
	for _, rw := range customRewards {
		rewards = append(rewards, rw.Value)
	}

	return rewards, nil
}

func readRewardsJSONL(ctx context.Context, provider sandbox.Provider, sandboxID string) ([]Reward, error) {
	res, err := provider.Exec(ctx, sandboxID, []string{"cat", "/sandbox/.arena/rewards.jsonl"})
	if err != nil {
		return nil, err
	}
	if res.ExitCode != 0 {
		return nil, fmt.Errorf("rewards.jsonl not found")
	}

	var rewards []Reward
	scanner := bufio.NewScanner(strings.NewReader(string(res.Stdout)))
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry struct {
			Type   string  `json:"type"`
			Name   string  `json:"name"`
			Value  float64 `json:"value"`
			Weight float64 `json:"weight"`
			Source string  `json:"source"`
		}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		name := entry.Name
		if name == "" {
			name = entry.Type
		}
		if name == "" {
			name = "agent_reward"
		}
		rewards = append(rewards, Reward{
			Name:   name,
			Value:  entry.Value,
			Weight: entry.Weight,
			Source: entry.Source,
		})
	}
	return rewards, scanner.Err()
}

// ParsePytestDetailedOutput scans pytest stdout/stderr for pass/fail counts
// and returns a fractional reward (passed / total).
func ParsePytestDetailedOutput(output string) float64 {
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
	return ParsePytestOutput(output)
}

// ParseUnittestOutput scans unittest stdout/stderr for OK/FAIL and returns reward.
func ParseUnittestOutput(output string) float64 {
	lines := strings.Split(output, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "OK") {
			return 1.0
		}
		if strings.HasPrefix(line, "FAILED") || strings.HasPrefix(line, "FAIL") {
			return 0.0
		}
	}
	return 0.0
}

// ParsePytestOutput scans pytest stdout for pass/fail counts and returns a reward.
func ParsePytestOutput(stdout string) float64 {
	lines := strings.Split(stdout, "\n")
	for _, line := range lines {
		if strings.Contains(line, "passed") && !strings.Contains(line, "failed") {
			return 1.0
		}
		if strings.Contains(line, "failed") && !strings.Contains(line, "passed") {
			return 0.0
		}
	}
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
