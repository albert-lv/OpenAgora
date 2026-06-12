package verify

import (
	"bufio"
	"regexp"
	"strings"
)

// CargoParser parses `cargo test` output.
type CargoParser struct{}

var cargoTestRe = regexp.MustCompile(`^test (?P<name>\S+) \.\.\. (?P<status>ok|FAILED|ignored|FAILED)$`)

func (p CargoParser) Parse(stdout, stderr string) ([]TestCase, error) {
	var cases []TestCase
	for _, block := range []string{stdout, stderr} {
		scanner := bufio.NewScanner(strings.NewReader(block))
		for scanner.Scan() {
			line := scanner.Text()
			matches := cargoTestRe.FindStringSubmatch(line)
			if matches == nil {
				continue
			}
			name := matches[1]
			status := matches[2]
			cases = append(cases, TestCase{
				ID:     name,
				Status: normalizeCargoStatus(status),
			})
		}
	}
	return cases, nil
}

func normalizeCargoStatus(status string) TestStatus {
	switch status {
	case "ok":
		return StatusPass
	case "FAILED":
		return StatusFail
	case "ignored":
		return StatusSkip
	default:
		return StatusUnknown
	}
}
