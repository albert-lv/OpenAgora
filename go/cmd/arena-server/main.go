package main

import (
	"flag"
	"net"
	"os"
	"os/signal"
	"syscall"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox/docker"
	"github.com/albert-lv/agent-arena/go/pkg/sandbox/mock"
	"github.com/albert-lv/agent-arena/go/pkg/server"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

func main() {
	logger, _ := zap.NewProduction()
	defer func() { _ = logger.Sync() }()

	var sandboxType string
	flag.StringVar(&sandboxType, "sandbox", "docker", "sandbox provider: docker | mock")
	flag.Parse()

	var cfg *server.ServerConfig
	switch sandboxType {
	case "docker":
		cfg = &server.ServerConfig{SandboxProvider: docker.NewProvider()}
	case "mock":
		cfg = &server.ServerConfig{SandboxProvider: mock.NewProvider()}
	default:
		logger.Fatal("unknown sandbox provider", zap.String("sandbox", sandboxType))
	}

	s := grpc.NewServer()
	arena_pb.RegisterArenaServiceServer(s, server.New(logger, cfg))

	lis, err := net.Listen("tcp", ":9090")
	if err != nil {
		logger.Fatal("failed to listen", zap.Error(err))
	}

	go func() {
		if err := s.Serve(lis); err != nil {
			logger.Fatal("server error", zap.Error(err))
		}
	}()

	logger.Info("arena-server started", zap.String("addr", lis.Addr().String()), zap.String("sandbox", sandboxType))

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down...")
	s.GracefulStop()
}
