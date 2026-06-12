package verify

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

// SWEBenchVerifier runs baseline and patch tests and computes F2F/F2P/P2P/P2F metrics.
type SWEBenchVerifier struct {
	parsers map[string]TestFrameworkParser
}

// NewSWEBenchVerifier creates a SWE-bench verifier with default parsers.
func NewSWEBenchVerifier() *SWEBenchVerifier {
	return &SWEBenchVerifier{
		parsers: map[string]TestFrameworkParser{
			"pytest": PytestParser{},
			"jest":    JestParser{},
			"go":      GoTestParser{},
			"cargo":   CargoParser{},
			"maven":   MavenParser{},
		},
	}
}

// Name returns the verifier identifier.
func (s *SWEBenchVerifier) Name() string { return "swe-bench" }

// RegisterParser adds or overrides a parser for a framework.
func (s *SWEBenchVerifier) RegisterParser(framework string, p TestFrameworkParser) {
	s.parsers[strings.ToLower(framework)] = p
}

// Run executes baseline + patch verification.
func (s *SWEBenchVerifier) Run(ctx context.Context, provider sandbox.Provider, spec *VerificationSpec, sandboxID string) (*VerificationReport, error) {
	if provider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}
	if spec == nil {
		return nil, fmt.Errorf("verification spec is nil")
	}

	parser := s.selectParser(spec)
	workdir := spec.WorkingDirectory
	if workdir == "" {
		workdir = "/testbed"
	}
	if workdir != "" && !strings.HasPrefix(workdir, "/") {
		workdir = "/" + workdir
	}

	// Optional install step.
	if spec.InstallCommand != "" {
		if _, err := s.exec(ctx, provider, sandboxID, workdir, spec.InstallCommand, spec.Timeout); err != nil {
			return nil, fmt.Errorf("install command failed: %w", err)
		}
	}

	// Baseline tests.
	baselineCmd := spec.BaselineCommand
	if baselineCmd == "" && spec.Command != "" {
		// Legacy fallback: treat single command as both baseline and patch.
		baselineCmd = spec.Command
	}
	baselineRes, err := s.exec(ctx, provider, sandboxID, workdir, baselineCmd, spec.Timeout)
	if err != nil {
		return nil, fmt.Errorf("baseline command failed: %w", err)
	}
	baselineCases, err := parser.Parse(string(baselineRes.Stdout), string(baselineRes.Stderr))
	if err != nil {
		return nil, fmt.Errorf("parse baseline output: %w", err)
	}

	// Patch tests.
	patchCmd := spec.PatchCommand
	if patchCmd == "" && spec.Command != "" {
		patchCmd = spec.Command
	}
	patchRes, err := s.exec(ctx, provider, sandboxID, workdir, patchCmd, spec.Timeout)
	if err != nil {
		return nil, fmt.Errorf("patch command failed: %w", err)
	}
	patchCases, err := parser.Parse(string(patchRes.Stdout), string(patchRes.Stderr))
	if err != nil {
		return nil, fmt.Errorf("parse patch output: %w", err)
	}

	// Diff and compute report.
	report := s.diff(baselineCases, patchCases, spec.PassToPass, spec.FailToPass)
	report.Stdout = string(patchRes.Stdout)
	report.Stderr = string(patchRes.Stderr)
	return report, nil
}

func (s *SWEBenchVerifier) selectParser(spec *VerificationSpec) TestFrameworkParser {
	framework := strings.ToLower(spec.Framework)
	if framework == "" {
		// Infer from command.
		cmd := strings.ToLower(spec.BaselineCommand + " " + spec.PatchCommand + " " + spec.Command)
		switch {
		case strings.Contains(cmd, "pytest"):
			framework = "pytest"
		case strings.Contains(cmd, "jest"):
			framework = "jest"
		case strings.Contains(cmd, "go test"):
			framework = "go"
		case strings.Contains(cmd, "cargo test"):
			framework = "cargo"
		case strings.Contains(cmd, "mvn"):
			framework = "maven"
		}
	}
	if p, ok := s.parsers[framework]; ok {
		return p
	}
	// Fallback: treat each non-empty line as a test result with binary status.
	return ParserFunc(fallbackParser)
}

