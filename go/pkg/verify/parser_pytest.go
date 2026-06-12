package verify

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

// PytestParser parses pytest output.
// It prefers pytest-json-report format when available, otherwise falls back to
// parsing verbose output lines like "tests/test_foo.py::test_bar PASSED".
type PytestParser struct{}

func (p PytestParser) Parse(stdout, stderr string) ([]TestCase, error) {
	// Try JSON report first.
	if cases, err := p.parseJSON(stdout); err == nil && len(cases) > 0 {
		return cases, nil
	}
	// Fall back to verbose line parsing.
	return p.parseVerbose(stdout + "\n" + stderr), nil
}

func (p PytestParser) parseJSON(output string) ([]TestCase, error) {
	// pytest-json-report writes a single JSON object. Extract the first JSON object.
	start := strings.Index(output, "{\"")
	if start == -1 {
		return nil, fmt.Errorf("no JSON object found")
	}
	end := strings.LastIndex(output, "}")
	if end == -1 || end <= start {
		return nil, fmt.Errorf("malformed JSON")
	}
	var report struct {
		Tests []struct {
			NodeID   string  `json:"nodeid"`
			Outcome  string  `json:"outcome"`
			Duration float64 `json:"duration"`
		} `json:"tests"`
	}
	if err := json.Unmarshal([]byte(output[start:end+1]), &report); err != nil {
		return nil, err
	}

	cases := make([]TestCase, 0, len(report.Tests))
	for _, t := range report.Tests {
		cases = append(cases, TestCase{
			ID:     t.NodeID,
			Status: normalizeOutcome(t.Outcome),
		})
	}
	return cases, nil
}

var verboseLineRe = regexp.MustCompile(`^(?P<file>.+?)::(?P<test>.+?) (?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)`)

func (p PytestParser) parseVerbose(output string) []TestCase {
	var cases []TestCase
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		matches := verboseLineRe.FindStringSubmatch(line)
		if matches == nil {
			continue
		}
		file := matches[1]
		test := matches[2]
		status := matches[3]
		cases = append(cases, TestCase{
			ID:     fmt.Sprintf("%s::%s", file, test),
			Status: normalizeOutcome(status),
		})
	}
	return cases
}

func normalizeOutcome(outcome string) TestStatus {
	switch strings.ToLower(outcome) {
	case "passed", "pass":
		return StatusPass
	case "failed", "fail", "failure":
		return StatusFail
	case "error":
		return StatusError
	case "skipped", "skip":
		return StatusSkip
	default:
		return StatusUnknown
	}
}
