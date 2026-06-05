package trajectory

import (
	"time"
)

// Step represents a single interaction in a rollout trajectory.
type Step struct {
	RolloutID string
	StepID    int
	Timestamp time.Time
	Request   *LLMRequest
	Response  *LLMResponse
	Rewards   []Reward
	Metadata  map[string]string
}

// LLMRequest captures the agent's LLM request.
type LLMRequest struct {
	Endpoint  string
	Model     string
	Messages  []byte // raw JSON
	Tools     []byte // raw JSON
	Sampling  *SamplingConfig
}

// LLMResponse captures the LLM's response.
type LLMResponse struct {
	Choices  []byte // raw JSON
	Usage    *Usage
	Logprobs []byte // raw JSON
}

// Usage tracks token consumption.
type Usage struct {
	PromptTokens     int
	CompletionTokens int
}

// Reward represents a reward signal attached to a step.
type Reward struct {
	Type   string
	Value  float64
	Source string
	Detail []byte // raw JSON
}

// SamplingConfig captures per-rollout sampling parameters.
type SamplingConfig struct {
	Temperature      float64
	TopP             float64
	Seed             int64
	MaxTokensBudget  int
}
