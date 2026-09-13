package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
	"go.uber.org/zap"
)

// TestProxyCapturesEngineTokenIDs verifies that SGLang-shaped responses
// (meta_info with prompt/completion token IDs and weight_version) are
// captured into the trajectory step.
func TestProxyCapturesEngineTokenIDs(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()
	be.handler = func(w http.ResponseWriter, r *http.Request) {
		resp := map[string]any{
			"id":      "chatcmpl-test",
			"object":  "chat.completion",
			"choices": []any{map[string]any{"message": map[string]any{"role": "assistant", "content": "hi"}, "finish_reason": "stop"}},
			"usage":   map[string]any{"prompt_tokens": 3, "completion_tokens": 2},
			"meta_info": map[string]any{
				"prompt_token_ids":     []any{11, 12, 13},
				"completion_token_ids": []any{21, 22},
				"weight_version":       "step-7",
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}

	mw := &mockWriter{}
	p, err := NewProxy(be.URL(), mw, zap.NewNop())
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	p.RegisterRollout("r1", "t1", "tok1", nil, "")

	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(`{"model":"m","messages":[]}`))
	req.Header.Set("Authorization", "Bearer tok1")
	rec := httptest.NewRecorder()
	p.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if len(mw.steps) != 1 {
		t.Fatalf("expected 1 step, got %d", len(mw.steps))
	}
	resp := mw.steps[0].Response
	wantPrompt := []int32{11, 12, 13}
	if !equalInt32s(resp.PromptTokenIDs, wantPrompt) {
		t.Fatalf("prompt token IDs = %v, want %v", resp.PromptTokenIDs, wantPrompt)
	}
	wantCompletion := []int32{21, 22}
	if !equalInt32s(resp.CompletionTokenIDs, wantCompletion) {
		t.Fatalf("completion token IDs = %v, want %v", resp.CompletionTokenIDs, wantCompletion)
	}
	if resp.WeightVersion != "step-7" {
		t.Fatalf("weight version = %q, want step-7", resp.WeightVersion)
	}
}

// TestProxyNoTokenIDsWhenAbsent ensures capture is a no-op for backends that
// do not report token IDs.
func TestProxyNoTokenIDsWhenAbsent(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	mw := &mockWriter{}
	p, err := NewProxy(be.URL(), mw, zap.NewNop())
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	p.RegisterRollout("r1", "t1", "tok1", nil, "")

	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(`{"model":"m","messages":[]}`))
	req.Header.Set("Authorization", "Bearer tok1")
	rec := httptest.NewRecorder()
	p.ServeHTTP(rec, req)

	if len(mw.steps) != 1 {
		t.Fatalf("expected 1 step, got %d", len(mw.steps))
	}
	resp := mw.steps[0].Response
	if len(resp.PromptTokenIDs) != 0 || len(resp.CompletionTokenIDs) != 0 || resp.WeightVersion != "" {
		t.Fatalf("expected no token IDs, got %+v", resp)
	}
}

// TestExtractEngineTokenIDs covers the supported response shapes directly.
func TestExtractEngineTokenIDs(t *testing.T) {
	cases := []struct {
		name           string
		resp           map[string]any
		wantPrompt     []int32
		wantCompletion []int32
		wantVersion    string
	}{
		{
			name: "sglang top-level",
			resp: map[string]any{
				"prompt_token_ids":     []any{1, 2},
				"completion_token_ids": []any{3},
				"weight_version":       "v1",
			},
			wantPrompt:     []int32{1, 2},
			wantCompletion: []int32{3},
			wantVersion:    "v1",
		},
		{
			name: "sglang output_token_logprobs fallback",
			resp: map[string]any{
				"meta_info": map[string]any{
					"prompt_token_ids": []any{5, 6},
					"output_token_logprobs": []any{
						[]any{-0.1, 7, "a"},
						[]any{-0.2, 8, "b"},
					},
				},
			},
			wantPrompt:     []int32{5, 6},
			wantCompletion: []int32{7, 8},
		},
		{
			name: "choices token_ids",
			resp: map[string]any{
				"choices": []any{map[string]any{"token_ids": []any{9, 10}}},
			},
			wantCompletion: []int32{9, 10},
		},
		{
			name: "nothing present",
			resp: map[string]any{"choices": []any{map[string]any{}}},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p, c, v := extractEngineTokenIDs(tc.resp)
			if !equalInt32s(p, tc.wantPrompt) {
				t.Fatalf("prompt = %v, want %v", p, tc.wantPrompt)
			}
			if !equalInt32s(c, tc.wantCompletion) {
				t.Fatalf("completion = %v, want %v", c, tc.wantCompletion)
			}
			if v != tc.wantVersion {
				t.Fatalf("version = %q, want %q", v, tc.wantVersion)
			}
		})
	}
}

// TestInjectSamplingRequestsTokenIDs verifies the vLLM token-ID opt-in is
// injected only when the backend type is known to be vllm.
func TestInjectSamplingRequestsTokenIDs(t *testing.T) {
	body := []byte(`{"model":"m","messages":[]}`)
	u, _ := url.Parse("http://vllm:8000/v1")

	out, err := injectSampling(body, nil, u, "vllm")
	if err != nil {
		t.Fatalf("inject sampling: %v", err)
	}
	var req map[string]any
	if err := json.Unmarshal(out, &req); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if req["return_tokens_as_token_ids"] != true {
		t.Fatalf("expected return_tokens_as_token_ids for vllm, got %v", req["return_tokens_as_token_ids"])
	}

	out, err = injectSampling(body, nil, u, "")
	if err != nil {
		t.Fatalf("inject sampling: %v", err)
	}
	req = map[string]any{}
	if err := json.Unmarshal(out, &req); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := req["return_tokens_as_token_ids"]; ok {
		t.Fatal("return_tokens_as_token_ids must not be injected for unknown backend type")
	}
}

func equalInt32s(a, b []int32) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// Ensure trajectory.LLMResponse carries the captured fields (compile check).
var _ = trajectory.LLMResponse{PromptTokenIDs: []int32{1}, CompletionTokenIDs: []int32{2}, WeightVersion: "v"}
