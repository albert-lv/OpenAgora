// Package inference relays trainer-side weight updates to the shared LLM
// inference backend that serves rollout generation, so the trainer needs no
// backend-specific knowledge.
package inference

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// WeightSyncer refits the inference backend with new weights.
type WeightSyncer interface {
	// PauseGeneration stops the backend from starting new generation work.
	// The mode is backend-specific; pass "" for the implementation default.
	PauseGeneration(ctx context.Context, mode string) error
	// UpdateWeightsFromDisk reloads weights from a trainer-side checkpoint
	// directory on a shared filesystem.
	UpdateWeightsFromDisk(ctx context.Context, modelPath, version string, abortInFlight bool) error
	// ContinueGeneration resumes generation after a refit.
	ContinueGeneration(ctx context.Context) error
}

// NewWeightSyncer builds a WeightSyncer for the given backend type
// ("sglang" or "vllm"). An empty backend type returns nil, nil.
func NewWeightSyncer(backendType, backendURL string) (WeightSyncer, error) {
	if backendType == "" {
		return nil, nil
	}
	if backendURL == "" {
		return nil, fmt.Errorf("backend URL is required for backend type %q", backendType)
	}
	// Weight updates load full checkpoints and can take minutes.
	client := &http.Client{Timeout: 10 * time.Minute}
	base := strings.TrimSuffix(backendURL, "/")
	switch strings.ToLower(backendType) {
	case "sglang":
		return &sglangSyncer{base: base, client: client}, nil
	case "vllm":
		return &vllmSyncer{base: base, client: client}, nil
	default:
		return nil, fmt.Errorf("unsupported backend type %q (supported: sglang, vllm)", backendType)
	}
}

// postJSON POSTs a JSON payload to base+path and decodes the response body
// into out when out is non-nil.
func postJSON(ctx context.Context, client *http.Client, base, path string, payload map[string]any, out any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal %s payload: %w", path, err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+path, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build %s request: %w", path, err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("%s: read response: %w", path, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s: backend returned %s: %s", path, resp.Status, strings.TrimSpace(string(respBody)))
	}
	if out != nil && len(respBody) > 0 {
		if err := json.Unmarshal(respBody, out); err != nil {
			return fmt.Errorf("%s: decode response: %w", path, err)
		}
	}
	return nil
}

// sglangSyncer implements WeightSyncer against SGLang's RL HTTP APIs
// (pause_generation / update_weights_from_disk / continue_generation).
type sglangSyncer struct {
	base   string
	client *http.Client
}

func (s *sglangSyncer) PauseGeneration(ctx context.Context, mode string) error {
	if mode == "" {
		mode = "retract"
	}
	return postJSON(ctx, s.client, s.base, "/pause_generation", map[string]any{"mode": mode}, nil)
}

func (s *sglangSyncer) UpdateWeightsFromDisk(ctx context.Context, modelPath, version string, abortInFlight bool) error {
	payload := map[string]any{
		"model_path":         modelPath,
		"weight_version":     version,
		"abort_all_requests": abortInFlight,
		"flush_cache":        true,
	}
	var resp struct {
		Success bool   `json:"success"`
		Message string `json:"message"`
	}
	if err := postJSON(ctx, s.client, s.base, "/update_weights_from_disk", payload, &resp); err != nil {
		return err
	}
	if !resp.Success {
		return fmt.Errorf("update_weights_from_disk failed: %s", resp.Message)
	}
	return nil
}

func (s *sglangSyncer) ContinueGeneration(ctx context.Context) error {
	return postJSON(ctx, s.client, s.base, "/continue_generation", map[string]any{}, nil)
}

// vLLMSyncer implements WeightSyncer against vLLM's RL HTTP APIs
// (pause / resume). vLLM has no stable disk-reload HTTP endpoint, so
// UpdateWeightsFromDisk reports the operation as unsupported.
type vllmSyncer struct {
	base   string
	client *http.Client
}

func (v *vllmSyncer) PauseGeneration(ctx context.Context, mode string) error {
	if mode == "" {
		mode = "keep"
	}
	return postJSON(ctx, v.client, v.base, "/pause", map[string]any{"mode": mode}, nil)
}

func (v *vllmSyncer) UpdateWeightsFromDisk(ctx context.Context, modelPath, version string, abortInFlight bool) error {
	return fmt.Errorf("unsupported by backend: vLLM has no stable disk-reload HTTP endpoint")
}

func (v *vllmSyncer) ContinueGeneration(ctx context.Context) error {
	return postJSON(ctx, v.client, v.base, "/resume", map[string]any{}, nil)
}
