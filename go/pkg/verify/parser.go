package verify

// TestFrameworkParser turns raw test output into normalized TestCases.
type TestFrameworkParser interface {
	// Parse extracts test cases from stdout/stderr.
	Parse(stdout, stderr string) ([]TestCase, error)
}

// ParserFunc allows a plain function to be used as a TestFrameworkParser.
type ParserFunc func(stdout, stderr string) ([]TestCase, error)

// Parse implements TestFrameworkParser.
func (f ParserFunc) Parse(stdout, stderr string) ([]TestCase, error) {
	return f(stdout, stderr)
}
