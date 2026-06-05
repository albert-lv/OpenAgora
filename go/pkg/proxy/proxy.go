package proxy

import (
	"io"
	"net/http"
	"net/url"

	"go.uber.org/zap"
)

// Proxy is the core Arena component that transparently intercepts
// all communication between an agent and the LLM backend.
type Proxy struct {
	backend  *url.URL
	logger   *zap.Logger
	// capture  TrajectoryCapture
	// sampling SamplingOverride
	// budget   TokenBudget
	// router   BackendRouter
}

// NewProxy creates a new LLM proxy instance.
func NewProxy(backendURL string, logger *zap.Logger) (*Proxy, error) {
	u, err := url.Parse(backendURL)
	if err != nil {
		return nil, err
	}
	return &Proxy{
		backend: u,
		logger:  logger,
	}, nil
}

// ServeHTTP implements an OpenAI-compatible endpoint.
// The agent points OPENAI_BASE_URL to this proxy.
func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// 1. Validate ARENA_ROLLOUT_TOKEN
	// 2. Inject sampling parameters (temperature, top_p, seed)
	// 3. Check token budget
	// 4. Forward to actual LLM backend
	// 5. Capture req/resp -> trajectory writer
	// 6. Return response to agent

	p.logger.Info("proxy request", zap.String("path", r.URL.Path))

	// TODO: implement full proxy logic
	w.WriteHeader(http.StatusNotImplemented)
	io.WriteString(w, `{"error": "not yet implemented"}`)
}
