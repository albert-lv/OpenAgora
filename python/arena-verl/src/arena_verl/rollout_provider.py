from typing import List, Dict, Any, Optional
import concurrent.futures

from arena_sdk.client import ArenaClient


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
        sampling: Optional[Dict[str, Any]] = None,
    ):
        self.client = ArenaClient(arena_endpoint)
        self.sandbox_image = sandbox_image
        self.llm_backend = llm_backend
        self.verify_command = verify_command
        self.max_concurrent = max_concurrent
        self.sampling = sampling or {}

    def generate(self, prompts: List[str], sampling: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Generate trajectories for a batch of prompts.

        Each prompt becomes a separate Arena rollout. The method blocks until
        all rollouts complete and returns their trajectories + rewards.
        """
        cfg = sampling if sampling is not None else self.sampling
        results: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = {
                executor.submit(self._run_one, i, prompt, cfg): i
                for i, prompt in enumerate(prompts)
            }
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    results.append({"index": idx, **result})
                except Exception as exc:
                    results.append({
                        "index": idx,
                        "error": str(exc),
                        "trajectory": [],
                        "reward": 0.0,
                    })

        # Sort by original index.
        results.sort(key=lambda x: x["index"])
        return results

    def _run_one(self, index: int, prompt: str, sampling: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single rollout and return its trajectory + reward."""
        task_id = f"batch-{index}"
        verify = {"command": self.verify_command} if self.verify_command else None

        rollout_id = self.client.create_rollout(
            task_id=task_id,
            image=self.sandbox_image,
            llm_backend=self.llm_backend,
            sampling=sampling,
            verify=verify,
            task_file=prompt.encode("utf-8"),
        )

        # Wait for completion.
        info = self.client.wait(rollout_id)

        # Fetch trajectory.
        trajectory = self.client.get_trajectory(rollout_id)

        return {
            "rollout_id": rollout_id,
            "task_id": task_id,
            "status": info["status"],
            "reward": info["reward"],
            "trajectory": trajectory,
        }

    def close(self) -> None:
        """Close the underlying Arena client."""
        self.client.close()
