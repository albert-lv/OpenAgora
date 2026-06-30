package verify

import (
	"encoding/xml"
	"fmt"
	"strings"
)

// MavenParser parses Maven Surefire XML reports.
type MavenParser struct{}

func (p MavenParser) Parse(stdout, stderr string) ([]TestCase, error) {
	// Surefire XML is the most reliable source. stdout may contain the XML report
	// or we may need to cat target/surefire-reports/*.xml separately. Here we parse
	// any <testsuite> block found in stdout.
	var cases []TestCase
	for {
		start := strings.Index(stdout, "<testsuite")
		if start == -1 {
			break
		}
		end := strings.Index(stdout[start:], "</testsuite>")
		if end == -1 {
			break
		}
		block := stdout[start : start+end+len("</testsuite>")]
		stdout = stdout[start+end+len("</testsuite>"):]

		var suite struct {
			Cases []struct {
				Name      string `xml:"name,attr"`
				ClassName string `xml:"classname,attr"`
				Failure   *struct {
					Message string `xml:"message,attr"`
				} `xml:"failure"`
				Skipped *struct{} `xml:"skipped"`
				Error   *struct {
					Message string `xml:"message,attr"`
				} `xml:"error"`
			} `xml:"testcase"`
		}
		if err := xml.Unmarshal([]byte(block), &suite); err != nil {
			continue
		}
		for _, c := range suite.Cases {
			status := StatusPass
			if c.Failure != nil {
				status = StatusFail
			} else if c.Error != nil {
				status = StatusError
			} else if c.Skipped != nil {
				status = StatusSkip
			}
			cases = append(cases, TestCase{
				ID:     fmt.Sprintf("%s#%s", c.ClassName, c.Name),
				Status: status,
			})
		}
	}
	return cases, nil
}
