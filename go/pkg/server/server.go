package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/albert-lv/OpenAgora/go/pkg/inference"
	"github.com/albert-lv/OpenAgora/go/pkg/proxy"
	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
	"github.com/albert-lv/OpenAgora/go/pkg/trajectory"
	"github.com/albert-lv/OpenAgora/go/pkg/trajectory/backend"
	"github.com/albert-lv/OpenAgora/go/pkg/verify"
	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
	"github.com/google/uuid"
	"go.uber.org/zap"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// Rollout holds the runtime state of a single rollout.
type Rollout struct {
	ID                 string
	TraceID            string
	TaskID             string
	Status             string // pending, running, paused, success, failed, stopped
	SandboxID          string
	Token              string
	ProxyAddr          string
	ProxyURL           string // URL handed to the trainer; returned again by ResumeRollout
	WeightVersion      string // weight version this rollout's generation is attributed to
	Reward             float64
	VerificationReport *verify.VerificationReport
	Timeout            time.Duration // max time the sandbox may run
	CreatedAt          time.Time
	FinishedAt         *time.Time
	// Pause accounting: the timeout clock is suspended while paused.
	PausedAt    time.Time
	PausedTotal time.Duration
	stateCh     chan struct{} // signalled (non-blocking) on pause/resume
}

// ArenaServer implements the ArenaService gRPC server.
type ArenaServer struct {
	arena_pb.UnimplementedArenaServiceServer
	logger *zap.Logger

	sandboxProvider    sandbox.Provider
	proxy              *proxy.Proxy
	proxyAdvertiseHost string
	verifyRunner       VerifyRunner
	syncVerify         bool
	trajBackend        backend.Backend
	trajWriter         trajectory.Writer
	trajDir            string
	metrics            *Metrics
	weightSyncer       inference.WeightSyncer

	weightMu             sync.Mutex // serializes UpdateWeights calls
	currentWeightVersion string

	mu       sync.RWMutex
	rollouts map[string]*Rollout // key = rolloutID
}

// VerifyRunner defines the interface for verification.
// If nil, the server uses verify.Resolve directly.
type VerifyRunner interface {
	Run(ctx context.Context, provider sandbox.Provider, spec *verify.VerificationSpec, sandboxID string) (*verify.VerificationReport, error)
}

// ServerConfig holds optional configuration for ArenaServer.
type ServerConfig struct {
	SandboxProvider    sandbox.Provider
	Proxy              *proxy.Proxy
	ProxyAdvertiseHost string        // optional host advertised to sandboxes instead of the proxy listener address (e.g. "host.docker.internal")
	ProxyTimeout       time.Duration // timeout for proxied LLM backend calls; falls back to ARENA_PROXY_TIMEOUT, then proxy.DefaultHTTPTimeout
	VerifyRunner       VerifyRunner
	// SyncVerify restores the legacy behavior of running verification inline
	// before the rollout is marked complete. By default verification runs
	// asynchronously: the rollout reaches its terminal status as soon as
	// generation finishes and the reward/report are filled in afterwards.
	SyncVerify  bool
	TrajBackend backend.Backend
	TrajWriter  trajectory.Writer
	TrajDir     string
	Metrics     *Metrics
	// BackendType identifies the shared LLM inference backend ("sglang" or
	// "vllm"); BackendURL points at it. Both fall back to the
	// ARENA_BACKEND_TYPE / ARENA_BACKEND_URL env vars. Together they enable
	// weight synchronization (UpdateWeights) and backend-specific proxy
	// capture. WeightSyncer overrides the syncer built from these settings.
	BackendType  string
	BackendURL   string
	WeightSyncer inference.WeightSyncer
}

