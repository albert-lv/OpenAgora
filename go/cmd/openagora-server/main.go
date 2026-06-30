package main

import (
	"context"
	"flag"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"syscall"

	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
	"github.com/albert-lv/OpenAgora/go/pkg/sandbox/docker"
	"github.com/albert-lv/OpenAgora/go/pkg/sandbox/local"
	"github.com/albert-lv/OpenAgora/go/pkg/server"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

// dockerVerifyRunner runs verification commands via docker exec.
type dockerVerifyRunner struct {
	logger *zap.Logger
}

func (r *dockerVerifyRunner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	cmd := exec.CommandContext(ctx, "docker", append([]string{"exec", sandboxID, "sh", "-c", command}, []string{}...)...)
	out, err := cmd.CombinedOutput()
	if r.logger != nil {
		r.logger.Info("verify exec",
			zap.String("sandbox_id", sandboxID),
			zap.String("command", command),
			zap.String("output", string(out)),
			zap.Error(err))
	}
	if err != nil {
		return []float64{0.0}, nil
	}
	return []float64{1.0}, nil
}

// localVerifyRunner runs verification commands directly in the sandbox directory.
type localVerifyRunner struct {
	logger *zap.Logger
}

func (r *localVerifyRunner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
	cmd := exec.CommandContext(ctx, "sh", "-c", command)
	cmd.Dir = sandboxID
	cmd.Env = os.Environ()
	cmd.Env = append(cmd.Env, "SANDBOX_DIR="+sandboxID, "ARENA_SANDBOX_DIR="+sandboxID)
	out, err := cmd.CombinedOutput()
	if r.logger != nil {
		r.logger.Info("verify exec",
			zap.String("sandbox_id", sandboxID),
			zap.String("command", command),
			zap.String("output", string(out)),
			zap.Error(err))
	}
	if err != nil {
		return []float64{0.0}, nil
	}
	return []float64{1.0}, nil
}

func main() {
	logger, _ := zap.NewProduction()
	defer func() { _ = logger.Sync() }()

	var (
		sandboxMode = flag.String("sandbox", "docker", "Sandbox provider: docker or local")
		grpcAddr    = flag.String("grpc", ":9090", "gRPC listen address")
		httpAddr    = flag.String("http", ":9091", "HTTP dashboard listen address")
	)
	flag.Parse()

	var sbProvider sandbox.Provider
	var verifyRunner server.VerifyRunner
	switch *sandboxMode {
	case "local":
		sbProvider = local.NewProvider()
		verifyRunner = &localVerifyRunner{logger: logger}
		logger.Info("using local sandbox provider")
	default:
		sbProvider = docker.NewProvider()
		verifyRunner = &dockerVerifyRunner{logger: logger}
		logger.Info("using docker sandbox provider")
	}

	advertiseHost := os.Getenv("ARENA_PROXY_ADVERTISE_HOST")
	if advertiseHost == "" {
		if *sandboxMode == "local" {
			advertiseHost = "localhost"
		} else {
			advertiseHost = "host.docker.internal"
		}
	}

	cfg := &server.ServerConfig{
		SandboxProvider:    sbProvider,
		VerifyRunner:       verifyRunner,
		ProxyAdvertiseHost: advertiseHost,
	}

	arenaServer := server.New(logger, cfg)
	s := grpc.NewServer()
	arena_pb.RegisterArenaServiceServer(s, arenaServer)

	lis, err := net.Listen("tcp", *grpcAddr)
	if err != nil {
		logger.Fatal("failed to listen", zap.Error(err))
	}

	go func() {
		if err := s.Serve(lis); err != nil {
			logger.Fatal("server error", zap.Error(err))
		}
	}()

	httpLis, err := net.Listen("tcp", *httpAddr)
	if err != nil {
		logger.Fatal("failed to listen http", zap.Error(err))
	}
	go func() {
		if err := http.Serve(httpLis, arenaServer.DashboardHandler()); err != nil {
			logger.Fatal("http server error", zap.Error(err))
		}
	}()

	logger.Info("openagora-server started",
		zap.String("grpc_addr", lis.Addr().String()),
		zap.String("http_addr", httpLis.Addr().String()),
		zap.String("sandbox_mode", *sandboxMode),
	)

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down...")
	s.GracefulStop()
}
