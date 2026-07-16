package proxy

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
	"go.uber.org/zap"
)

// RolloutState holds per-rollout mutable state protected by Proxy.mu.
type RolloutState struct {
	RolloutID   string
	TraceID     string
	Token       string
	Sampling    *trajectory.SamplingConfig
	Usage       trajectory.Usage
	BudgetLimit int      // 0 = unlimited
	BackendURL  *url.URL // per-rollout backend override; nil uses proxy default
}

// Proxy is the core Arena component that transparently intercepts
// all communication between an agent and the LLM backend.
type Proxy struct {
	backend *url.URL
	logger  *zap.Logger
	writer  trajectory.Writer
	client  *http.Client
	metrics MetricsRecorder

	mu       sync.RWMutex
	rollouts map[string]*RolloutState // key = rollout token
}

// MetricsRecorder is the subset of the server metrics surface used by Proxy.
type MetricsRecorder interface {
	Inc(name string, value uint64, labelValues ...string)
	Observe(name string, value float64, labelValues ...string)
}

// SetMetrics attaches a metrics recorder to the proxy.
func (p *Proxy) SetMetrics(m MetricsRecorder) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.metrics = m
}

// NewProxy creates a new LLM proxy instance.
// backendURL may be empty; in that case every rollout must provide its own BackendURL.
func NewProxy(backendURL string, writer trajectory.Writer, logger *zap.Logger) (*Proxy, error) {
	var u *url.URL
	if backendURL != "" {
		var err error
		u, err = url.Parse(backendURL)
		if err != nil {
			return nil, err
		}
	}
	return &Proxy{
		backend:  u,
		logger:   logger,
		writer:   writer,
		client:   &http.Client{Timeout: 120 * time.Second},
		rollouts: make(map[string]*RolloutState),
	}, nil
}

// RegisterRollout registers a new rollout so that subsequent requests
// bearing its token are recognised and attributed.
func (p *Proxy) RegisterRollout(rolloutID, traceID, token string, sampling *trajectory.SamplingConfig, backendURL string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	budget := 0
	if sampling != nil {
		budget = sampling.MaxTokensBudget
	}
	var bu *url.URL
	if backendURL != "" {
		bu, _ = url.Parse(backendURL)
	}
	p.rollouts[token] = &RolloutState{
		RolloutID:   rolloutID,
		TraceID:     traceID,
		Token:       token,
		Sampling:    sampling,
		BudgetLimit: budget,
		BackendURL:  bu,
	}
	p.logger.Info("rollout registered",
		zap.String("rollout_id", rolloutID),
		zap.String("trace_id", traceID),
		zap.Int("budget", budget))
}

// UnregisterRollout removes a rollout from the proxy.
func (p *Proxy) UnregisterRollout(token string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	delete(p.rollouts, token)
}

// getRollout returns the rollout state for the given token.
func (p *Proxy) getRollout(token string) (*RolloutState, bool) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	rs, ok := p.rollouts[token]
	return rs, ok
}

// addUsage atomically adds token usage to a rollout.
func (p *Proxy) addUsage(token string, prompt, completion int) (totalPrompt, totalCompletion int, over bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	rs, ok := p.rollouts[token]
	if !ok {
		return 0, 0, false
	}
	rs.Usage.PromptTokens += prompt
	rs.Usage.CompletionTokens += completion
	if rs.BudgetLimit > 0 && (rs.Usage.PromptTokens+rs.Usage.CompletionTokens) > rs.BudgetLimit {
		return rs.Usage.PromptTokens, rs.Usage.CompletionTokens, true
	}
	return rs.Usage.PromptTokens, rs.Usage.CompletionTokens, false
}

// ServeHTTP implements an OpenAI-compatible endpoint.
// The agent points OPENAI_BASE_URL to this proxy.
func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	token := extractBearerToken(r)
	if token == "" {
		http.Error(w, `{"error":"missing authorization"}`, http.StatusUnauthorized)
		return
	}

	rs, ok := p.getRollout(token)
	if !ok {
		http.Error(w, `{"error":"invalid rollout token"}`, http.StatusUnauthorized)
		return
	}

	p.logger.Debug("proxy request",
		zap.String("rollout_id", rs.RolloutID),
		zap.String("path", r.URL.Path),
		zap.String("method", r.Method))

	// Only intercept chat completions; everything else is proxied verbatim.
	if r.URL.Path == "/v1/chat/completions" {
		p.handleChatCompletions(w, r, rs)
		return
	}

	p.proxyPlain(w, r)
}