// New creates a new ArenaServer instance.
func New(logger *zap.Logger, cfg *ServerConfig) *ArenaServer {
	if cfg == nil {
		cfg = &ServerConfig{}
	}

	metrics := cfg.Metrics
	if metrics == nil {
		metrics = NewMetrics()
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
		logger.Warn("sandbox provider not configured; CreateRollout will fail")
	}

	// Setup proxy default.
	var p *proxy.Proxy
	if cfg.Proxy != nil {
		p = cfg.Proxy
	} else {
		// Create a shared proxy instance; rollouts will register with per-rollout backends.
		var err error
		p, err = proxy.NewProxy("", trajWriter, logger, proxy.WithHTTPTimeout(resolveProxyTimeout(logger, cfg.ProxyTimeout)))
		if err != nil {
			logger.Fatal("failed to create proxy", zap.Error(err))
		}
	}

	p.SetMetrics(metrics)

	// Resolve the weight syncer: explicit override, then BackendType/BackendURL
	// with env fallbacks (ARENA_BACKEND_TYPE / ARENA_BACKEND_URL).
	weightSyncer := cfg.WeightSyncer
	backendType := cfg.BackendType
	if backendType == "" {
		backendType = os.Getenv("ARENA_BACKEND_TYPE")
	}
	backendURL := cfg.BackendURL
	if backendURL == "" {
		backendURL = os.Getenv("ARENA_BACKEND_URL")
	}
	if weightSyncer == nil && backendType != "" {
		ws, err := inference.NewWeightSyncer(backendType, backendURL)
		if err != nil {
			logger.Warn("weight sync disabled", zap.Error(err))
		} else {
			weightSyncer = ws
		}
	}
	p.SetBackendType(backendType)

	return &ArenaServer{
		logger:             logger,
		sandboxProvider:    sbProvider,
		proxy:              p,
		proxyAdvertiseHost: cfg.ProxyAdvertiseHost,
		verifyRunner:       cfg.VerifyRunner,
		syncVerify:         cfg.SyncVerify,
		trajBackend:        trajBackend,
		trajWriter:         trajWriter,
		trajDir:            trajDir,
		metrics:            metrics,
		weightSyncer:       weightSyncer,
		rollouts:           make(map[string]*Rollout),
	}
}

// resolveProxyTimeout returns the configured proxy timeout, falling back to
// the ARENA_PROXY_TIMEOUT env var (e.g. "5m"). Returns 0 when unset, in which
// case the proxy default applies.
func resolveProxyTimeout(logger *zap.Logger, configured time.Duration) time.Duration {
	if configured > 0 {
		return configured
	}
	v := os.Getenv("ARENA_PROXY_TIMEOUT")
	if v == "" {
		return 0
	}
	d, err := time.ParseDuration(v)
	if err != nil || d <= 0 {
		logger.Warn("ignoring invalid ARENA_PROXY_TIMEOUT", zap.String("value", v))
		return 0
	}
	return d
}

