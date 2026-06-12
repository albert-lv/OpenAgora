package server

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
)

//go:embed dashboard/static/*
var staticFiles embed.FS

// DashboardHandler returns an http.Handler for the Arena dashboard and API.
func (s *ArenaServer) DashboardHandler() http.Handler {
	mux := http.NewServeMux()

	// API endpoints.
	mux.HandleFunc("/api/rollouts", s.handleListRollouts)
	mux.HandleFunc("/api/rollouts/", s.handleRolloutDetail)
	mux.HandleFunc("/api/stats/overview", s.handleStatsOverview)
	mux.HandleFunc("/api/stats/verify", s.handleStatsVerify)
	mux.HandleFunc("/api/stats/tokens", s.handleStatsTokens)

	// Static files and SPA fallback.
	mux.Handle("/static/", http.FileServer(http.FS(staticFiles)))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.Redirect(w, r, "/", http.StatusFound)
			return
		}
		data, err := staticFiles.ReadFile("dashboard/static/index.html")
		if err != nil {
			http.Error(w, "dashboard not found", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(data)
	})

	return mux
}

type rolloutJSON struct {
	ID         string     `json:"rollout_id"`
	TraceID    string     `json:"trace_id"`
	TaskID     string     `json:"task_id"`
	Status     string     `json:"status"`
	Reward     float64    `json:"reward"`
	CreatedAt  time.Time  `json:"created_at"`
	FinishedAt *time.Time `json:"finished_at,omitempty"`
}

