package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/albert-lv/agent-arena/go/pkg/proxy"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox"
	"github.com/albert-lv/agent-arena/go/pkg/trajectory"
	"github.com/albert-lv/agent-arena/go/pkg/trajectory/backend"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/google/uuid"
	"go.uber.org/zap"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Rollout holds the runtime state of a single rollout.
type Rollout struct {
	ID         string
	TaskID     string
	Status     string // pending, running, success, failed, stopped
	SandboxID  string
	Token      string
	ProxyAddr  string
	Reward     float64
	CreatedAt  time.Time
	FinishedAt *time.Time
}

// ArenaServer implements the ArenaService gRPC server.
type ArenaServer struct {
	arena_pb.UnimplementedArenaServiceServer
	logger *zap.Logger

	sandboxProvider sandbox.Provider
	proxy           *proxy.Proxy
	verifyRunner    VerifyRunner
	trajBackend     backend.Backend
	trajWriter      trajectory.Writer
	trajDir         string

	mu       sync.RWMutex
	rollouts map[string]*Rollout // key = rolloutID
}

// VerifyRunner defines the interface for verification.
type VerifyRunner interface {
	Run(ctx context.Context, sandboxID string, command string) ([]float64, error)
}

// ServerConfig holds optional configuration for ArenaServer.
type ServerConfig struct {
	SandboxProvider sandbox.Provider
	Proxy           *proxy.Proxy
	VerifyRunner    VerifyRunner
	TrajBackend     backend.Backend
	TrajWriter      trajectory.Writer
	TrajDir         string
}

// New creates a new ArenaServer instance.
func New(logger *zap.Logger, cfg *ServerConfig) *ArenaServer {
	if cfg == nil {
		cfg = &ServerConfig{}
	}

	// Setup trajectory storage defaults.
	trajDir := cfg.TrajDir
	if trajDir == "" {
		trajDir = filepath.Join(os.TempDir(), "arena-trajectories")
		_ = os.MkdirAll(trajDir, 0755)
	}
	trajBackend := cfg.TrajBackend
	if trajBackend == nil {
		trajBackend = backend.NewLocalJSONL(trajDir)
	}
	trajWriter := cfg.TrajWriter
	if trajWriter == nil {
		// Wrap backend as writer.
		trajWriter = &backendWriter{backend: trajBackend}
	}

	// Setup sandbox provider default.
	sbProvider := cfg.SandboxProvider
	if sbProvider == nil {
		// Will be nil if docker is not available; callers should provide one.
	}

	// Setup proxy default.
	var p *proxy.Proxy
	if cfg.Proxy != nil {
		p = cfg.Proxy
	} else {
		// Create a shared proxy instance; rollouts will register with per-rollout backends.
		var err error
		p, err = proxy.NewProxy("", trajWriter, logger)
		if err != nil {
			logger.Fatal("failed to create proxy", zap.Error(err))
		}
	}

	return &ArenaServer{
		logger:          logger,
		sandboxProvider: sbProvider,
		proxy:           p,
		verifyRunner:    cfg.VerifyRunner,
		trajBackend:     trajBackend,
		trajWriter:      trajWriter,
		trajDir:         trajDir,
		rollouts:        make(map[string]*Rollout),
	}
}

// CreateRollout starts a new rollout.
func (s *ArenaServer) CreateRollout(ctx context.Context, req *arena_pb.CreateRolloutRequest) (*arena_pb.CreateRolloutResponse, error) {
	if s.sandboxProvider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}

	rolloutID := uuid.NewString()
	token := uuid.NewString()

	s.logger.Info("CreateRollout",
		zap.String("rollout_id", rolloutID),
		zap.String("task_id", req.TaskId),
		zap.String("image", req.Sandbox.Image),
		zap.String("llm_backend", req.LlmBackend))

	// 1. Start proxy server for this rollout.
	ps, err := proxy.NewProxyServer(s.proxy, s.logger)
	if err != nil {
		return nil, fmt.Errorf("proxy server: %w", err)
	}
	proxyAddr, err := ps.Start()
	if err != nil {
		return nil, fmt.Errorf("proxy start: %w", err)
	}

	// 2. Register rollout on the shared proxy.
	sampling := protoToInternalSampling(req.Sampling)
	s.proxy.RegisterRollout(rolloutID, token, sampling, req.LlmBackend)

	// 3. Build sandbox config with injected env vars.
	envVars := req.Sandbox.EnvVars
	if envVars == nil {
		envVars = make(map[string]string)
	}
	envVars["OPENAI_BASE_URL"] = fmt.Sprintf("http://%s/v1", proxyAddr)
	envVars["ARENA_ROLLOUT_TOKEN"] = token
	envVars["ARENA_TASK_ID"] = req.TaskId
	envVars["ARENA_SANDBOX_ID"] = rolloutID // will be overwritten after container creation

	sbConfig := &sandbox.Config{
		Image:    req.Sandbox.Image,
		Memory:   req.Sandbox.Memory,
		CPUs:     req.Sandbox.Cpus,
		EnvVars:  envVars,
		TaskFile: req.Sandbox.TaskFile,
		Timeout:  time.Duration(req.Sandbox.TimeoutSeconds) * time.Second,
	}

	// 4. Create sandbox.
	sb, err := s.sandboxProvider.Create(ctx, sbConfig)
	if err != nil {
		s.proxy.UnregisterRollout(token)
		ps.Close()
		return nil, fmt.Errorf("sandbox create: %w", err)
	}

	// Update env with real sandbox ID.
	envVars["ARENA_SANDBOX_ID"] = sb.ID

	// 5. Start sandbox.
	if err := s.sandboxProvider.Start(ctx, sb.ID); err != nil {
		s.proxy.UnregisterRollout(token)
		_ = s.sandboxProvider.Destroy(ctx, sb.ID)
		ps.Close()
		return nil, fmt.Errorf("sandbox start: %w", err)
	}

	// 6. Record rollout state.
	rollout := &Rollout{
		ID:        rolloutID,
		TaskID:    req.TaskId,
		Status:    "running",
		SandboxID: sb.ID,
		Token:     token,
		ProxyAddr: proxyAddr,
		CreatedAt: time.Now(),
	}
	s.mu.Lock()
	s.rollouts[rolloutID] = rollout
	s.mu.Unlock()

	// 7. Background goroutine: wait for completion, verify, update state.
	go s.runLifecycle(rolloutID, sb.ID, token, ps, req.Verify)

	proxyURL := fmt.Sprintf("http://%s/v1", proxyAddr)
	return &arena_pb.CreateRolloutResponse{RolloutId: rolloutID, ProxyUrl: proxyURL, Token: token}, nil
}