// CreateRollout starts a new rollout.
func (s *ArenaServer) CreateRollout(ctx context.Context, req *arena_pb.CreateRolloutRequest) (*arena_pb.CreateRolloutResponse, error) {
	if s.sandboxProvider == nil {
		return nil, fmt.Errorf("sandbox provider not configured")
	}

	s.metrics.Add("arena_rollouts_active", 1)
	rolloutID := uuid.NewString()
	traceID := uuid.NewString()
	token := uuid.NewString()

	s.logger.Info("CreateRollout",
		zap.String("rollout_id", rolloutID),
		zap.String("trace_id", traceID),
		zap.String("task_id", req.TaskId),
		zap.String("image", req.Sandbox.Image),
		zap.String("llm_backend", req.LlmBackend))

	// 1. Start proxy server for this rollout.
	// Listen on all interfaces so sandboxes (e.g. Docker) can reach us.
	ps, err := proxy.NewProxyServerWithHost(s.proxy, s.logger, "0.0.0.0")
	if err != nil {
		return nil, fmt.Errorf("proxy server: %w", err)
	}
	proxyAddr, err := ps.Start()
	if err != nil {
		return nil, fmt.Errorf("proxy start: %w", err)
	}
	_, proxyPort, err := net.SplitHostPort(proxyAddr)
	if err != nil {
		return nil, fmt.Errorf("proxy addr: %w", err)
	}
	advertiseHost := s.proxyAdvertiseHost
	if advertiseHost == "" {
		advertiseHost = "127.0.0.1"
	}

	// 2. Register rollout on the shared proxy.
	sampling := protoToInternalSampling(req.Sampling)
	// If openagora-server runs on the host, it cannot resolve host.docker.internal.
	// Replace with localhost so the proxy can reach the LLM backend.
	llmBackend := req.LlmBackend
	if strings.Contains(llmBackend, "host.docker.internal") {
		llmBackend = strings.ReplaceAll(llmBackend, "host.docker.internal", "localhost")
	}
	s.proxy.RegisterRollout(rolloutID, traceID, token, sampling, llmBackend)

	// 3. Build sandbox config with injected env vars.
	envVars := req.Sandbox.EnvVars
	if envVars == nil {
		envVars = make(map[string]string)
	}
	proxyURLHost := net.JoinHostPort(advertiseHost, proxyPort)
	envVars["OPENAI_BASE_URL"] = fmt.Sprintf("http://%s/v1", proxyURLHost)
	envVars["OPENAI_API_KEY"] = token
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
		Command:  req.Sandbox.Command,
	}

	// 4. Create sandbox.
	sb, err := s.sandboxProvider.Create(ctx, sbConfig)
	if err != nil {
		s.proxy.UnregisterRollout(token)
		_ = ps.Close()
		return nil, fmt.Errorf("sandbox create: %w", err)
	}

	// Update env with real sandbox ID.
	envVars["ARENA_SANDBOX_ID"] = sb.ID

	// 5. Start sandbox.
	if err := s.sandboxProvider.Start(ctx, sb.ID); err != nil {
		s.proxy.UnregisterRollout(token)
		_ = s.sandboxProvider.Destroy(ctx, sb)
		_ = ps.Close()
		return nil, fmt.Errorf("sandbox start: %w", err)
	}

	// 6. Record rollout state.
	timeout := sbConfig.Timeout
	if timeout <= 0 {
		timeout = 10 * time.Minute
	}
	proxyURL := fmt.Sprintf("http://%s/v1", net.JoinHostPort(s.proxyAdvertiseHost, proxyPort))
	rollout := &Rollout{
		ID:        rolloutID,
		TraceID:   traceID,
		TaskID:    req.TaskId,
		Status:    "running",
		SandboxID: sb.ID,
		Token:     token,
		ProxyAddr: proxyAddr,
		ProxyURL:  proxyURL,
		Timeout:   timeout,
		CreatedAt: time.Now(),
		stateCh:   make(chan struct{}, 1),
	}
	s.mu.Lock()
	rollout.WeightVersion = s.currentWeightVersion
	s.rollouts[rolloutID] = rollout
	s.mu.Unlock()

	// 7. Background goroutine: wait for completion, verify, update state.
	go s.runLifecycle(rollout, sb, token, ps, req.Verify)

	return &arena_pb.CreateRolloutResponse{RolloutId: rolloutID, ProxyUrl: proxyURL, Token: token}, nil
}

// runLifecycle waits for the sandbox to finish, then completes the rollout.
// Generation completion (terminal status + flushed trajectory) is not gated on
// verification unless SyncVerify is configured; by default verification runs
// asynchronously against the still-running sandbox and its results are filled
// into the rollout record when done.
func (s *ArenaServer) runLifecycle(rollout *Rollout, sb *sandbox.Sandbox, token string, ps *proxy.ProxyServer, verifyCfg *arena_pb.VerifyConfig) {
	start := time.Now()
	// The lifecycle context is cancelled only on timeout or return; paused
	// time does not count against the rollout timeout.
	ctx, cancel := context.WithCancel(context.Background())
	defer func() {
		s.metrics.Add("arena_rollouts_active", -1)
	}()

	waitErrCh := make(chan error, 1)
	go func() {
		waitErrCh <- s.sandboxProvider.WaitForDone(ctx, sb.ID)
	}()

	// Wait for sandbox completion, enforcing the rollout timeout.
	err, timedOut := s.waitForCompletion(ctx, cancel, rollout, start, waitErrCh)
	if err != nil {
		s.logger.Warn("WaitForDone error", zap.String("rollout_id", rollout.ID), zap.Error(err))
	}

	// Generation is complete: stop accepting LLM traffic for this rollout and
	// flush the trajectory so GetTrajectory observes all steps immediately.
	s.proxy.UnregisterRollout(token)
	_ = ps.Close()
	if f, ok := s.trajBackend.(backend.Finalizer); ok {
		if ferr := f.Finalize(context.Background(), rollout.ID); ferr != nil {
			s.logger.Warn("trajectory finalize failed", zap.String("rollout_id", rollout.ID), zap.Error(ferr))
		}
	}

	if s.syncVerify {
		defer cancel()
		report := s.runVerify(ctx, rollout, sb, verifyCfg)
		s.stopSandbox(sb)
		s.applyVerification(rollout, report)
		s.markTerminal(rollout, start, timedOut, err)
		return
	}

	// Async verification: mark the rollout terminal now so the trainer can
	// consume it; verify results are attached when verification finishes.
	s.markTerminal(rollout, start, timedOut, err)
	if verifyCfg == nil || s.verifyRunner == nil {
		defer cancel()
		s.stopSandbox(sb)
		s.applyVerification(rollout, nil)
		return
	}
	go func() {
		defer cancel()
		report := s.runVerify(ctx, rollout, sb, verifyCfg)
		s.stopSandbox(sb)
		s.applyVerification(rollout, report)
	}()
}

