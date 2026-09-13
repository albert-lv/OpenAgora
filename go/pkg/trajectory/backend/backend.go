package backend

import (
	"context"
	"io"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
)

// Backend is the interface for trajectory storage backends.
type Backend interface {
	Write(ctx context.Context, rolloutID string, step *trajectory.Step) error
	Read(ctx context.Context, rolloutID string, w io.Writer) error
	Close(ctx context.Context) error
}

// NopBackend is a no-op backend for testing.
type NopBackend struct{}

func (NopBackend) Write(ctx context.Context, rolloutID string, step *trajectory.Step) error {
	return nil
}
func (NopBackend) Read(ctx context.Context, rolloutID string, w io.Writer) error { return nil }
func (NopBackend) Close(ctx context.Context) error                               { return nil }

// Finalizer is an optional interface for backends that buffer writes.
// The server calls Finalize when a rollout's trajectory is complete so that
// buffered data is durably written even before the periodic flush fires.
type Finalizer interface {
	Finalize(ctx context.Context, rolloutID string) error
}

// Flusher is an optional interface for backends that buffer writes.
// Unlike Finalize, Flush keeps the rollout's file open for further writes;
// the server uses it when a rollout is paused mid-generation.
type Flusher interface {
	Flush(ctx context.Context, rolloutID string) error
}
