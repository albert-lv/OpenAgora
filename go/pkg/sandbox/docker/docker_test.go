package docker

import (
	"testing"
)

func TestParseMemory(t *testing.T) {
	cases := []struct {
		input    string
		expected int64
		wantErr  bool
	}{
		{"", 0, false},
		{"1g", 1 << 30, false},
		{"1G", 1 << 30, false},
		{"1gb", 1 << 30, false},
		{"512m", 512 << 20, false},
		{"512M", 512 << 20, false},
		{"512mb", 512 << 20, false},
		{"1024k", 1024 << 10, false},
		{"1024K", 1024 << 10, false},
		{"1024kb", 1024 << 10, false},
		{"8g", 8 << 30, false},
		{"bad", 0, true},
	}

	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			got, err := parseMemory(tc.input)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error for %q", tc.input)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.expected {
				t.Fatalf("parseMemory(%q) = %d, want %d", tc.input, got, tc.expected)
			}
		})
	}
}

func TestNewProvider(t *testing.T) {
	p := NewProvider()
	if p == nil {
		t.Fatal("NewProvider returned nil")
	}
}
