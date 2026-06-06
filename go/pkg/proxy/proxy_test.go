package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/albert-lv/agent-arena/go/pkg/trajectory"
	"go.uber.org/zap"
)

// mockWriter collects trajectory steps for inspection.
type mockWriter struct {
	steps []*trajectory.Step
}

func (m *mockWriter) Write(ctx context.Context, step *trajectory.Step) error {
	m.steps = append(m.steps, step)
	return nil
}

func (m *mockWriter) Close(ctx context.Context) error { return nil }

// mockLLMBackend simulates an OpenAI-compatible LLM server.
type mockLLMBackend struct {
	server *httptest.Server
	// Handler can be overridden per-test.
	handler http.HandlerFunc
}

func newMockLLMBackend() *mockLLMBackend {
	m := &mockLLMBackend{}
	m.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if m.handler != nil {
			m.handler(w, r)
			return
		}
		// Default non-streaming response.
		resp := map[string]any{
			"id":      "chatcmpl-test",
			"object":  "chat.completion",
			"choices": []any{map[string]any{"message": map[string]any{"role": "assistant", "content": "hello"}}},
			"usage":   map[string]any{"prompt_tokens": 10, "completion_tokens": 5},
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
	return m
}

func (m *mockLLMBackend) URL() string { return m.server.URL }
func (m *mockLLMBackend) Close()      { m.server.Close() }

func TestProxyAuth(t *testing.T) {
	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy("http://localhost:9999", mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(`{}`))
	rec := httptest.NewRecorder()
	proxy.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}

	// Register rollout and retry.
	proxy.RegisterRollout("r1", "tok1", nil, "")
	req2 := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(`{}`))
	req2.Header.Set("Authorization", "Bearer tok1")
	rec2 := httptest.NewRecorder()
	proxy.ServeHTTP(rec2, req2)
	// Should not be 401 anymore (will be 502 since backend is down, which is fine).
	if rec2.Code == http.StatusUnauthorized {
		t.Fatal("expected non-401 after registration")
	}
}

