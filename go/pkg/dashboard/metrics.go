package dashboard

import (
	"sort"
	"strings"
	"sync"
	"time"
)

// MetricsStore holds all dashboard metrics in memory.
type MetricsStore struct {
	mu sync.RWMutex

	// Rollout metrics
	totalRollouts      int64
	activeRollouts     int64
	successCount       int64
	failedCount        int64
	rolloutHistory     []RolloutRecord

	// Token metrics
	totalPromptTokens     int64
	totalCompletionTokens int64
	tokenTimeline         []TokenDataPoint

	// Tool metrics
	toolCalls        map[string]int64
	toolSuccess      map[string]int64
	toolChains       map[string]int64

	// Verify metrics
	verifyResults      []VerifyResult
	failureReasons     map[string]int64

	// Trajectory store
	trajectories   map[string][]TrajectoryStep
}

// RolloutRecord represents a single rollout.
type RolloutRecord struct {
	ID        string    `json:"id"`
	TaskID    string    `json:"task_id"`
	Status    string    `json:"status"`
	Reward    float64   `json:"reward"`
	Steps     int       `json:"steps"`
	Duration  float64   `json:"duration_sec"`
	CreatedAt time.Time `json:"created_at"`
}

// TokenDataPoint represents token usage at a point in time.
type TokenDataPoint struct {
	Timestamp      string `json:"timestamp"`
	PromptTokens     int64  `json:"prompt_tokens"`
	CompletionTokens int64  `json:"completion_tokens"`
}

// TrajectoryStep represents a single step in a trajectory.
type TrajectoryStep struct {
	StepID    int                    `json:"step_id"`
	Action    string                 `json:"action"`
	Arguments map[string]interface{} `json:"arguments"`
	Observation string               `json:"observation"`
	Timestamp time.Time              `json:"timestamp"`
}

// VerifyResult represents a verification result.
type VerifyResult struct {
	RolloutID   string    `json:"rollout_id"`
	TaskID      string    `json:"task_id"`
	Success     bool      `json:"success"`
	Reward      float64   `json:"reward"`
	Reason      string    `json:"reason"`
	Timestamp   time.Time `json:"timestamp"`
}

// NewMetricsStore creates a new metrics store.
func NewMetricsStore() *MetricsStore {
	return &MetricsStore{
		rolloutHistory: make([]RolloutRecord, 0),
		tokenTimeline:  make([]TokenDataPoint, 0),
		toolCalls:      make(map[string]int64),
		toolSuccess:    make(map[string]int64),
		toolChains:     make(map[string]int64),
		failureReasons: make(map[string]int64),
		trajectories:   make(map[string][]TrajectoryStep),
	}
}

// RecordRolloutCreated records a new rollout creation.
func (s *MetricsStore) RecordRolloutCreated(id, taskID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.totalRollouts++
	s.activeRollouts++
	s.rolloutHistory = append(s.rolloutHistory, RolloutRecord{
		ID:        id,
		TaskID:    taskID,
		Status:    "running",
		CreatedAt: time.Now(),
	})
}

// RecordRolloutCompleted records a rollout completion.
func (s *MetricsStore) RecordRolloutCompleted(id string, status string, reward float64, steps int, duration float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.activeRollouts--
	if status == "success" {
		s.successCount++
	} else {
		s.failedCount++
	}
	// Update record
	for i := range s.rolloutHistory {
		if s.rolloutHistory[i].ID == id {
			s.rolloutHistory[i].Status = status
			s.rolloutHistory[i].Reward = reward
			s.rolloutHistory[i].Steps = steps
			s.rolloutHistory[i].Duration = duration
			break
		}
	}
}

// RecordTokens records token usage.
func (s *MetricsStore) RecordTokens(promptTokens, completionTokens int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.totalPromptTokens += promptTokens
	s.totalCompletionTokens += completionTokens
	s.tokenTimeline = append(s.tokenTimeline, TokenDataPoint{
		Timestamp:      time.Now().Format("15:04:05"),
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
	})
	// Keep only last 1000 points
	if len(s.tokenTimeline) > 1000 {
		s.tokenTimeline = s.tokenTimeline[len(s.tokenTimeline)-1000:]
	}
}

// RecordToolCall records a tool call.
func (s *MetricsStore) RecordToolCall(toolName string, success bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.toolCalls[toolName]++
	if success {
		s.toolSuccess[toolName]++
	}
}

