package verify

import (
	"encoding/json"
	"fmt"
	"strings"
)

// JestParser parses Jest --json output.
type JestParser struct{}

func (p JestParser) Parse(stdout, stderr string) ([]TestCase, error) {
	// Jest --json outputs one JSON object. Find the first '{'.
	start := strings.Index(stdout, "{")
	if start == -1 {
		return nil, fmt.Errorf("no JSON output from jest")
	}
	var report struct {
		TestResults []struct {
			Name             string `json:"name"`
			Status           string `json:"status"`
			AssertionResults []struct {
				Title           string   `json:"title"`
				Status          string   `json:"status"`
				FailureMessages []string `json:"failureMessages"`
			} `json:"assertionResults"`
		} `json:"testResults"`
	}
	if err := json.Unmarshal([]byte(stdout[start:]), &report); err != nil {
		return nil, err
	}

	var cases []TestCase
	for _, result := range report.TestResults {
		for _, ar := range result.AssertionResults {
			cases = append(cases, TestCase{
				ID:     fmt.Sprintf("%s > %s", result.Name, ar.Title),
				Status: normalizeOutcome(ar.Status),
			})
		}
	}
	return cases, nil
}