func TestProxyNonStreaming(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	proxy.RegisterRollout("r1", "tok1", &trajectory.SamplingConfig{
		Temperature:     0.5,
		TopP:            0.9,
		Seed:            42,
		MaxTokensBudget: 100,
	}, "")

	body := `{"model":"gpt-4","messages":[{"role":"user","content":"hi"}]}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer tok1")
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	proxy.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	// Verify backend received sampling injection.
	var received map[string]any
	be.handler = func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &received)
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}
	req2 := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	req2.Header.Set("Authorization", "Bearer tok1")
	req2.Header.Set("Content-Type", "application/json")
	rec2 := httptest.NewRecorder()
	proxy.ServeHTTP(rec2, req2)

	if received == nil {
		t.Fatal("backend did not receive request")
	}
	if received["temperature"] != 0.5 {
		t.Fatalf("expected temperature 0.5, got %v", received["temperature"])
	}
	if received["top_p"] != 0.9 {
		t.Fatalf("expected top_p 0.9, got %v", received["top_p"])
	}
	if received["seed"] != float64(42) {
		t.Fatalf("expected seed 42, got %v", received["seed"])
	}

	// Verify trajectory was recorded.
	if len(mw.steps) != 2 {
		t.Fatalf("expected 2 trajectory steps, got %d", len(mw.steps))
	}
	step := mw.steps[0]
	if step.RolloutID != "r1" {
		t.Fatalf("expected rollout r1, got %s", step.RolloutID)
	}
	if step.Response == nil || step.Response.Usage == nil {
		t.Fatal("expected usage in trajectory")
	}
	if step.Response.Usage.PromptTokens != 10 {
		t.Fatalf("expected 10 prompt tokens, got %d", step.Response.Usage.PromptTokens)
	}
}

func TestProxyTokenBudget(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	proxy.RegisterRollout("r1", "tok1", &trajectory.SamplingConfig{
		MaxTokensBudget: 12,
	}, "")

	body := `{"model":"gpt-4","messages":[]}`
	// First request uses 10+5 = 15 tokens (exceeds budget of 12).
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer tok1")
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	proxy.ServeHTTP(rec, req)

	// It should still succeed because budget is checked *before* forwarding,
	// and the first request starts at 0 usage.
	if rec.Code != http.StatusOK {
		t.Fatalf("first request expected 200, got %d", rec.Code)
	}

	// Second request should be blocked because 15 >= 12.
	req2 := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	req2.Header.Set("Authorization", "Bearer tok1")
	req2.Header.Set("Content-Type", "application/json")
	rec2 := httptest.NewRecorder()
	proxy.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d", rec2.Code)
	}
}

func TestProxyStreaming(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	// Override backend to return SSE stream.
	be.handler = func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		flusher := w.(http.Flusher)

		chunks := []string{
			`data: {"choices":[{"delta":{"content":"Hello"}}],"usage":null}` + "\n\n",
			`data: {"choices":[{"delta":{"content":" world"}}],"usage":null}` + "\n\n",
			`data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}}` + "\n\n",
			"data: [DONE]\n\n",
		}
		for _, c := range chunks {
			io.WriteString(w, c)
			flusher.Flush()
		}
	}

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	proxy.RegisterRollout("r1", "tok1", nil, "")

	body := `{"model":"gpt-4","messages":[],"stream":true}`
	req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer tok1")
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	proxy.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	// Verify the streamed body contains our chunks.
	respBody := rec.Body.String()
	if !strings.Contains(respBody, "Hello") {
		t.Fatal("stream missing 'Hello'")
	}
	if !strings.Contains(respBody, " world") {
		t.Fatal("stream missing ' world'")
	}
	if !strings.Contains(respBody, "[DONE]") {
		t.Fatal("stream missing [DONE]")
	}

	// Verify trajectory captured the synthetic response.
	if len(mw.steps) != 1 {
		t.Fatalf("expected 1 trajectory step, got %d", len(mw.steps))
	}
	step := mw.steps[0]
	if step.Response == nil || step.Response.Usage == nil {
		t.Fatal("expected usage in trajectory")
	}
	if step.Response.Usage.PromptTokens != 3 {
		t.Fatalf("expected 3 prompt tokens, got %d", step.Response.Usage.PromptTokens)
	}
	if step.Response.Usage.CompletionTokens != 2 {
		t.Fatalf("expected 2 completion tokens, got %d", step.Response.Usage.CompletionTokens)
	}
}

func TestProxyPlainForwarding(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	// Track whether backend received a non-chat request.
	var receivedPath string
	be.handler = func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, `{"models":[]}`)
	}

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	proxy.RegisterRollout("r1", "tok1", nil, "")

	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	req.Header.Set("Authorization", "Bearer tok1")
	rec := httptest.NewRecorder()
	proxy.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if receivedPath != "/v1/models" {
		t.Fatalf("expected /v1/models, got %s", receivedPath)
	}
	// Plain forwarding should not record trajectory.
	if len(mw.steps) != 0 {
		t.Fatalf("expected 0 trajectory steps for plain forwarding, got %d", len(mw.steps))
	}
}

func TestInjectSampling(t *testing.T) {
	sampling := &trajectory.SamplingConfig{
		Temperature: 0.3,
		TopP:        0.8,
		Seed:        123,
	}
	body := []byte(`{"model":"gpt-4","messages":[]}`)
	out, err := injectSampling(body, sampling)
	if err != nil {
		t.Fatalf("inject sampling: %v", err)
	}
	var req map[string]any
	if err := json.Unmarshal(out, &req); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if req["temperature"] != 0.3 {
		t.Fatalf("temperature: %v", req["temperature"])
	}
	if req["top_p"] != 0.8 {
		t.Fatalf("top_p: %v", req["top_p"])
	}
	if req["seed"] != float64(123) {
		t.Fatalf("seed: %v", req["seed"])
	}
}

func TestProxyServerStart(t *testing.T) {
	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy("http://localhost:9999", mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	ps, err := NewProxyServer(proxy, logger)
	if err != nil {
		t.Fatalf("new proxy server: %v", err)
	}
	addr, err := ps.Start()
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if addr == "" {
		t.Fatal("expected non-empty address")
	}
	defer ps.Close()

	// Ensure the server is reachable.
	proxy.RegisterRollout("r1", "tok1", nil, "")
	url := "http://" + addr + "/v1/models"
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("Authorization", "Bearer tok1")
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadGateway {
		// Backend is down so we expect 502; the important thing is the server is up.
		t.Fatalf("expected 502 (backend down), got %d", resp.StatusCode)
	}
}

func TestBudgetNotEnforcedWhenZero(t *testing.T) {
	be := newMockLLMBackend()
	defer be.Close()

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		t.Fatalf("new proxy: %v", err)
	}
	// BudgetLimit = 0 means unlimited.
	proxy.RegisterRollout("r1", "tok1", &trajectory.SamplingConfig{
		MaxTokensBudget: 0,
	}, "")

	body := `{"model":"gpt-4","messages":[]}`
	for i := 0; i < 5; i++ {
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer tok1")
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		proxy.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d: expected 200, got %d", i, rec.Code)
		}
	}
}

func BenchmarkProxyNonStreaming(b *testing.B) {
	be := newMockLLMBackend()
	defer be.Close()

	mw := &mockWriter{}
	logger := zap.NewNop()
	proxy, err := NewProxy(be.URL(), mw, logger)
	if err != nil {
		b.Fatalf("new proxy: %v", err)
	}
	proxy.RegisterRollout("r1", "tok1", nil, "")

	body := []byte(`{"model":"gpt-4","messages":[{"role":"user","content":"hi"}]}`)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		req := httptest.NewRequest(http.MethodPost, "/v1/chat/completions", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer tok1")
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		proxy.ServeHTTP(rec, req)
	}
}
