package verify

import arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"

// Reward is a named, weighted score produced by a verifier or the agent.
// Multiple rewards allow multi-dimensional evaluation (e.g. correctness + style).
type Reward struct {
	Name   string
	Value  float64
	Weight float64
	Source string
}

// TotalReward computes the weighted sum of rewards. If no weights are set it
// falls back to the arithmetic mean.
func TotalReward(rewards []Reward) float64 {
	if len(rewards) == 0 {
		return 0.0
	}
	var sum, weightSum float64
	hasWeights := false
	for _, r := range rewards {
		if r.Weight != 0 {
			hasWeights = true
		}
		weightSum += r.Weight
	}
	if !hasWeights {
		for _, r := range rewards {
			sum += r.Value
		}
		return sum / float64(len(rewards))
	}
	if weightSum == 0 {
		return 0.0
	}
	for _, r := range rewards {
		sum += r.Value * r.Weight
	}
	return sum / weightSum
}

// VerificationReport is the structured result of a verification run.
type VerificationReport struct {
	// Deprecated: use TotalReward and Rewards instead.
	Reward      float64
	TotalReward float64
	Rewards     []Reward
	F2PCount    int
	P2PCount    int
	F2FCount    int
	P2FCount    int
	TestCases   []TestCaseTransition
	Stdout      string
	Stderr      string
}

// ComputeCounts recalculates F2F/F2P/P2P/P2F counters from TestCases.
func (r *VerificationReport) ComputeCounts() {
	r.F2FCount = 0
	r.F2PCount = 0
	r.P2PCount = 0
	r.P2FCount = 0
	for _, tc := range r.TestCases {
		switch tc.Category {
		case CategoryF2F:
			r.F2FCount++
		case CategoryF2P:
			r.F2PCount++
		case CategoryP2P:
			r.P2PCount++
		case CategoryP2F:
			r.P2FCount++
		}
	}
}

// ToProto converts the report to its protobuf representation.
func (r *VerificationReport) ToProto() *arena_pb.VerificationReport {
	if r == nil {
		return nil
	}
	cases := make([]*arena_pb.TestCaseResult, len(r.TestCases))
	for i, tc := range r.TestCases {
		cases[i] = &arena_pb.TestCaseResult{
			TestId:         tc.ID,
			BaselinePassed: tc.BaselineStatus == StatusPass,
			PatchPassed:    tc.PatchStatus == StatusPass,
			Category:       string(tc.Category),
		}
	}
	rewards := make([]*arena_pb.Reward, len(r.Rewards))
	for i, rw := range r.Rewards {
		rewards[i] = &arena_pb.Reward{
			Name:   rw.Name,
			Value:  float32(rw.Value),
			Weight: float32(rw.Weight),
			Source: rw.Source,
		}
	}
	return &arena_pb.VerificationReport{
		Reward:      float32(r.Reward),
		TotalReward: float32(r.TotalReward),
		Rewards:     rewards,
		F2PCount:    int32(r.F2PCount),
		P2PCount:    int32(r.P2PCount),
		F2FCount:    int32(r.F2FCount),
		P2FCount:    int32(r.P2FCount),
		TestCases:   cases,
		Stdout:      r.Stdout,
		Stderr:      r.Stderr,
	}
}
