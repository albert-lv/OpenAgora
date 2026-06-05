import grpc
from typing import Iterator, Optional
from pydantic import BaseModel

# Generated protobuf imports (assumed to exist after make proto)
# import arena.v1.arena_pb2 as arena_pb
# import arena.v1.arena_pb2_grpc as arena_grpc

class ArenaClient:
    """Python client for Arena gRPC server."""

    def __init__(self, endpoint: str = "localhost:9090"):
        self.endpoint = endpoint
        self.channel = grpc.insecure_channel(endpoint)
        # self.stub = arena_grpc.ArenaServiceStub(self.channel)

    def create_rollout(
        self,
        task_id: str,
        image: str,
        llm_backend: str,
        sampling: Optional[dict] = None,
        verify: Optional[dict] = None,
    ):
        """Create a new rollout."""
        raise NotImplementedError("proto stubs not yet generated")

    def wait(self, rollout_id: str):
        """Wait for a rollout to complete and return result."""
        raise NotImplementedError()

    def stream_trajectory(self, rollout_id: str) -> Iterator[dict]:
        """Stream trajectory steps in real-time."""
        raise NotImplementedError()
