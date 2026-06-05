package server

import (
	"context"
	"fmt"

	arena_pb "github.com/albert-lv/agent-arena/go/proto/arena/v1"
	"go.uber.org/zap"
)

// ArenaServer implements the ArenaService gRPC server.
type ArenaServer struct {
	arena_pb.UnimplementedArenaServiceServer
	logger *zap.Logger
}

// New creates a new ArenaServer instance.
func New(logger *zap.Logger) *ArenaServer {
	return &ArenaServer{logger: logger}
}

// CreateRollout starts a new rollout.
func (s *ArenaServer) CreateRollout(ctx context.Context, req *arena_pb.CreateRolloutRequest) (*arena_pb.CreateRolloutResponse, error) {
	s.logger.Info("CreateRollout", zap.String("task_id", req.TaskId))
	return &arena_pb.CreateRolloutResponse{RolloutId: "not-implemented"}, nil
}

// GetRollout returns the status of a rollout.
func (s *ArenaServer) GetRollout(ctx context.Context, req *arena_pb.GetRolloutRequest) (*arena_pb.Rollout, error) {
	return nil, fmt.Errorf("not yet implemented")
}

// StopRollout stops a running rollout.
func (s *ArenaServer) StopRollout(ctx context.Context, req *arena_pb.StopRolloutRequest) (*arena_pb.StopRolloutResponse, error) {
	return nil, fmt.Errorf("not yet implemented")
}

// ListRollouts lists all rollouts.
func (s *ArenaServer) ListRollouts(ctx context.Context, req *arena_pb.ListRolloutsRequest) (*arena_pb.ListRolloutsResponse, error) {
	return nil, fmt.Errorf("not yet implemented")
}

// StreamTrajectory streams trajectory steps in real-time.
func (s *ArenaServer) StreamTrajectory(req *arena_pb.StreamTrajectoryRequest, stream arena_pb.ArenaService_StreamTrajectoryServer) error {
	return fmt.Errorf("not yet implemented")
}

// GetTrajectory returns the full trajectory for a completed rollout.
func (s *ArenaServer) GetTrajectory(ctx context.Context, req *arena_pb.GetTrajectoryRequest) (*arena_pb.Trajectory, error) {
	return nil, fmt.Errorf("not yet implemented")
}