// waitForCompletion blocks until the sandbox finishes or the rollout timeout
// expires. The timeout clock is suspended while the rollout is paused: a
// frozen sandbox neither exits nor writes its done marker, so WaitForDone
// (docker wait / done-file stat) simply blocks during the freeze, which is
// fine — only the deadline accounting needs to exclude paused time.
// Returns the WaitForDone error and whether the wait ended on timeout.
func (s *ArenaServer) waitForCompletion(ctx context.Context, cancel context.CancelFunc, rollout *Rollout, start time.Time, waitErrCh <-chan error) (error, bool) {
	for {
		s.mu.RLock()
		status := rollout.Status
		pausedTotal := rollout.PausedTotal
		stateCh := rollout.stateCh
		s.mu.RUnlock()

		if status == "paused" {
			// Timeout suspended; wait for resume (stateCh) or completion.
			select {
			case err := <-waitErrCh:
				return err, false
			case <-stateCh:
				continue
			}
		}

		elapsed := time.Since(start) - pausedTotal
		remaining := rollout.Timeout - elapsed
		if remaining <= 0 {
			cancel()
			return <-waitErrCh, true
		}
		timer := time.NewTimer(remaining)
		select {
		case err := <-waitErrCh:
			timer.Stop()
			return err, false
		case <-timer.C:
			cancel()
			return <-waitErrCh, true
		case <-stateCh:
			// Pause/resume changed the accounting; recompute.
			timer.Stop()
			continue
		}
	}
}

// signalState notifies the lifecycle goroutine of a pause/resume transition.
func signalState(ch chan struct{}) {
	select {
	case ch <- struct{}{}:
	default:
	}
}

// runVerify executes verification against the still-running sandbox.
// Returns nil when no verification is configured.
func (s *ArenaServer) runVerify(ctx context.Context, rollout *Rollout, sb *sandbox.Sandbox, verifyCfg *arena_pb.VerifyConfig) *verify.VerificationReport {
	if verifyCfg == nil || s.verifyRunner == nil {
		return nil
	}
	verifyStart := time.Now()
	spec := verify.FromProto(verifyCfg)
	report, verr := s.verifyRunner.Run(ctx, s.sandboxProvider, spec, sb.ID)
	verifyResult := "success"
	if verr != nil {
		verifyResult = "error"
		s.logger.Warn("verification failed",
			zap.String("rollout_id", rollout.ID),
			zap.Error(verr))
	}
	if report != nil {
		if report.TotalReward == 0 && len(report.Rewards) > 0 {
			report.TotalReward = verify.TotalReward(report.Rewards)
		}
	}
	s.metrics.Observe("arena_verify_duration_seconds", since(verifyStart))
	s.metrics.Inc("arena_verify_total", 1, verifyResult)
	return report
}

// stopSandbox stops and destroys the sandbox (idempotent). Uses a background
// context so cleanup still runs after the rollout timeout has expired.
func (s *ArenaServer) stopSandbox(sb *sandbox.Sandbox) {
	_ = s.sandboxProvider.Stop(context.Background(), sb.ID)
	_ = s.sandboxProvider.Destroy(context.Background(), sb)
}

