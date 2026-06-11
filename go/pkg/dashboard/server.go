package dashboard

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

// Server serves the Arena dashboard HTTP API and static files.
type Server struct {
	port  int
	store *MetricsStore
}

// NewServer creates a new dashboard server.
func NewServer(port int) *Server {
	return &Server{
		port:  port,
		store: NewMetricsStore(),
	}
}

// RegisterRoutes registers all dashboard routes on the provided mux.
func (s *Server) RegisterRoutes(mux *http.ServeMux) {
	// Static files (dashboard UI)
	mux.HandleFunc("/dashboard", s.handleIndex)
	mux.Handle("/dashboard/static/", http.StripPrefix("/dashboard/static/", http.FileServer(http.Dir("./static"))))

	// API endpoints
	mux.HandleFunc("/api/v1/metrics", s.handleMetrics)
	mux.HandleFunc("/api/v1/rollouts", s.handleRollouts)
	mux.HandleFunc("/api/v1/rollout/", s.handleRolloutDetail)
	mux.HandleFunc("/api/v1/tokens", s.handleTokens)
	mux.HandleFunc("/api/v1/trajectory/", s.handleTrajectory)
	mux.HandleFunc("/api/v1/tools", s.handleToolAnalysis)
	mux.HandleFunc("/api/v1/verify", s.handleVerifyAnalysis)
}

// Start starts the HTTP server.
func (s *Server) Start() error {
	mux := http.NewServeMux()
	s.RegisterRoutes(mux)
	addr := fmt.Sprintf(":%d", s.port)
	return http.ListenAndServe(addr, mux)
}

// handleIndex serves the main dashboard HTML page.
func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html")
	http.ServeFile(w, r, "./static/index.html")
}

// handleMetrics returns real-time metrics.
func (s *Server) handleMetrics(w http.ResponseWriter, r *http.Request) {
	metrics := s.store.GetMetrics()
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(metrics)
}

// handleRollouts returns a list of rollouts with pagination.
func (s *Server) handleRollouts(w http.ResponseWriter, r *http.Request) {
	limit := 50
	offset := 0
	// Parse query params if needed
	rollouts := s.store.GetRollouts(limit, offset)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(rollouts)
}

// handleRolloutDetail returns details for a specific rollout.
func (s *Server) handleRolloutDetail(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/rollout/")
	rollout := s.store.GetRollout(id)
	if rollout == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(rollout)
}

// handleTokens returns token usage statistics.
func (s *Server) handleTokens(w http.ResponseWriter, r *http.Request) {
	stats := s.store.GetTokenStats()
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(stats)
}

// handleTrajectory returns trajectory data for a specific rollout.
func (s *Server) handleTrajectory(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/trajectory/")
	trajectory := s.store.GetTrajectory(id)
	if trajectory == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(trajectory)
}

// handleToolAnalysis returns tool calling analysis data.
func (s *Server) handleToolAnalysis(w http.ResponseWriter, r *http.Request) {
	analysis := s.store.GetToolAnalysis()
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(analysis)
}

// handleVerifyAnalysis returns verify success rate analysis.
func (s *Server) handleVerifyAnalysis(w http.ResponseWriter, r *http.Request) {
	analysis := s.store.GetVerifyAnalysis()
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(analysis)
}
