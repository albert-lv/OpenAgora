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
