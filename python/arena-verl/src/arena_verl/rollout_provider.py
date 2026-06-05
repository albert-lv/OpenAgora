from typing import List, Dict, Any

class ArenaRolloutProvider:
    """
    veRL-compatible rollout provider backed by Arena.

    Usage:
        provider = ArenaRolloutProvider(
            arena_endpoint="localhost:9090",
            sandbox_image="openhands:latest",
            llm_backend="http://localhost:8000/v1",
            verify_command="pytest -k regression",
            max_concurrent=64,
        )
        trajectories = provider.generate(prompts=batch_of_tasks)
    """

    def __init__(
        self,
        arena_endpoint: str,
        sandbox_image: str,
        llm_backend: str,
        verify_command: str,
        max_concurrent: int = 64,
    ):
        self.arena_endpoint = arena_endpoint
        self.sandbox_image = sandbox_image
        self.llm_backend = llm_backend
        self.verify_command = verify_command
        self.max_concurrent = max_concurrent

    def generate(self, prompts: List[str], sampling: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Generate trajectories for a batch of prompts."""
        raise NotImplementedError("Arena integration not yet wired")
