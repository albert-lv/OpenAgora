package v1

import (
	"testing"

	"google.golang.org/protobuf/proto"
)

// TestPartialRolloutAndWeightSyncProtos is a regen sanity check: the messages
// and fields added for partial rollout, weight sync, and engine-native token
// IDs must exist in the generated stubs and round-trip.
func TestPartialRolloutAndWeightSyncProtos(t *testing.T) {
	msgs := []proto.Message{
		&PauseRolloutRequest{RolloutId: "r1", Mode: "freeze"},
		&PauseRolloutResponse{},
		&ResumeRolloutRequest{RolloutId: "r1"},
		&ResumeRolloutResponse{ProxyUrl: "http://127.0.0.1:1234/v1", Token: "tok"},
		&UpdateWeightsRequest{ModelPath: "/ckpt/step-10", WeightVersion: "step-10", AbortInFlight: true},
		&UpdateWeightsResponse{Success: true, Message: "ok", WeightVersion: "step-10"},
		&Rollout{RolloutId: "r1", Status: "paused", WeightVersion: "step-10"},
		&LLMResponse{
			PromptTokenIds:     []int32{11, 12, 13},
			CompletionTokenIds: []int32{21, 22},
			WeightVersion:      "step-10",
		},
	}
	for _, m := range msgs {
		data, err := proto.Marshal(m)
		if err != nil {
			t.Fatalf("marshal %T: %v", m, err)
		}
		out := m.ProtoReflect().New().Interface()
		if err := proto.Unmarshal(data, out); err != nil {
			t.Fatalf("unmarshal %T: %v", m, err)
		}
		if !proto.Equal(m, out.(proto.Message)) {
			t.Fatalf("round-trip mismatch for %T", m)
		}
	}

	// Field numbers are contract-pinned.
	lr := &LLMResponse{}
	fd := lr.ProtoReflect().Descriptor().Fields()
	if fd.ByName("prompt_token_ids").Number() != 4 || fd.ByName("completion_token_ids").Number() != 5 || fd.ByName("weight_version").Number() != 6 {
		t.Fatal("LLMResponse token-ID field numbers changed; proto contract broken")
	}
	ro := (&Rollout{}).ProtoReflect().Descriptor().Fields()
	if ro.ByName("weight_version").Number() != 8 {
		t.Fatal("Rollout.weight_version field number changed; proto contract broken")
	}
}
