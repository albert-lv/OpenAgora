package verify

import (
	"bufio"
	"encoding/json"
	"fmt"
	"strings"
)

// GoTestParser parses `go test -json` output.
type GoTestParser struct{}

func (p GoTestParser) Parse(stdout, stderr string) ([]TestCase, error) {
	var cases []TestCase
	scanner := bufio.NewScanner(strings.NewReader(stdout + "\n" + stderr))
	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}
		var event struct {
			Action  string `json:"Action"`
			Test    string `json:"Test"`
			Package string `json:"Package"`
			Output  string `json:"Output"`
		}
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			continue
		}
		if event.Test == "" {
			continue
		}
		id := fmt.Sprintf("%s/%s", event.Package, event.Test)
		switch event.Action {
		case "pass":
			cases = append(cases, TestCase{ID: id, Status: StatusPass})
		case "fail":
			cases = append(cases, TestCase{ID: id, Status: StatusFail})
		case "skip":
			cases = append(cases, TestCase{ID: id, Status: StatusSkip})
		}
	}
	return cases, scanner.Err()
}
