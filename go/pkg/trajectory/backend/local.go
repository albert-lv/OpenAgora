package backend

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
)

const (
	defaultFlushInterval = 2 * time.Second
	defaultFlushBytes    = 64 * 1024
)

// LocalJSONL implements a local JSONL file backend.
// Writes are buffered per rollout: each rollout's file stays open and is
// flushed periodically, when the buffer fills, on Finalize (rollout
// completion), and on Close.
type LocalJSONL struct {
	Dir string

	// FlushInterval is the periodic flush cadence. Defaults to 2s.
	FlushInterval time.Duration
	// FlushBytes is the per-rollout buffer size. Defaults to 64KiB.
	FlushBytes int

	mu     sync.Mutex
	files  map[string]*jsonlFile
	done   chan struct{}
	closed bool
	wg     sync.WaitGroup
}

type jsonlFile struct {
	f *os.File
	w *bufio.Writer
}

// NewLocalJSONL creates a new local JSONL backend.
func NewLocalJSONL(dir string) *LocalJSONL {
	b := &LocalJSONL{
		Dir:           dir,
		FlushInterval: defaultFlushInterval,
		FlushBytes:    defaultFlushBytes,
		files:         make(map[string]*jsonlFile),
		done:          make(chan struct{}),
	}
	b.wg.Add(1)
	go b.flushLoop()
	return b
}

func (b *LocalJSONL) flushLoop() {
	defer b.wg.Done()
	t := time.NewTicker(b.FlushInterval)
	defer t.Stop()
	for {
		select {
		case <-b.done:
			return
		case <-t.C:
			b.mu.Lock()
			for _, jf := range b.files {
				_ = jf.w.Flush()
			}
			b.mu.Unlock()
		}
	}
}

// Write appends a trajectory step to the rollout's JSONL file.
func (b *LocalJSONL) Write(ctx context.Context, rolloutID string, step *trajectory.Step) error {
	line, err := json.Marshal(step)
	if err != nil {
		return fmt.Errorf("local backend: marshal step: %w", err)
	}

	b.mu.Lock()
	defer b.mu.Unlock()
	if b.closed {
		return fmt.Errorf("local backend: closed")
	}

	jf, ok := b.files[rolloutID]
	if !ok {
		fpath := filepath.Join(b.Dir, rolloutID+".jsonl")
		f, err := os.OpenFile(fpath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			return fmt.Errorf("local backend: open file: %w", err)
		}
		jf = &jsonlFile{f: f, w: bufio.NewWriterSize(f, b.FlushBytes)}
		b.files[rolloutID] = jf
	}

	if _, err := jf.w.Write(line); err != nil {
		return fmt.Errorf("local backend: write: %w", err)
	}
	if err := jf.w.WriteByte('\n'); err != nil {
		return fmt.Errorf("local backend: write newline: %w", err)
	}
	return nil
}

// Flush writes buffered data for a rollout to disk without closing the file.
// It is called by the server when a rollout is paused mid-generation.
func (b *LocalJSONL) Flush(ctx context.Context, rolloutID string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	if jf, ok := b.files[rolloutID]; ok {
		if err := jf.w.Flush(); err != nil {
			return fmt.Errorf("local backend: flush: %w", err)
		}
	}
	return nil
}

// Finalize flushes and closes the rollout's file. It is called by the server
// when a rollout's trajectory is complete.
func (b *LocalJSONL) Finalize(ctx context.Context, rolloutID string) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	jf, ok := b.files[rolloutID]
	if !ok {
		return nil
	}
	delete(b.files, rolloutID)
	flushErr := jf.w.Flush()
	closeErr := jf.f.Close()
	if flushErr != nil {
		return fmt.Errorf("local backend: flush: %w", flushErr)
	}
	if closeErr != nil {
		return fmt.Errorf("local backend: close: %w", closeErr)
	}
	return nil
}

// Read streams the trajectory for a rollout to the given writer.
func (b *LocalJSONL) Read(ctx context.Context, rolloutID string, w io.Writer) error {
	// Flush any buffered data so the read observes all completed writes.
	b.mu.Lock()
	if jf, ok := b.files[rolloutID]; ok {
		if err := jf.w.Flush(); err != nil {
			b.mu.Unlock()
			return fmt.Errorf("local backend: flush before read: %w", err)
		}
	}
	b.mu.Unlock()

	fpath := filepath.Join(b.Dir, rolloutID+".jsonl")
	f, err := os.Open(fpath)
	if err != nil {
		return fmt.Errorf("local backend: open file: %w", err)
	}
	defer func() { _ = f.Close() }()

	_, err = io.Copy(w, f)
	return err
}

// Close flushes and closes all open files and stops the background flusher.
func (b *LocalJSONL) Close(ctx context.Context) error {
	b.mu.Lock()
	if b.closed {
		b.mu.Unlock()
		return nil
	}
	b.closed = true
	close(b.done)
	var firstErr error
	for id, jf := range b.files {
		if err := jf.w.Flush(); err != nil && firstErr == nil {
			firstErr = err
		}
		if err := jf.f.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
		delete(b.files, id)
	}
	b.mu.Unlock()
	b.wg.Wait()
	return firstErr
}