// runLifecycle waits for the sandbox to finish, runs verification, and updates state.
func (s *ArenaServer) runLifecycle(rolloutID, sandboxID, token string, ps *proxy.ProxyServer, verifyCfg *arena_pb.VerifyConfig) {
	ctx := context.Background()

	// Wait for sandbox completion.
	err := s.sandboxProvider.WaitForDone(ctx, sandboxID)
	if err != nil {
		s.logger.Warn("WaitForDone error", zap.String("rollout_id", rolloutID), zap.Error(err))
	}

	// Stop the sandbox (idempotent).
	_ = s.sandboxProvider.Stop(ctx, sandboxID)

	// Run verification if configured.
	var reward float64
	if verifyCfg != nil && verifyCfg.Command != "" && s.verifyRunner != nil {
		rewards, verr := s.verifyRunner.Run(ctx, sandboxID, verifyCfg.Command)
		if verr != nil {
			s.logger.Warn("verification failed",
				zap.String("rollout_id", rolloutID),
				zap.Error(verr))
		} else if len(rewards) > 0 {
			reward = rewards[0]
		}
	}

	// Update rollout state.
	now := time.Now()
	s.mu.Lock()
	if r, ok := s.rollouts[rolloutID]; ok {
		r.FinishedAt = &now
		r.Reward = reward
		if err != nil {
			r.Status = "failed"
		} else {
			r.Status = "success"
		}
	}
	s.mu.Unlock()

	// Cleanup proxy registration.
	s.proxy.UnregisterRollout(token)
	_ = ps.Close()

	s.logger.Info("rollout finished",
		zap.String("rollout_id", rolloutID),
		zap.String("status", s.rollouts[rolloutID].Status),
		zap.Float64("reward", reward))
}

// GetRollout returns the status of a rollout.
func (s *ArenaServer) GetRollout(ctx context.Context, req *arena_pb.GetRolloutRequest) (*arena_pb.Rollout, error) {
	s.mu.RLock()
	r, ok := s.rollouts[req.RolloutId]
	s.mu.RUnlock()
	if !ok {
		return nil, fmt.Errorf("rollout not found: %s", req.RolloutId)
	}
	return s.toProtoRollout(r), nil
}

// StopRollout stops a running rollout.
func (s *ArenaServer) StopRollout(ctx context.Context, req *arena_pb.StopRolloutRequest) (*arena_pb.StopRolloutResponse, error) {
	s.mu.Lock()
	r, ok := s.rollouts[req.RolloutId]
	if !ok {
		s.mu.Unlock()
		return nil, fmt.Errorf("rollout not found: %s", req.RolloutId)
	}
	r.Status = "stopped"
	s.mu.Unlock()

	if err := s.sandboxProvider.Stop(ctx, r.SandboxID); err != nil {
		s.logger.Warn("failed to stop sandbox", zap.String("rollout_id", req.RolloutId), zap.Error(err))
	}
	return &arena_pb.StopRolloutResponse{}, nil
}

// ListRollouts lists all rollouts.
func (s *ArenaServer) ListRollouts(ctx context.Context, req *arena_pb.ListRolloutsRequest) (*arena_pb.ListRolloutsResponse, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var list []*arena_pb.Rollout
	for _, r := range s.rollouts {
		list = append(list, s.toProtoRollout(r))
	}
	return &arena_pb.ListRolloutsResponse{Rollouts: list}, nil
}

