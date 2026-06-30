package trajectory

import (
	"context"
)

// Writer is the interface for append-only trajectory storage.
type Writer interface {
	Write(ctx context.Context, step *Step) error
	Close(ctx context.Context) error
}

// NopWriter is a no-op writer for testing.
type NopWriter struct{}

func (NopWriter) Write(ctx context.Context, step *Step) error { return nil }
func (NopWriter) Close(ctx context.Context) error              { return nil }

// TODO: implement local JSONL writer, Parquet writer, remote backend writer
