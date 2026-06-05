package main

import (
	"context"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"github.com/albert-lv/agent-arena/go/pkg/server"
	"go.uber.org/zap"
	"google.golang.org/grpc"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	s := grpc.NewServer()
	arena_pb.RegisterArenaServiceServer(s, server.New(logger))

	lis, err := net.Listen("tcp", ":9090")
	if err != nil {
		logger.Fatal("failed to listen", zap.Error(err))
	}

	go func() {
		if err := s.Serve(lis); err != nil {
			logger.Fatal("server error", zap.Error(err))
		}
	}()

	logger.Info("arena-server started", zap.String("addr", lis.Addr().String()))

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down...")
	s.GracefulStop()
}
