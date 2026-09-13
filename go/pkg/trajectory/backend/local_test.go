package backend

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
)

func testStep(rolloutID string) *trajectory.Step {
	return &trajectory.Step{
		RolloutID: rolloutID,
		Timestamp: time.Now(),
		Request:   &trajectory.LLMRequest{Endpoint: "/v1/chat/completions"},
		Response:  &trajectory.LLMResponse{Choices: []byte(`{"choices":[]}`)},
	}
}

func TestLocalJSONLBufferedWriteAndFinalize(t *testing.T) {
	dir := t.TempDir()
	b := NewLocalJSONL(dir)
	defer func() { _ = b.Close(context.Background()) }()

	ctx := context.Background()
	for i := 0; i < 3; i++ {
		if err := b.Write(ctx, "r1", testStep("r1")); err != nil {
			t.Fatalf("write: %v", err)
		}
	}

	// Data is buffered; Read must flush so it observes all writes.
	var buf bytes.Buffer
	if err := b.Read(ctx, "r1", &buf); err != nil {
		t.Fatalf("read: %v", err)
	}
	if n := strings.Count(strings.TrimSpace(buf.String()), "\n") + 1; n != 3 {
		t.Fatalf("expected 3 lines, got %d", n)
	}

	if err := b.Finalize(ctx, "r1"); err != nil {
		t.Fatalf("finalize: %v", err)
	}
	// Finalize is idempotent for unknown/finalized rollouts.
	if err := b.Finalize(ctx, "r1"); err != nil {
		t.Fatalf("finalize again: %v", err)
	}

	// After Finalize the on-disk file holds all records.
	raw, err := os.ReadFile(filepath.Join(dir, "r1.jsonl"))
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if n := strings.Count(strings.TrimSpace(string(raw)), "\n") + 1; n != 3 {
		t.Fatalf("expected 3 lines on disk, got %d", n)
	}

	// Writing again after Finalize reopens the file and appends.
	if err := b.Write(ctx, "r1", testStep("r1")); err != nil {
		t.Fatalf("write after finalize: %v", err)
	}
	if err := b.Finalize(ctx, "r1"); err != nil {
		t.Fatalf("finalize after rewrite: %v", err)
	}
	raw, err = os.ReadFile(filepath.Join(dir, "r1.jsonl"))
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if n := strings.Count(strings.TrimSpace(string(raw)), "\n") + 1; n != 4 {
		t.Fatalf("expected 4 lines on disk, got %d", n)
	}
}

func TestLocalJSONLWriteBufferedUntilFlush(t *testing.T) {
	dir := t.TempDir()
	b := NewLocalJSONL(dir)
	defer func() { _ = b.Close(context.Background()) }()

	ctx := context.Background()
	if err := b.Write(ctx, "r1", testStep("r1")); err != nil {
		t.Fatalf("write: %v", err)
	}

	// The write sits in the buffer until a flush (interval, Read, Finalize,
	// or Close); the file exists but the record is not yet on disk.
	raw, err := os.ReadFile(filepath.Join(dir, "r1.jsonl"))
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if len(raw) != 0 {
		t.Fatal("expected write to be buffered, not yet on disk")
	}

	// Read flushes, making buffered data visible.
	var buf bytes.Buffer
	if err := b.Read(ctx, "r1", &buf); err != nil {
		t.Fatalf("read: %v", err)
	}
	if buf.Len() == 0 {
		t.Fatal("expected buffered data to be visible via Read")
	}
}

func TestLocalJSONLClose(t *testing.T) {
	dir := t.TempDir()
	b := NewLocalJSONL(dir)
	ctx := context.Background()

	if err := b.Write(ctx, "r1", testStep("r1")); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := b.Close(ctx); err != nil {
		t.Fatalf("close: %v", err)
	}
	// Close is idempotent.
	if err := b.Close(ctx); err != nil {
		t.Fatalf("close again: %v", err)
	}
	// Close flushed pending data.
	raw, err := os.ReadFile(filepath.Join(dir, "r1.jsonl"))
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if len(raw) == 0 {
		t.Fatal("expected data flushed on close")
	}
	// Writes after Close fail.
	if err := b.Write(ctx, "r1", testStep("r1")); err == nil {
		t.Fatal("expected error writing after close")
	}
}
