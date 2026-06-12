package verify

import (
	"time"

	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
)

// TestStatus represents the outcome of a single test case.
type TestStatus string

const (
	StatusPass    TestStatus = "pass"
	StatusFail    TestStatus = "fail"
	StatusSkip    TestStatus = "skip"
	StatusError   TestStatus = "error"
	StatusTimeout TestStatus = "timeout"
	StatusUnknown TestStatus = "unknown"
)

// TestCase is a normalized representation of one test result.
type TestCase struct {
	ID       string
	Status   TestStatus
	Duration time.Duration
	Stdout   string
	Stderr   string
}

// Category describes the transition of a test case from baseline to patch.
type Category string

const (
	CategoryF2F Category = "F2F" // Fail -> Fail
	CategoryF2P Category = "F2P" // Fail -> Pass
	CategoryP2P Category = "P2P" // Pass -> Pass
	CategoryP2F Category = "P2F" // Pass -> Fail
)

// TestCaseTransition pairs a test case with its SWE-bench category.
type TestCaseTransition struct {
	TestCase
	BaselineStatus TestStatus
	PatchStatus    TestStatus
	Category       Category
}

// VerificationSpec is the Go-side representation of a verification request.
type VerificationSpec struct {
	Command           string
	LogParser         string
	PassToPass        []string
	FailToPass        []string
	Language          string
	Framework         string
	InstallCommand    string
	BaselineCommand   string
	PatchCommand      string
	Timeout           time.Duration
	WorkingDirectory  string
}

// FromProto converts a protobuf VerifyConfig into a VerificationSpec.
func FromProto(cfg *arena_pb.VerifyConfig) *VerificationSpec {
	if cfg == nil {
		return nil
	}
	timeout := time.Duration(cfg.TimeoutSeconds) * time.Second
	if timeout == 0 {
		timeout = 5 * time.Minute
	}
	return &VerificationSpec{
		Command:          cfg.Command,
		LogParser:        cfg.LogParser,
		PassToPass:       cfg.PassToPass,
		FailToPass:       cfg.FailToPass,
		Language:         cfg.Language,
		Framework:        cfg.Framework,
		InstallCommand:   cfg.InstallCommand,
		BaselineCommand:  cfg.BaselineCommand,
		PatchCommand:     cfg.PatchCommand,
		Timeout:          timeout,
		WorkingDirectory: cfg.WorkingDirectory,
	}
}
