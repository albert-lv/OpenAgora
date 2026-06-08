import json
import grpc
import time
from typing import Any, Iterator, Optional

from arena.v1 import arena_pb2 as arena_pb
from arena.v1 import arena_pb2_grpc as arena_grpc


class ArenaClient:
    """Python client for Arena gRPC server."""

    def __init__(self, endpoint: str = "localhost:9090"):
        self.endpoint = endpoint
        self.channel = grpc.insecure_channel(endpoint)
        self.stub = arena_grpc.ArenaServiceStub(self.channel)

    def create_rollout(
        self,
        task_id: str,
        image: str,
        llm_backend: str,
        sampling: Optional[dict] = None,
        verify: Optional[dict] = None,
        memory: str = "8g",
        cpus: float = 2.0,
        timeout_seconds: int = 3600,
        env_vars: Optional[dict] = None,
        task_file: Optional[bytes] = None,
    ) -> str:
        """Create a new rollout and return the rollout ID."""
        sandbox_cfg = arena_pb.SandboxConfig(
            image=image,
            memory=memory,
            cpus=cpus,
            timeout_seconds=timeout_seconds,
            env_vars=env_vars or {},
        )
        if task_file is not None:
            sandbox_cfg.task_file = task_file

        sampling_cfg = None
        if sampling is not None:
            sampling_cfg = arena_pb.SamplingConfig(
                temperature=sampling.get("temperature", 0.7),
                top_p=sampling.get("top_p", 0.95),
                seed=sampling.get("seed", 0),
                max_tokens_budget=sampling.get("max_tokens_budget", 0),
            )

        verify_cfg = None
        if verify is not None:
            verify_cfg = arena_pb.VerifyConfig(
                command=verify.get("command", ""),
                log_parser=verify.get("log_parser", ""),
                pass_to_pass=verify.get("pass_to_pass", []),
                fail_to_pass=verify.get("fail_to_pass", []),
            )

        req = arena_pb.CreateRolloutRequest(
            task_id=task_id,
            sandbox=sandbox_cfg,
            sampling=sampling_cfg,
            verify=verify_cfg,
            llm_backend=llm_backend,
        )
        resp = self.stub.CreateRollout(req)
        return {
            "rollout_id": resp.rollout_id,
            "proxy_url": resp.proxy_url,
            "token": resp.token,
        }

    def get_rollout(self, rollout_id: str) -> dict:
        """Get the current status of a rollout."""
        req = arena_pb.GetRolloutRequest(rollout_id=rollout_id)
        r = self.stub.GetRollout(req)
        return {
            "rollout_id": r.rollout_id,
            "task_id": r.task_id,
            "status": r.status,
            "reward": r.reward,
        }

    def wait(self, rollout_id: str, poll_interval: float = 1.0, timeout: float = 3600.0) -> dict:
        """Wait for a rollout to complete and return result."""
        start = time.time()
        while True:
            info = self.get_rollout(rollout_id)
            if info["status"] in ("success", "failed", "stopped"):
                return info
            if time.time() - start > timeout:
                raise TimeoutError(f"rollout {rollout_id} did not complete within {timeout}s")
            time.sleep(poll_interval)

    def stream_trajectory(self, rollout_id: str) -> Iterator[dict]:
        """Stream trajectory steps in real-time."""
        req = arena_pb.StreamTrajectoryRequest(rollout_id=rollout_id)
        for step in self.stub.StreamTrajectory(req):
            yield {
                "rollout_id": step.rollout_id,
                "step_id": step.step_id,
                "request": {
                    "endpoint": step.request.endpoint if step.request else None,
                    "model": step.request.model if step.request else None,
                },
                "response": {
                    "usage": {
                        "prompt_tokens": step.response.usage.prompt_tokens if step.response and step.response.usage else 0,
                        "completion_tokens": step.response.usage.completion_tokens if step.response and step.response.usage else 0,
                    }
                } if step.response else None,
                "metadata": dict(step.metadata),
            }

    def get_trajectory(self, rollout_id: str) -> list[dict]:
        """Get the full trajectory for a completed rollout.

        Returns a list of steps, each containing:
            - rollout_id, step_id
            - request: {endpoint, model, messages}
            - response: {content, usage, logprobs}
            - metadata
        """
        req = arena_pb.GetTrajectoryRequest(rollout_id=rollout_id)
        resp = self.stub.GetTrajectory(req)
        steps = []
        for step in resp.steps:
            step_data = {
                "rollout_id": step.rollout_id,
                "step_id": step.step_id,
                "request": {
                    "endpoint": step.request.endpoint if step.request else None,
                    "model": step.request.model if step.request else None,
                    "messages": self._safe_json_load(step.request.messages) if step.request and step.request.messages else None,
                },
                "response": {
                    "content": self._extract_content(step.response.choices) if step.response else None,
                    "usage": {
                        "prompt_tokens": step.response.usage.prompt_tokens if step.response and step.response.usage else 0,
                        "completion_tokens": step.response.usage.completion_tokens if step.response and step.response.usage else 0,
                    },
                    "logprobs": self._safe_json_load(step.response.logprobs) if step.response and step.response.logprobs else None,
                } if step.response else None,
                "metadata": dict(step.metadata),
            }
            steps.append(step_data)
        return steps

    def _safe_json_load(self, data: bytes) -> Any:
        """Safely load JSON bytes; return None on failure."""
        try:
            return json.loads(data)
        except Exception:
            return None

    def _extract_content(self, choices_bytes: bytes) -> Optional[str]:
        """Extract assistant content from raw choices JSON."""
        if not choices_bytes:
            return None
        try:
            choices = json.loads(choices_bytes)
            if choices and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict):
                    msg = choice.get("message", {})
                    return msg.get("content")
        except Exception:
            pass
        return None

    def list_rollouts(self) -> list[dict]:
        """List all rollouts."""
        req = arena_pb.ListRolloutsRequest()
        resp = self.stub.ListRollouts(req)
        return [
            {
                "rollout_id": r.rollout_id,
                "task_id": r.task_id,
                "status": r.status,
                "reward": r.reward,
            }
            for r in resp.rollouts
        ]

    def stop_rollout(self, rollout_id: str) -> None:
        """Stop a running rollout."""
        req = arena_pb.StopRolloutRequest(rollout_id=rollout_id)
        self.stub.StopRollout(req)

    def close(self) -> None:
        """Close the gRPC channel."""
        self.channel.close()