// StreamTrajectory streams trajectory steps in real-time.
func (s *ArenaServer) StreamTrajectory(req *arena_pb.StreamTrajectoryRequest, stream arena_pb.ArenaService_StreamTrajectoryServer) error {
	// For simplicity, read the full trajectory from backend and stream it.
	pr, pw := io.Pipe()
	go func() {
		_ = s.trajBackend.Read(stream.Context(), req.RolloutId, pw)
		_ = pw.Close()
	}()

	scanner := json.NewDecoder(pr)
	stepID := 0
	for {
		var step trajectory.Step
		if err := scanner.Decode(&step); err != nil {
			if err == io.EOF {
				break
			}
			return fmt.Errorf("decode trajectory: %w", err)
		}
		stepID++
		pbStep := s.toProtoStep(&step, stepID)
		if err := stream.Send(pbStep); err != nil {
			return fmt.Errorf("send trajectory: %w", err)
		}
	}
	return nil
}

// GetTrajectory returns the full trajectory for a completed rollout.
func (s *ArenaServer) GetTrajectory(ctx context.Context, req *arena_pb.GetTrajectoryRequest) (*arena_pb.Trajectory, error) {
	pr, pw := io.Pipe()
	go func() {
		_ = s.trajBackend.Read(ctx, req.RolloutId, pw)
		_ = pw.Close()
	}()

	var steps []*arena_pb.TrajectoryStep
	scanner := json.NewDecoder(pr)
	stepID := 0
	for {
		var step trajectory.Step
		if err := scanner.Decode(&step); err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("decode trajectory: %w", err)
		}
		stepID++
		steps = append(steps, s.toProtoStep(&step, stepID))
	}
	return &arena_pb.Trajectory{Steps: steps}, nil
}

// toProtoRollout converts internal Rollout to protobuf Rollout.
func (s *ArenaServer) toProtoRollout(r *Rollout) *arena_pb.Rollout {
	pb := &arena_pb.Rollout{
		RolloutId: r.ID,
		TaskId:    r.TaskID,
		Status:    r.Status,
		CreatedAt: timestamppb.New(r.CreatedAt),
		Reward:    float32(r.Reward),
	}
	if r.FinishedAt != nil {
		pb.FinishedAt = timestamppb.New(*r.FinishedAt)
	}
	return pb
}

// toProtoStep converts internal Step to protobuf TrajectoryStep.
func (s *ArenaServer) toProtoStep(step *trajectory.Step, stepID int) *arena_pb.TrajectoryStep {
	pb := &arena_pb.TrajectoryStep{
		RolloutId: step.RolloutID,
		StepId:    int32(stepID),
		Ts:        timestamppb.New(step.Timestamp),
		Metadata:  step.Metadata,
	}
	if step.Request != nil {
		pb.Request = &arena_pb.LLMRequest{
			Endpoint:     step.Request.Endpoint,
			Model:        step.Request.Model,
			MessagesJson: step.Request.Messages,
			ToolsJson:    step.Request.Tools,
		}
		if step.Request.Sampling != nil {
			pb.Request.Sampling = &arena_pb.SamplingConfig{
				Temperature:     float32(step.Request.Sampling.Temperature),
				TopP:            float32(step.Request.Sampling.TopP),
				Seed:            step.Request.Sampling.Seed,
				MaxTokensBudget: int32(step.Request.Sampling.MaxTokensBudget),
			}
		}
	}
	if step.Response != nil {
		pb.Response = &arena_pb.LLMResponse{
			ChoicesJson: step.Response.Choices,
			LogprobsJson: step.Response.Logprobs,
		}
		if step.Response.Usage != nil {
			pb.Response.Usage = &arena_pb.Usage{
				PromptTokens:     int32(step.Response.Usage.PromptTokens),
				CompletionTokens: int32(step.Response.Usage.CompletionTokens),
			}
		}
	}
	for _, rw := range step.Rewards {
		pb.Rewards = append(pb.Rewards, &arena_pb.Reward{
			Type:   rw.Type,
			Value:  float32(rw.Value),
			Source: rw.Source,
		})
	}
	return pb
}

// protoToInternalSampling converts protobuf SamplingConfig to internal type.
func protoToInternalSampling(cfg *arena_pb.SamplingConfig) *trajectory.SamplingConfig {
	if cfg == nil {
		return nil
	}
	return &trajectory.SamplingConfig{
		Temperature:     float64(cfg.Temperature),
		TopP:            float64(cfg.TopP),
		Seed:            cfg.Seed,
		MaxTokensBudget: int(cfg.MaxTokensBudget),
	}
}

// backendWriter wraps a backend.Backend as a trajectory.Writer.
type backendWriter struct {
	backend backend.Backend
}

func (w *backendWriter) Write(ctx context.Context, step *trajectory.Step) error {
	return w.backend.Write(ctx, step.RolloutID, step)
}

func (w *backendWriter) Close(ctx context.Context) error {
	return w.backend.Close(ctx)
}