func (s *ArenaServer) handleListRollouts(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	items := []rolloutJSON{}
	for _, ro := range s.rollouts {
		items = append(items, rolloutJSON{
			ID:         ro.ID,
			TraceID:    ro.TraceID,
			TaskID:     ro.TaskID,
			Status:     ro.Status,
			Reward:     ro.Reward,
			CreatedAt:  ro.CreatedAt,
			FinishedAt: ro.FinishedAt,
		})
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(items)
}

func (s *ArenaServer) handleRolloutDetail(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/rollouts/")
	parts := strings.SplitN(path, "/", 2)
	rolloutID := parts[0]

	s.mu.RLock()
	ro, ok := s.rollouts[rolloutID]
	s.mu.RUnlock()
	if !ok {
		http.Error(w, "rollout not found", http.StatusNotFound)
		return
	}

	// If trajectory subpath requested.
	if len(parts) == 2 && parts[1] == "trajectory" {
		s.handleTrajectory(w, r, rolloutID)
		return
	}

	// If logs subpath requested.
	if len(parts) == 2 && parts[1] == "logs" {
		s.handleRolloutLogs(w, r, ro)
		return
	}

	resp := rolloutJSON{
		ID:         ro.ID,
		TraceID:    ro.TraceID,
		TaskID:     ro.TaskID,
		Status:     ro.Status,
		Reward:     ro.Reward,
		CreatedAt:  ro.CreatedAt,
		FinishedAt: ro.FinishedAt,
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func (s *ArenaServer) handleRolloutLogs(w http.ResponseWriter, r *http.Request, ro *Rollout) {
	logs, err := s.sandboxProvider.Logs(r.Context(), ro.SandboxID, 100)
	if err != nil {
		http.Error(w, fmt.Sprintf("read logs: %v", err), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write(logs)
}

func (s *ArenaServer) handleTrajectory(w http.ResponseWriter, r *http.Request, rolloutID string) {
	var buf bytes.Buffer
	if err := s.trajBackend.Read(r.Context(), rolloutID, &buf); err != nil {
		http.Error(w, fmt.Sprintf("read trajectory: %v", err), http.StatusInternalServerError)
		return
	}

	var items []map[string]any
	for _, line := range strings.Split(buf.String(), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var step trajectory.Step
		if err := json.Unmarshal([]byte(line), &step); err != nil {
			continue
		}
		items = append(items, trajectoryStepToMap(&step))
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(items)
}

func trajectoryStepToMap(step *trajectory.Step) map[string]any {
	m := map[string]any{
		"rollout_id": step.RolloutID,
		"step_id":    step.StepID,
		"timestamp":  step.Timestamp,
		"trace_id":   "",
	}
	if step.Metadata != nil {
		m["trace_id"] = step.Metadata["trace_id"]
	}
	if step.Request != nil {
		m["request"] = map[string]any{
			"endpoint": step.Request.Endpoint,
			"model":    step.Request.Model,
		}
	}
	if step.Response != nil {
		resp := map[string]any{}
		if step.Response.Usage != nil {
			resp["usage"] = map[string]any{
				"prompt_tokens":     step.Response.Usage.PromptTokens,
				"completion_tokens": step.Response.Usage.CompletionTokens,
			}
		}
		if len(step.Response.Logprobs) > 0 {
			resp["logprobs_len"] = len(step.Response.Logprobs)
		}
		m["response"] = resp
	}
	return m
}

func (s *ArenaServer) handleStatsOverview(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	total := len(s.rollouts)
	var active, success, failed int
	var totalReward float64

	for _, ro := range s.rollouts {
		switch ro.Status {
		case "running":
			active++
		case "success":
			success++
		case "failed":
			failed++
		}
		totalReward += ro.Reward
	}

	avgReward := 0.0
	if total > 0 {
		avgReward = totalReward / float64(total)
	}

	tokenStats := s.collectTokenStats()

	resp := map[string]any{
		"total_rollouts":  total,
		"active_rollouts": active,
		"success_count":   success,
		"failed_count":    failed,
		"avg_reward":      avgReward,
		"total_tokens":    tokenStats.Total,
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func (s *ArenaServer) handleStatsVerify(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	total := 0
	success := 0
	var totalReward float64

	for _, ro := range s.rollouts {
		if ro.Status != "pending" && ro.Status != "running" {
			total++
			totalReward += ro.Reward
			if ro.Reward > 0 {
				success++
			}
		}
	}

	successRate := 0.0
	if total > 0 {
		successRate = float64(success) / float64(total)
	}
	avgReward := 0.0
	if total > 0 {
		avgReward = totalReward / float64(total)
	}

	resp := map[string]any{
		"total":        total,
		"success":      success,
		"success_rate": successRate,
		"avg_reward":   avgReward,
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

// tokenStats holds aggregated token usage.
type tokenStats struct {
	TotalPrompt     int64            `json:"total_prompt_tokens"`
	TotalCompletion int64            `json:"total_completion_tokens"`
	Total           int64            `json:"total_tokens"`
	ByRollout       []rolloutTokens  `json:"by_rollout"`
	Timeline        []tokenDataPoint `json:"timeline"`
}

type rolloutTokens struct {
	RolloutID        string `json:"rollout_id"`
	PromptTokens     int64  `json:"prompt_tokens"`
	CompletionTokens int64  `json:"completion_tokens"`
	TotalTokens      int64  `json:"total_tokens"`
	Steps            int    `json:"steps"`
}

type tokenDataPoint struct {
	Timestamp        string `json:"timestamp"`
	PromptTokens     int64  `json:"prompt_tokens"`
	CompletionTokens int64  `json:"completion_tokens"`
}

// collectTokenStats aggregates token usage across all rollouts.
// Caller must hold at least a read lock on s.mu.
func (s *ArenaServer) collectTokenStats() tokenStats {
	stats := tokenStats{
		ByRollout: make([]rolloutTokens, 0, len(s.rollouts)),
		Timeline:  make([]tokenDataPoint, 0),
	}

	for _, ro := range s.rollouts {
		var buf bytes.Buffer
		if err := s.trajBackend.Read(context.Background(), ro.ID, &buf); err != nil {
			continue
		}

		var prompt, completion int64
		var steps int
		for _, line := range strings.Split(buf.String(), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var step trajectory.Step
			if err := json.Unmarshal([]byte(line), &step); err != nil {
				continue
			}
			steps++
			if step.Response != nil && step.Response.Usage != nil {
				prompt += int64(step.Response.Usage.PromptTokens)
				completion += int64(step.Response.Usage.CompletionTokens)
				stats.Timeline = append(stats.Timeline, tokenDataPoint{
					Timestamp:        step.Timestamp.Format("15:04:05"),
					PromptTokens:     int64(step.Response.Usage.PromptTokens),
					CompletionTokens: int64(step.Response.Usage.CompletionTokens),
				})
			}
		}

		total := prompt + completion
		stats.TotalPrompt += prompt
		stats.TotalCompletion += completion
		stats.Total += total
		stats.ByRollout = append(stats.ByRollout, rolloutTokens{
			RolloutID:        ro.ID,
			PromptTokens:     prompt,
			CompletionTokens: completion,
			TotalTokens:      total,
			Steps:            steps,
		})
	}

	return stats
}

func (s *ArenaServer) handleStatsTokens(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	stats := s.collectTokenStats()
	s.mu.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(stats)
}
