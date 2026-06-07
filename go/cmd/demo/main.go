package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox/mock"
	"github.com/albert-lv/agent-arena/go/pkg/server"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	logger, _ := zap.NewDevelopment()

	// 1. Start Arena gRPC server with mock sandbox.
	grpcSvr := grpc.NewServer()
	arena_pb.RegisterArenaServiceServer(grpcSvr, server.New(logger, &server.ServerConfig{
		SandboxProvider: mock.NewProvider(),
	}))
	lis, _ := net.Listen("tcp", "127.0.0.1:9090")
	go func() { _ = grpcSvr.Serve(lis) }()
	fmt.Println("Arena gRPC: 127.0.0.1:9090")

	// 2. Start mock LLM backend.
	llmMux := http.NewServeMux()
	llmMux.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": "print('hello')"}}},
			"usage":   map[string]any{"prompt_tokens": 12, "completion_tokens": 6},
		})
	})
	llmLis, _ := net.Listen("tcp", "127.0.0.1:0")
	go func() { _ = http.Serve(llmLis, llmMux) }()
	llmURL := fmt.Sprintf("http://%s/v1", llmLis.Addr().String())
	fmt.Println("Mock LLM:", llmURL)

	// 3. Create gRPC client.
	conn, _ := grpc.NewClient("127.0.0.1:9090", grpc.WithTransportCredentials(insecure.NewCredentials()))
	client := arena_pb.NewArenaServiceClient(conn)
	ctx := context.Background()

	// 4. Create rollout.
	resp, _ := client.CreateRollout(ctx, &arena_pb.CreateRolloutRequest{
		TaskId:     "demo-task",
		LlmBackend: llmURL,
		Sandbox:    &arena_pb.SandboxConfig{Image: "mock"},
		Sampling:   &arena_pb.SamplingConfig{Temperature: 0.5, Seed: 42},
	})
	fmt.Println("Rollout ID:", resp.RolloutId)
	fmt.Println("Proxy URL: ", resp.ProxyUrl)

	// 5. Simulate agent calling proxy (2 requests) with correct token.
	time.Sleep(200 * time.Millisecond)
	for i := 0; i < 2; i++ {
		body, _ := json.Marshal(map[string]any{"model": "gpt-4", "messages": []any{}})
		req, _ := http.NewRequest("POST", resp.ProxyUrl+"/chat/completions", bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+resp.Token)
		req.Header.Set("Content-Type", "application/json")
		r, _ := http.DefaultClient.Do(req)
		_, _ = io.Copy(io.Discard, r.Body)
		_ = r.Body.Close()
		fmt.Printf("Agent call %d: %s\n", i+1, r.Status)
	}

	// 6. Wait for rollout to finish.
	fmt.Println("Waiting for rollout...")
	for {
		rollout, _ := client.GetRollout(ctx, &arena_pb.GetRolloutRequest{RolloutId: resp.RolloutId})
		if rollout.Status == "success" || rollout.Status == "failed" {
			fmt.Printf("Status: %s  Reward: %.2f\n", rollout.Status, rollout.Reward)
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	// 7. Fetch trajectory.
	traj, _ := client.GetTrajectory(ctx, &arena_pb.GetTrajectoryRequest{RolloutId: resp.RolloutId})
	fmt.Printf("Trajectory steps: %d\n", len(traj.Steps))
	for _, s := range traj.Steps {
		u := s.Response.Usage
		fmt.Printf("  step %d: prompt=%d completion=%d\n", s.StepId, u.PromptTokens, u.CompletionTokens)
	}
	grpcSvr.GracefulStop()
}
