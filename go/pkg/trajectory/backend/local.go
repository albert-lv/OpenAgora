package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/albert-lv/agent-arena/go/pkg/trajectory"
)

// LocalJSONL implements a local JSONL file backend.
type LocalJSONL struct {
	Dir string
}

// NewLocalJSONL creates a new local JSONL backend.
func NewLocalJSONL(dir string) *LocalJSONL {
	return &LocalJSONL{Dir: dir}
}

// Write appends a trajectory step to the rollout's JSONL file.
func (b *LocalJSONL) Write(ctx context.Context, rolloutID string, step *trajectory.Step) error {
	fpath := filepath.Join(b.Dir, rolloutID+".jsonl")
	f, err := os.OpenFile(fpath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("local backend: open file: %w", err)
	}
	defer func() { _ = f.Close() }()

	line, err := json.Marshal(step)
	if err != nil {
		return fmt.Errorf("local backend: marshal step: %w", err)
	}

	if _, err := f.Write(line); err != nil {
		return fmt.Errorf("local backend: write: %w", err)
	}
	if _, err := f.WriteString("\n"); err != nil {
		return fmt.Errorf("local backend: write newline: %w", err)
	}
	return nil
}

// Read streams the trajectory for a rollout to the given writer.
func (b *LocalJSONL) Read(ctx context.Context, rolloutID string, w io.Writer) error {
	fpath := filepath.Join(b.Dir, rolloutID+".jsonl")
	f, err := os.Open(fpath)
	if err != nil {
		return fmt.Errorf("local backend: open file: %w", err)
	}
	defer func() { _ = f.Close() }()

	_, err = io.Copy(w, f)
	return err
}

// Close is a no-op for the local backend.
func (b *LocalJSONL) Close(ctx context.Context) error { return nil }
