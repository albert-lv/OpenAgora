package main

import (
	"context"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"syscall"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox/docker"
	"github.com/albert-lv/agent-arena/go/pkg/server"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

// simpleVerifyRunner runs commands via docker exec.
type simpleVerifyRunner struct {
	logger *zap.Logger
}

func (r *simpleVerifyRunner) Run(ctx context.Context, sandboxID string, command string) ([]float64, error) {
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

func main() {
	logger, _ := zap.NewProduction()
	defer func() { _ = logger.Sync() }()

	sbProvider := docker.NewProvider()
	cfg := &server.ServerConfig{
		SandboxProvider:    sbProvider,
		VerifyRunner:       &simpleVerifyRunner{logger: logger},
		ProxyAdvertiseHost: "host.docker.internal",
	}

	arenaServer := server.New(logger, cfg)
	s := grpc.NewServer()
	arena_pb.RegisterArenaServiceServer(s, arenaServer)

	lis, err := net.Listen("tcp", ":9090")
	if err != nil {
		logger.Fatal("failed to listen", zap.Error(err))
	}

	go func() {
		if err := s.Serve(lis); err != nil {
			logger.Fatal("server error", zap.Error(err))
		}
	}()

	// Start HTTP dashboard server.
	httpLis, err := net.Listen("tcp", ":9091")
	if err != nil {
		logger.Fatal("failed to listen http", zap.Error(err))
	}
	go func() {
		if err := http.Serve(httpLis, arenaServer.DashboardHandler()); err != nil {
			logger.Fatal("http server error", zap.Error(err))
		}
	}()

	logger.Info("arena-server started", zap.String("grpc_addr", lis.Addr().String()), zap.String("http_addr", httpLis.Addr().String()))

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down...")
	s.GracefulStop()
}
