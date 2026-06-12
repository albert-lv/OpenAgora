from typing import List, Dict, Any, Optional, AsyncIterator
import asyncio
import concurrent.futures

from openagora_sdk.client import ArenaClient


class ArenaRolloutProvider:
    """
    veRL-compatible rollout provider backed by Arena.

    Supports both synchronous blocking generation and async streaming
    generation for integration with veRL training loops.

    Usage (sync)::

        provider = ArenaRolloutProvider(
            arena_endpoint="localhost:9090",
            sandbox_image="openhands:latest",
            llm_backend="http://localhost:8000/v1",
            verify_command="pytest -k regression",
            max_concurrent=64,
        )
        trajectories = provider.generate(prompts=batch_of_tasks)

    Usage (async stream)::

        async for result in provider.generate_async(prompts=batch_of_tasks):
            print(f"Sample {result['index']}: reward={result['reward']}")
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
        """Generate trajectories for a batch of prompts (blocking).

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

    async def generate_async(
        self,
        prompts: List[str],
        sampling: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Async stream of rollout results as they complete.

        Yields each result immediately when its rollout finishes, allowing
        the caller to process partial results while others are still running.
        This is useful for online RL loops that want to start training on
        early-completing rollouts without waiting for the entire batch.
        """
        cfg = sampling if sampling is not None else self.sampling
        loop = asyncio.get_running_loop()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = [
                loop.run_in_executor(executor, self._run_one, i, prompt, cfg)
                for i, prompt in enumerate(prompts)
            ]
            for coro in asyncio.as_completed(futures):
                try:
                    result = await coro
                except Exception as exc:
                    result = {
                        "error": str(exc),
                        "trajectory": [],
                        "reward": 0.0,
                    }
                yield result

    def _run_one(self, index: int, prompt: str, sampling: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single rollout and return its trajectory + reward."""
        task_id = f"batch-{index}"
        verify = {"command": self.verify_command} if self.verify_command else None

        rollout = self.client.create_rollout(
            task_id=task_id,
            image=self.sandbox_image,
            llm_backend=self.llm_backend,
            sampling=sampling,
            verify=verify,
            task_file=prompt.encode("utf-8"),
        )
        rollout_id = rollout["rollout_id"]

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