// handleChatCompletions intercepts chat completion requests for sampling injection,
// budget enforcement and trajectory capture.
func (p *Proxy) handleChatCompletions(w http.ResponseWriter, r *http.Request, rs *RolloutState) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, `{"error":"read body"}`, http.StatusBadRequest)
		return
	}
	_ = r.Body.Close()

	// 1. Inject sampling parameters.
	body, err = injectSampling(body, rs.Sampling, rs.BackendURL)
	if err != nil {
		p.logger.Warn("failed to inject sampling", zap.Error(err))
		// Continue with original body on injection failure.
	}
	p.logger.Info("proxy forwarded request", zap.String("rollout_id", rs.RolloutID), zap.ByteString("body", body))

	// 2. Check token budget before forwarding.
	if rs.BudgetLimit > 0 {
		p.mu.RLock()
		used := rs.Usage.PromptTokens + rs.Usage.CompletionTokens
		p.mu.RUnlock()
		if used >= rs.BudgetLimit {
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = io.WriteString(w, fmt.Sprintf(`{"error":"token budget exhausted: %d/%d"}`, used, rs.BudgetLimit))
			return
		}
	}

	// Determine if stream was requested.
	var reqMap map[string]any
	isStream := false
	if json.Unmarshal(body, &reqMap) == nil {
		if v, ok := reqMap["stream"].(bool); ok && v {
			isStream = true
		}
	}

	// 3. Forward to backend.
	backend := rs.BackendURL
	if backend == nil {
		backend = p.backend
	}
	if backend == nil {
		http.Error(w, `{"error":"no backend configured"}`, http.StatusInternalServerError)
		return
	}
	backendReq, err := p.newBackendRequest(r, body, backend)
	if err != nil {
		http.Error(w, `{"error":"create backend request"}`, http.StatusInternalServerError)
		return
	}

	proxyStart := time.Now()
	backendResp, err := p.client.Do(backendReq)
	if err != nil {
		p.logger.Error("backend error", zap.Error(err))
		if p.metrics != nil {
			p.metrics.Inc("arena_proxy_backend_errors_total", 1)
		}
		http.Error(w, `{"error":"backend unreachable"}`, http.StatusBadGateway)
		return
	}
	if p.metrics != nil {
		p.metrics.Inc("arena_proxy_requests_total", 1, r.URL.Path)
		p.metrics.Observe("arena_proxy_request_duration_seconds", time.Since(proxyStart).Seconds(), r.URL.Path)
	}
	defer func() { _ = backendResp.Body.Close() }()
	p.logger.Info("proxy backend response", zap.String("rollout_id", rs.RolloutID), zap.Int("status", backendResp.StatusCode))

	// Copy headers except those managed by Go's HTTP server.
	for k, vv := range backendResp.Header {
		for _, v := range vv {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(backendResp.StatusCode)

	if isStream {
		p.streamResponse(w, backendResp.Body, rs, body)
	} else {
		p.nonStreamResponse(w, backendResp.Body, rs, body)
	}
}

// nonStreamResponse copies the response body and captures trajectory.
func (p *Proxy) nonStreamResponse(w http.ResponseWriter, respBody io.Reader, rs *RolloutState, reqBody []byte) {
	respBytes, err := io.ReadAll(respBody)
	if err != nil {
		p.logger.Error("read backend response", zap.Error(err))
		return
	}

	_, _ = w.Write(respBytes)

	// Extract usage and logprobs.
	var respMap map[string]any
	promptTokens, completionTokens := 0, 0
	var logprobsBytes []byte
	if json.Unmarshal(respBytes, &respMap) == nil {
		if usage, ok := respMap["usage"].(map[string]any); ok {
			if v, ok := usage["prompt_tokens"].(float64); ok {
				promptTokens = int(v)
			}
			if v, ok := usage["completion_tokens"].(float64); ok {
				completionTokens = int(v)
			}
		}
		// Capture logprobs if present.
		if lp, ok := respMap["choices"].([]any); ok && len(lp) > 0 {
			if choice, ok := lp[0].(map[string]any); ok {
				if logprobs, ok := choice["logprobs"]; ok && logprobs != nil {
					logprobsBytes, _ = json.Marshal(logprobs)
				}
			}
		}
	}

	if p.metrics != nil {
		p.metrics.Inc("arena_tokens_total", uint64(promptTokens), "prompt")
		p.metrics.Inc("arena_tokens_total", uint64(completionTokens), "completion")
	}

	p.recordStep(rs, reqBody, respBytes, promptTokens, completionTokens, logprobsBytes)

	if rs.BudgetLimit > 0 {
		_, _, over := p.addUsage(rs.Token, promptTokens, completionTokens)
		if over {
			p.logger.Warn("token budget exhausted after response",
				zap.String("rollout_id", rs.RolloutID))
		}
	}
}

// streamResponse copies SSE chunks while accumulating usage and capturing trajectory.
func (p *Proxy) streamResponse(w http.ResponseWriter, respBody io.Reader, rs *RolloutState, reqBody []byte) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		p.logger.Error("streaming not supported by ResponseWriter")
		_, _ = io.Copy(w, respBody)
		return
	}

	scanner := bufio.NewScanner(respBody)
	var fullContent strings.Builder
	promptTokens, completionTokens := 0, 0
	var lastChunk []byte

	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			// Write non-data lines (e.g., empty lines) as-is.
			_, _ = fmt.Fprintln(w, line)
			flusher.Flush()
			continue
		}

		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			_, _ = fmt.Fprintln(w, line)
			flusher.Flush()
			continue
		}

		_, _ = fmt.Fprintln(w, line)
		flusher.Flush()

		var chunk map[string]any
		if json.Unmarshal([]byte(data), &chunk) != nil {
			continue
		}

		lastChunk = []byte(data)

		// Accumulate delta content.
		if choices, ok := chunk["choices"].([]any); ok && len(choices) > 0 {
			if choice, ok := choices[0].(map[string]any); ok {
				if delta, ok := choice["delta"].(map[string]any); ok {
					if content, ok := delta["content"].(string); ok {
						fullContent.WriteString(content)
					}
				}
			}
		}

		// Usage may appear in the last chunk (OpenAI-style).
		if usage, ok := chunk["usage"].(map[string]any); ok {
			if v, ok := usage["prompt_tokens"].(float64); ok {
				promptTokens = int(v)
			}
			if v, ok := usage["completion_tokens"].(float64); ok {
				completionTokens = int(v)
			}
		}
	}

	if err := scanner.Err(); err != nil {
		p.logger.Error("stream scan error", zap.Error(err))
	}

	// Build a synthetic response for trajectory capture.
	syntheticResp := map[string]any{
		"choices": []any{
			map[string]any{
				"message": map[string]any{
					"role":    "assistant",
					"content": fullContent.String(),
				},
				"finish_reason": "stop",
			},
		},
		"usage": map[string]any{
			"prompt_tokens":     promptTokens,
			"completion_tokens": completionTokens,
		},
	}
	if promptTokens == 0 && completionTokens == 0 && len(lastChunk) > 0 {
		// Try to extract usage from the last chunk one more time.
		var chunk map[string]any
		if json.Unmarshal(lastChunk, &chunk) == nil {
			if usage, ok := chunk["usage"].(map[string]any); ok {
				if v, ok := usage["prompt_tokens"].(float64); ok {
					promptTokens = int(v)
				}
				if v, ok := usage["completion_tokens"].(float64); ok {
					completionTokens = int(v)
				}
			}
		}
		syntheticResp["usage"] = map[string]any{
			"prompt_tokens":     promptTokens,
			"completion_tokens": completionTokens,
		}
	}

	if p.metrics != nil {
		p.metrics.Inc("arena_tokens_total", uint64(promptTokens), "prompt")
		p.metrics.Inc("arena_tokens_total", uint64(completionTokens), "completion")
	}

	syntheticBytes, _ := json.Marshal(syntheticResp)
	// Streaming responses typically don't carry per-token logprobs.
	p.recordStep(rs, reqBody, syntheticBytes, promptTokens, completionTokens, nil)

	if rs.BudgetLimit > 0 {
		_, _, over := p.addUsage(rs.Token, promptTokens, completionTokens)
		if over {
			p.logger.Warn("token budget exhausted after stream",
				zap.String("rollout_id", rs.RolloutID))
		}
	}
}

