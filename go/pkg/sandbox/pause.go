package sandbox

import "context"

// Pauser is an optional interface for providers that can freeze a running
// sandbox in place, preserving all in-sandbox state, and later resume it.
// It enables partial rollout: a paused rollout keeps its state and, after
// resume, its LLM calls are served by whatever weights the backend serves
// at that time. Providers that cannot freeze sandboxes simply do not
// implement it; the server then rejects PauseRollout as unimplemented.
type Pauser interface {
	Pause(ctx context.Context, id string) error
	Unpause(ctx context.Context, id string) error
}
