package dashboard

import ()

// ========== Metrics Response Types ==========

type MetricsResponse struct {
	TotalRollouts         int64   `json:"total_rollouts"`
	ActiveRollouts        int64   `json:"active_rollouts"`
	SuccessRate           float64 `json:"success_rate"`
	TotalPromptTokens     int64   `json:"total_prompt_tokens"`
	TotalCompletionTokens int64   `json:"total_completion_tokens"`
	Throughput            float64 `json:"throughput_per_min"`
	AvgReward             float64 `json:"avg_reward"`
	AvgSteps              float64 `json:"avg_steps"`
}

type RolloutListItem struct {
	ID        string  `json:"id"`
	TaskID    string  `json:"task_id"`
	Status    string  `json:"status"`
	Reward    float64 `json:"reward"`
	Steps     int     `json:"steps"`
	Duration  float64 `json:"duration_sec"`
	CreatedAt string  `json:"created_at"`
}

type TokenStats struct {
	TotalPrompt     int64            `json:"total_prompt_tokens"`
	TotalCompletion int64            `json:"total_completion_tokens"`
	ByRollout       []RolloutTokens  `json:"by_rollout"`
	Timeline        []TokenDataPoint `json:"timeline"`
}

type RolloutTokens struct {
	RolloutID        string `json:"rollout_id"`
	PromptTokens     int64  `json:"prompt_tokens"`
	CompletionTokens int64  `json:"completion_tokens"`
}

// ========== Tool Analysis Types ==========

type ToolAnalysisResponse struct {
	ToolCounts         []ToolCount      `json:"tool_counts"`
	ToolChains         []ToolChain      `json:"tool_chains"`
	ToolHeatmap        []ToolHeatmapData `json:"tool_heatmap"`
	TotalToolCalls     int64            `json:"total_tool_calls"`
	AvgToolsPerRollout float64          `json:"avg_tools_per_rollout"`
}

type ToolCount struct {
	ToolName     string  `json:"tool_name"`
	Count        int64   `json:"count"`
	SuccessCount int64   `json:"success_count"`
	SuccessRate  float64 `json:"success_rate"`
}

type ToolChain struct {
	Chain       []string `json:"chain"`
	Count       int64    `json:"count"`
	SuccessRate float64  `json:"success_rate"`
}

type ToolHeatmapData struct {
	ToolName string `json:"tool_name"`
	Window   string `json:"window"`
	Count    int64  `json:"count"`
}

// ========== Verify Analysis Types ==========

type VerifyAnalysisResponse struct {
	TotalRollouts    int64              `json:"total_rollouts"`
	SuccessCount     int64              `json:"success_count"`
	SuccessRate      float64            `json:"success_rate"`
	FirstPassRate    float64            `json:"first_pass_rate"`
	Trend            []VerifyTrendPoint `json:"trend"`
	FailureBreakdown []FailureReason    `json:"failure_breakdown"`
	ByTaskType       []TaskTypeStats    `json:"by_task_type"`
	RecentFailures   []FailureRecord    `json:"recent_failures"`
}

type VerifyTrendPoint struct {
	Timestamp string  `json:"timestamp"`
	Window    string  `json:"window"`
	Total     int64   `json:"total"`
	Success   int64   `json:"success"`
	Rate      float64 `json:"rate"`
}

type FailureReason struct {
	Reason     string  `json:"reason"`
	Count      int64   `json:"count"`
	Percentage float64 `json:"percentage"`
}

type TaskTypeStats struct {
	TaskType string  `json:"task_type"`
	Total    int64   `json:"total"`
	Success  int64   `json:"success"`
	Rate     float64 `json:"rate"`
}

type FailureRecord struct {
	RolloutID string `json:"rollout_id"`
	TaskID    string `json:"task_id"`
	Reason    string `json:"reason"`
	Steps     int    `json:"steps"`
	Reward    float64 `json:"reward"`
	Timestamp string `json:"timestamp"`
	Details   string `json:"details"`
}

// ========== Trajectory Types ==========

type TrajectoryResponse struct {
	RolloutID   string              `json:"rollout_id"`
	Steps       []TrajectoryStep    `json:"steps"`
	TotalSteps  int                 `json:"total_steps"`
	Duration    float64             `json:"duration_sec"`
}