// proxyPlain forwards the request to the backend without any interception.
func (p *Proxy) proxyPlain(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, `{"error":"read body"}`, http.StatusBadRequest)
		return
	}
	_ = r.Body.Close()

	backendReq, err := p.newBackendRequest(r, body, p.backend)
	if err != nil {
		http.Error(w, `{"error":"create backend request"}`, http.StatusInternalServerError)
		return
	}

	backendResp, err := p.client.Do(backendReq)
	if err != nil {
		http.Error(w, `{"error":"backend unreachable"}`, http.StatusBadGateway)
		return
	}
	defer func() { _ = backendResp.Body.Close() }()

	for k, vv := range backendResp.Header {
		for _, v := range vv {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(backendResp.StatusCode)
	_, _ = io.Copy(w, backendResp.Body)
}

// newBackendRequest builds an HTTP request targeting the LLM backend.
func (p *Proxy) newBackendRequest(r *http.Request, body []byte, backend *url.URL) (*http.Request, error) {
	backendURL := backend.ResolveReference(r.URL)
	req, err := http.NewRequestWithContext(r.Context(), r.Method, backendURL.String(), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	for k, vv := range r.Header {
		if strings.EqualFold(k, "Authorization") {
			// Strip the Arena token; backend may use its own auth.
			continue
		}
		for _, v := range vv {
			req.Header.Add(k, v)
		}
	}
	return req, nil
}

// injectSampling rewrites the request JSON to enforce per-rollout sampling params.
func injectSampling(body []byte, sampling *trajectory.SamplingConfig, backendURL *url.URL) ([]byte, error) {
	if sampling == nil {
		return body, nil
	}
	var req map[string]any
	if err := json.Unmarshal(body, &req); err != nil {
		return body, err
	}
	if sampling.Temperature != 0 {
		req["temperature"] = sampling.Temperature
	}
	if sampling.TopP != 0 {
		req["top_p"] = sampling.TopP
	}
	if sampling.Seed != 0 {
		req["seed"] = sampling.Seed
	}
	if sampling.MaxTokensBudget > 0 {
		// Cap max_tokens to remaining budget if present; otherwise leave as-is.
		if _, hasMaxTokens := req["max_tokens"]; hasMaxTokens {
			// We'll enforce budget at proxy level rather than rewriting max_tokens
			// to avoid interfering with agent's intent.
			_ = hasMaxTokens
		}
	}
	// Request logprobs from backend to support RL training.
	// Note: ollama supports logprobs but not top_logprobs.
	req["logprobs"] = true
	// vLLM / SGLang support top_logprobs; ollama does not. Only inject when we
	// can reasonably infer a non-ollama backend and the client did not set it.
	if _, hasTop := req["top_logprobs"]; !hasTop && backendSupportsTopLogprobs(backendURL) {
		req["top_logprobs"] = 20
	}
	return json.Marshal(req)
}

// backendSupportsTopLogprobs heuristically decides whether the backend is
// likely to support OpenAI-style top_logprobs. ollama is explicitly excluded.
func backendSupportsTopLogprobs(u *url.URL) bool {
	if u == nil {
		return false
	}
	host := strings.ToLower(u.Host)
	if strings.Contains(host, "ollama") {
		return false
	}
	// ollama default port.
	if strings.HasSuffix(host, ":11434") {
		return false
	}
	return true
}

// extractBearerToken parses the Authorization header.
func extractBearerToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if strings.HasPrefix(auth, prefix) {
		return strings.TrimSpace(auth[len(prefix):])
	}
	return ""
}

// recordStep writes a trajectory step for the captured interaction.
func (p *Proxy) recordStep(rs *RolloutState, reqBody, respBody []byte, promptTokens, completionTokens int, logprobs []byte) {
	step := &trajectory.Step{
		RolloutID: rs.RolloutID,
		StepID:    0, // Will be assigned by writer or server.
		Timestamp: time.Now(),
		Request: &trajectory.LLMRequest{
			Endpoint: "/v1/chat/completions",
			Messages: reqBody,
			Sampling: rs.Sampling,
		},
		Response: &trajectory.LLMResponse{
			Choices: respBody,
			Usage: &trajectory.Usage{
				PromptTokens:     promptTokens,
				CompletionTokens: completionTokens,
			},
			Logprobs: logprobs,
		},
		Metadata: map[string]string{
			"trace_id": rs.TraceID,
		},
	}
	if err := p.writer.Write(context.TODO(), step); err != nil {
		p.logger.Error("failed to write trajectory", zap.Error(err))
	}
}

// StepCounter generates monotonic step IDs per rollout.
type StepCounter struct {
	mu     sync.Mutex
	counts map[string]int
}

// NewStepCounter creates a new step counter.
func NewStepCounter() *StepCounter {
	return &StepCounter{counts: make(map[string]int)}
}

// Next returns the next step ID for the given rollout.
func (c *StepCounter) Next(rolloutID string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.counts[rolloutID]++
	return c.counts[rolloutID]
}

// ProxyServer wraps Proxy as an http.Server with a dedicated listener.
type ProxyServer struct {
	*http.Server
	ListenerAddr string
	listenHost   string
}

// NewProxyServer creates an HTTP server that exposes the proxy on a random port.
func NewProxyServer(proxy *Proxy, logger *zap.Logger) (*ProxyServer, error) {
	return NewProxyServerWithHost(proxy, logger, "")
}

// NewProxyServerWithHost creates an HTTP server bound to the given host with a random port.
func NewProxyServerWithHost(proxy *Proxy, logger *zap.Logger, host string) (*ProxyServer, error) {
	mux := http.NewServeMux()
	mux.Handle("/", proxy)

	return &ProxyServer{
		Server: &http.Server{
			Handler: mux,
		},
		listenHost: host,
	}, nil
}

// Start begins serving on a random port and returns the address.
func (ps *ProxyServer) Start() (string, error) {
	addr := ":0"
	if ps.listenHost != "" {
		addr = net.JoinHostPort(ps.listenHost, "0")
	}
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		return "", err
	}
	ps.ListenerAddr = lis.Addr().String()
	go func() {
		_ = ps.Serve(lis)
	}()
	return ps.ListenerAddr, nil
}