// applyVerification attaches verification results to the rollout record.
func (s *ArenaServer) applyVerification(rollout *Rollout, report *verify.VerificationReport) {
	s.mu.Lock()
	if r, ok := s.rollouts[rollout.ID]; ok {
		r.VerificationReport = report
		if report != nil {
			r.Reward = report.TotalReward
		}
	}
	s.mu.Unlock()

	reward := 0.0
	rewardDims := 0
	if report != nil {
		reward = report.TotalReward
		rewardDims = len(report.Rewards)
	}
	s.metrics.Observe("arena_rollout_reward", reward)
	if report != nil {
		s.logger.Info("rollout verification finished",
			zap.String("rollout_id", rollout.ID),
			zap.Float64("reward", reward),
			zap.Int("reward_dimensions", rewardDims))
	}
}

// markTerminal sets the rollout's final status and records completion metrics.
func (s *ArenaServer) markTerminal(rollout *Rollout, start time.Time, timedOut bool, waitErr error) {
	now := time.Now()
	s.mu.Lock()
	status := "success"
	if r, ok := s.rollouts[rollout.ID]; ok {
		r.FinishedAt = &now
		switch {
		case timedOut:
			r.Status = "failed"
		case waitErr != nil:
			r.Status = "failed"
		default:
			r.Status = "success"
		}
		status = r.Status
	}
	s.mu.Unlock()

	s.metrics.Inc("arena_rollouts_total", 1, status)
	s.metrics.Observe("arena_rollout_duration_seconds", since(start))
	s.logger.Info("rollout finished",
		zap.String("rollout_id", rollout.ID),
		zap.String("status", status))
}

