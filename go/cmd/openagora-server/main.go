package main

import (
	"context"
	"flag"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/daytona"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/docker"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/e2b"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/local"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/mock"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/modal"
	_ "github.com/albert-lv/OpenAgora/go/pkg/sandbox/rock"
	"github.com/albert-lv/OpenAgora/go/pkg/server"
	"github.com/albert-lv/OpenAgora/go/pkg/verify"
	arena_pb "github.com/albert-lv/OpenAgora/go/proto/openagora/v1"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

// verifyResolverRunner uses the verify package registry to select and run
// the appropriate verifier (legacy single-command, pytest, unittest, SWE-bench).
type verifyResolverRunner struct {
	logger *zap.Logger
}

func (r *verifyResolverRunner) Run(ctx context.Context, provider sandbox.Provider, spec *verify.VerificationSpec, sandboxID string) (*verify.VerificationReport, error) {
	if r.logger != nil {
		r.logger.Info("verify run",
			zap.String("sandbox_id", sandboxID),
			zap.String("command", spec.Command),
			zap.String("framework", spec.Framework))
	}
	verifier, err := verify.Resolve(spec)
	if err != nil {
		return nil, err
	}
	return verifier.Run(ctx, provider, spec, sandboxID)
}

func main() {
	logger, _ := zap.NewProduction()
	defer func() { _ = logger.Sync() }()

	var (
		sandboxMode = flag.String("sandbox", "docker", "Sandbox provider: docker, local, mock, e2b, modal, daytona, or rock")
		grpcAddr    = flag.String("grpc", ":9090", "gRPC listen address")
		httpAddr    = flag.String("http", ":9091", "HTTP dashboard listen address")
	)
	flag.Parse()

	factory := sandbox.DefaultProviderFactory()
	sbProvider, err := factory.Create(*sandboxMode, nil)
	if err != nil {
		logger.Fatal("unknown sandbox provider", zap.String("provider", *sandboxMode), zap.Error(err))
	}

	verifyRunner := &verifyResolverRunner{logger: logger}

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