func fallbackParser(stdout, stderr string) ([]TestCase, error) {
	output := stdout + "\n" + stderr
	var cases []TestCase
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		// Heuristic: lines containing "PASS" or "FAIL".
		status := StatusUnknown
		if strings.Contains(line, "PASS") && !strings.Contains(line, "FAIL") {
			status = StatusPass
		} else if strings.Contains(line, "FAIL") {
			status = StatusFail
		} else {
			continue
		}
		cases = append(cases, TestCase{ID: line, Status: status})
	}
	return cases, nil
}

func (s *SWEBenchVerifier) exec(ctx context.Context, provider sandbox.Provider, sandboxID, workdir, command string, timeout time.Duration) (*sandbox.ExecResult, error) {
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	wrapped := command
	if workdir != "" {
		wrapped = fmt.Sprintf("cd %s && %s", workdir, command)
	}
	return provider.Exec(ctx, sandboxID, []string{"sh", "-c", wrapped})
}

func (s *SWEBenchVerifier) diff(baseline, patch []TestCase, p2pFilter, f2pFilter []string) *VerificationReport {
	baselineMap := make(map[string]TestStatus)
	for _, c := range baseline {
		baselineMap[c.ID] = c.Status
	}
	patchMap := make(map[string]TestStatus)
	for _, c := range patch {
		patchMap[c.ID] = c.Status
	}

	filter := unionSets(p2pFilter, f2pFilter)
	useFilter := len(filter) > 0

	report := &VerificationReport{}
	seen := make(map[string]bool)

	for id := range unionKeys(baselineMap, patchMap) {
		if useFilter && !filter[id] {
			continue
		}
		seen[id] = true
		baseStatus := baselineMap[id]
		patchStatus := patchMap[id]

		// Default missing to fail.
		if baseStatus == "" {
			baseStatus = StatusFail
		}
		if patchStatus == "" {
			patchStatus = StatusFail
		}

		category := categorize(baseStatus, patchStatus)
		report.TestCases = append(report.TestCases, TestCaseTransition{
			TestCase: TestCase{
				ID:     id,
				Status: patchStatus,
			},
			BaselineStatus: baseStatus,
			PatchStatus:    patchStatus,
			Category:       category,
		})
	}

	report.ComputeCounts()
	report.Reward = computeReward(report)
	return report
}

func categorize(baseline, patch TestStatus) Category {
	basePass := baseline == StatusPass
	patchPass := patch == StatusPass
	switch {
	case !basePass && patchPass:
		return CategoryF2P
	case basePass && patchPass:
		return CategoryP2P
	case !basePass && !patchPass:
		return CategoryF2F
	case basePass && !patchPass:
		return CategoryP2F
	}
	return CategoryF2F
}

func computeReward(r *VerificationReport) float64 {
	total := r.F2PCount + r.P2PCount + r.F2FCount + r.P2FCount
	if total == 0 {
		return 0.0
	}
	// Primary: proportion of desired outcomes (F2P + P2P).
	score := float64(r.F2PCount+r.P2PCount) / float64(total)
	// Penalize regressions.
	if r.P2FCount > 0 {
		penalty := float64(r.P2FCount) / float64(total)
		score -= penalty
		if score < 0 {
			score = 0
		}
	}
	return score
}

func unionSets(a, b []string) map[string]bool {
	m := make(map[string]bool)
	for _, v := range a {
		m[v] = true
	}
	for _, v := range b {
		m[v] = true
	}
	return m
}

func unionKeys(maps ...map[string]TestStatus) map[string]bool {
	keys := make(map[string]bool)
	for _, m := range maps {
		for k := range m {
			keys[k] = true
		}
	}
	return keys
}