// GetRollout returns the status of a rollout.
func (s *ArenaServer) GetRollout(ctx context.Context, req *arena_pb.GetRolloutRequest) (*arena_pb.Rollout, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	r, ok := s.rollouts[req.RolloutId]
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

// PauseRollout freezes a running rollout's sandbox (partial rollout).
// The rollout timeout is suspended while paused and the per-rollout proxy
// listener stays alive, so ResumeRollout needs no re-registration.
func (s *ArenaServer) PauseRollout(ctx context.Context, req *arena_pb.PauseRolloutRequest) (*arena_pb.PauseRolloutResponse, error) {
	if req.Mode != "" && req.Mode != "freeze" {
		return nil, status.Errorf(codes.InvalidArgument, "unknown pause mode %q (supported: \"freeze\")", req.Mode)
	}
	pauser, ok := s.sandboxProvider.(sandbox.Pauser)
	if !ok {
		return nil, status.Errorf(codes.Unimplemented, "sandbox provider %T does not support pause/resume", s.sandboxProvider)
	}

	s.mu.Lock()
	r, ok := s.rollouts[req.RolloutId]
	if !ok {
		s.mu.Unlock()
		return nil, status.Errorf(codes.NotFound, "rollout not found: %s", req.RolloutId)
	}
	if r.Status != "running" {
		s.mu.Unlock()
		return nil, status.Errorf(codes.FailedPrecondition, "rollout %s is %s; only running rollouts can be paused", req.RolloutId, r.Status)
	}
	r.Status = "paused"
	r.PausedAt = time.Now()
	s.mu.Unlock()
	signalState(r.stateCh)

	if err := pauser.Pause(ctx, r.SandboxID); err != nil {
		// Roll back the transition so the rollout keeps running.
		s.mu.Lock()
		r.Status = "running"
		r.PausedAt = time.Time{}
		s.mu.Unlock()
		signalState(r.stateCh)
		return nil, status.Errorf(codes.Internal, "pause sandbox: %v", err)
	}

	// Flush buffered trajectory steps so the pause boundary is durable, but
	// keep the writer open: generation continues after resume.
	if f, ok := s.trajBackend.(backend.Flusher); ok {
		if ferr := f.Flush(context.Background(), r.ID); ferr != nil {
			s.logger.Warn("trajectory flush on pause failed", zap.String("rollout_id", r.ID), zap.Error(ferr))
		}
	}
	s.logger.Info("rollout paused", zap.String("rollout_id", r.ID))
	return &arena_pb.PauseRolloutResponse{}, nil
}

// ResumeRollout unfreezes a paused rollout and restores its timeout
// accounting. The proxy listener was kept alive during the pause, so the
// returned proxy URL and token are unchanged.
func (s *ArenaServer) ResumeRollout(ctx context.Context, req *arena_pb.ResumeRolloutRequest) (*arena_pb.ResumeRolloutResponse, error) {
	pauser, ok := s.sandboxProvider.(sandbox.Pauser)
	if !ok {
		return nil, status.Errorf(codes.Unimplemented, "sandbox provider %T does not support pause/resume", s.sandboxProvider)
	}

	s.mu.RLock()
	r, ok := s.rollouts[req.RolloutId]
	s.mu.RUnlock()
	if !ok {
		return nil, status.Errorf(codes.NotFound, "rollout not found: %s", req.RolloutId)
	}

	s.mu.Lock()
	if r.Status != "paused" {
		s.mu.Unlock()
		return nil, status.Errorf(codes.FailedPrecondition, "rollout %s is %s; only paused rollouts can be resumed", req.RolloutId, r.Status)
	}
	s.mu.Unlock()

	if err := pauser.Unpause(ctx, r.SandboxID); err != nil {
		return nil, status.Errorf(codes.Internal, "unpause sandbox: %v", err)
	}

	s.mu.Lock()
	r.PausedTotal += time.Since(r.PausedAt)
	r.PausedAt = time.Time{}
	r.Status = "running"
	s.mu.Unlock()
	signalState(r.stateCh)

	s.logger.Info("rollout resumed", zap.String("rollout_id", r.ID))
	return &arena_pb.ResumeRolloutResponse{ProxyUrl: r.ProxyURL, Token: r.Token}, nil
}

// UpdateWeights refits the shared inference backend with newly trained
// weights: generation is paused, the backend reloads from the trainer's
// checkpoint directory, and generation continues. Concurrent calls are
// serialized. On success the version is recorded and stamped onto new
// rollouts at CreateRollout time.
func (s *ArenaServer) UpdateWeights(ctx context.Context, req *arena_pb.UpdateWeightsRequest) (*arena_pb.UpdateWeightsResponse, error) {
	if s.weightSyncer == nil {
		return nil, status.Error(codes.FailedPrecondition,
			"no weight syncer configured: set ServerConfig.BackendType/BackendURL or ARENA_BACKEND_TYPE/ARENA_BACKEND_URL")
	}
	if req.ModelPath == "" {
		return nil, status.Error(codes.InvalidArgument, "model_path is required")
	}

	s.weightMu.Lock()
	defer s.weightMu.Unlock()

	if err := s.weightSyncer.PauseGeneration(ctx, ""); err != nil {
		return nil, status.Errorf(codes.Internal, "pause generation: %v", err)
	}
	updateErr := s.weightSyncer.UpdateWeightsFromDisk(ctx, req.ModelPath, req.WeightVersion, req.AbortInFlight)
	// Always resume generation, even after a failed refit, so the backend is
	// not left paused.
	if cerr := s.weightSyncer.ContinueGeneration(ctx); cerr != nil {
		s.logger.Warn("continue generation failed", zap.Error(cerr))
		if updateErr == nil {
			updateErr = fmt.Errorf("continue generation: %w", cerr)
		}
	}
	if updateErr != nil {
		return &arena_pb.UpdateWeightsResponse{Success: false, Message: updateErr.Error()}, nil
	}

	s.mu.Lock()
	s.currentWeightVersion = req.WeightVersion
	s.mu.Unlock()
	s.logger.Info("weights updated", zap.String("weight_version", req.WeightVersion), zap.String("model_path", req.ModelPath))
	return &arena_pb.UpdateWeightsResponse{Success: true, WeightVersion: req.WeightVersion}, nil
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
		RolloutId:          r.ID,
		TaskId:             r.TaskID,
		Status:             r.Status,
		CreatedAt:          timestamppb.New(r.CreatedAt),
		Reward:             float32(r.Reward),
		VerificationReport: r.VerificationReport.ToProto(),
		WeightVersion:      r.WeightVersion,
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
			ChoicesJson:        step.Response.Choices,
			LogprobsJson:       step.Response.Logprobs,
			PromptTokenIds:     step.Response.PromptTokenIDs,
			CompletionTokenIds: step.Response.CompletionTokenIDs,
			WeightVersion:      step.Response.WeightVersion,
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