// RecordToolChain records a tool chain sequence.
func (s *MetricsStore) RecordToolChain(chain []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	key := strings.Join(chain, "->")
	s.toolChains[key]++
}

// RecordVerifyResult records a verification result.
func (s *MetricsStore) RecordVerifyResult(rolloutID, taskID string, success bool, reward float64, reason string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.verifyResults = append(s.verifyResults, VerifyResult{
		RolloutID: rolloutID,
		TaskID:    taskID,
		Success:   success,
		Reward:    reward,
		Reason:    reason,
		Timestamp: time.Now(),
	})
	if !success && reason != "" {
		s.failureReasons[reason]++
	}
	// Keep only last 10000 results
	if len(s.verifyResults) > 10000 {
		s.verifyResults = s.verifyResults[len(s.verifyResults)-10000:]
	}
}

// RecordTrajectory records a trajectory step.
func (s *MetricsStore) RecordTrajectory(rolloutID string, step TrajectoryStep) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.trajectories[rolloutID] = append(s.trajectories[rolloutID], step)
}

// GetMetrics returns current metrics summary.
func (s *MetricsStore) GetMetrics() MetricsResponse {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var avgReward, avgSteps float64
	var completedCount int64
	for _, r := range s.rolloutHistory {
		if r.Status != "running" {
			avgReward += r.Reward
			avgSteps += float64(r.Steps)
			completedCount++
		}
	}
	if completedCount > 0 {
		avgReward /= float64(completedCount)
		avgSteps /= float64(completedCount)
	}

	var successRate float64
	if s.totalRollouts > 0 {
		successRate = float64(s.successCount) / float64(s.totalRollouts)
	}

	// Calculate throughput (rollouts per minute in last 10 minutes)
	var throughput float64
	cutoff := time.Now().Add(-10 * time.Minute)
	recentCount := 0
	for _, r := range s.rolloutHistory {
		if r.CreatedAt.After(cutoff) {
			recentCount++
		}
	}
	throughput = float64(recentCount) / 10.0

	return MetricsResponse{
		TotalRollouts:         s.totalRollouts,
		ActiveRollouts:        s.activeRollouts,
		SuccessRate:           successRate,
		TotalPromptTokens:     s.totalPromptTokens,
		TotalCompletionTokens: s.totalCompletionTokens,
		Throughput:            throughput,
		AvgReward:             avgReward,
		AvgSteps:              avgSteps,
	}
}

// GetRollouts returns a paginated list of rollouts.
func (s *MetricsStore) GetRollouts(limit, offset int) []RolloutListItem {
	s.mu.RLock()
	defer s.mu.RUnlock()

	items := make([]RolloutListItem, 0, limit)
	start := len(s.rolloutHistory) - offset - limit
	if start < 0 {
		start = 0
	}
	end := start + limit
	if end > len(s.rolloutHistory) {
		end = len(s.rolloutHistory)
	}

	for i := end - 1; i >= start; i-- {
		r := s.rolloutHistory[i]
		items = append(items, RolloutListItem{
			ID:        r.ID,
			TaskID:    r.TaskID,
			Status:    r.Status,
			Reward:    r.Reward,
			Steps:     r.Steps,
			Duration:  r.Duration,
			CreatedAt: r.CreatedAt.Format("2006-01-02 15:04:05"),
		})
	}
	return items
}

// GetRollout returns a single rollout by ID.
func (s *MetricsStore) GetRollout(id string) *RolloutRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, r := range s.rolloutHistory {
		if r.ID == id {
			return &r
		}
	}
	return nil
}

// GetTokenStats returns token usage statistics.
func (s *MetricsStore) GetTokenStats() TokenStats {
	s.mu.RLock()
	defer s.mu.RUnlock()

	byRollout := make([]RolloutTokens, 0)
	return TokenStats{
		TotalPrompt:     s.totalPromptTokens,
		TotalCompletion: s.totalCompletionTokens,
		ByRollout:       byRollout,
		Timeline:        s.tokenTimeline,
	}
}

// GetTrajectory returns trajectory for a rollout.
func (s *MetricsStore) GetTrajectory(id string) []TrajectoryStep {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.trajectories[id]
}

// GetToolAnalysis returns tool calling analysis.
func (s *MetricsStore) GetToolAnalysis() ToolAnalysisResponse {
	s.mu.RLock()
	defer s.mu.RUnlock()

	toolCounts := make([]ToolCount, 0, len(s.toolCalls))
	for name, count := range s.toolCalls {
		successRate := 0.0
		if count > 0 {
			successRate = float64(s.toolSuccess[name]) / float64(count)
		}
		toolCounts = append(toolCounts, ToolCount{
			ToolName:     name,
			Count:        count,
			SuccessCount: s.toolSuccess[name],
			SuccessRate:  successRate,
		})
	}

	// Sort by count descending
	sort.Slice(toolCounts, func(i, j int) bool {
		return toolCounts[i].Count > toolCounts[j].Count
	})

	// Top chains
	toolChains := make([]ToolChain, 0, len(s.toolChains))
	for chain, count := range s.toolChains {
		toolChains = append(toolChains, ToolChain{
			Chain: strings.Split(chain, "->"),
			Count: count,
		})
	}
	// Sort by count descending
	sort.Slice(toolChains, func(i, j int) bool {
		return toolChains[i].Count > toolChains[j].Count
	})
	if len(toolChains) > 20 {
		toolChains = toolChains[:20]
	}

	totalCalls := int64(0)
	for _, c := range s.toolCalls {
		totalCalls += c
	}

	avgTools := 0.0
	if s.totalRollouts > 0 {
		avgTools = float64(totalCalls) / float64(s.totalRollouts)
	}

	return ToolAnalysisResponse{
		ToolCounts:       toolCounts,
		ToolChains:       toolChains,
		TotalToolCalls:   totalCalls,
		AvgToolsPerRollout: avgTools,
	}
}

// GetVerifyAnalysis returns verify success rate analysis.
func (s *MetricsStore) GetVerifyAnalysis() VerifyAnalysisResponse {
	s.mu.RLock()
	defer s.mu.RUnlock()

	total := int64(len(s.verifyResults))
	var successCount int64
	for _, v := range s.verifyResults {
		if v.Success {
			successCount++
		}
	}

	successRate := 0.0
	if total > 0 {
		successRate = float64(successCount) / float64(total)
	}

	// Calculate first pass rate (rollouts that succeeded on first try)
	// For simplicity, we consider all success as first pass here
	firstPassRate := successRate

	// Trend by 5-minute windows
	trend := make([]VerifyTrendPoint, 0)
	windowSize := 5 * time.Minute
	now := time.Now()
	for i := 0; i < 12; i++ { // Last hour
		windowStart := now.Add(-time.Duration(i+1) * windowSize)
		windowEnd := now.Add(-time.Duration(i) * windowSize)
		var wTotal, wSuccess int64
		for _, v := range s.verifyResults {
			if v.Timestamp.After(windowStart) && v.Timestamp.Before(windowEnd) {
				wTotal++
				if v.Success {
					wSuccess++
				}
			}
		}
		wRate := 0.0
		if wTotal > 0 {
			wRate = float64(wSuccess) / float64(wTotal)
		}
		trend = append(trend, VerifyTrendPoint{
			Timestamp: windowEnd.Format("15:04"),
			Window:    "5min",
			Total:     wTotal,
			Success:   wSuccess,
			Rate:      wRate,
		})
	}
	// Reverse to get chronological order
	for i, j := 0, len(trend)-1; i < j; i, j = i+1, j-1 {
		trend[i], trend[j] = trend[j], trend[i]
	}

	// Failure breakdown
	failureBreakdown := make([]FailureReason, 0, len(s.failureReasons))
	for reason, count := range s.failureReasons {
		percentage := 0.0
		if s.failedCount > 0 {
			percentage = float64(count) / float64(s.failedCount) * 100
		}
		failureBreakdown = append(failureBreakdown, FailureReason{
			Reason:     reason,
			Count:      count,
			Percentage: percentage,
		})
	}

	// Recent failures
	recentFailures := make([]FailureRecord, 0, 10)
	for i := len(s.verifyResults) - 1; i >= 0 && len(recentFailures) < 10; i-- {
		if !s.verifyResults[i].Success {
			recentFailures = append(recentFailures, FailureRecord{
				RolloutID: s.verifyResults[i].RolloutID,
				TaskID:    s.verifyResults[i].TaskID,
				Reason:    s.verifyResults[i].Reason,
				Timestamp: s.verifyResults[i].Timestamp.Format("2006-01-02 15:04:05"),
			})
		}
	}

	return VerifyAnalysisResponse{
		TotalRollouts:    total,
		SuccessCount:     successCount,
		SuccessRate:      successRate,
		FirstPassRate:    firstPassRate,
		Trend:            trend,
		FailureBreakdown: failureBreakdown,
		RecentFailures:   recentFailures,
	}
}
