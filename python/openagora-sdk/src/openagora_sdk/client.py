import asyncio
import grpc
import random
import time
from typing import Iterator, Optional

from openagora.v1 import arena_pb2 as arena_pb
from openagora.v1 import arena_pb2_grpc as arena_grpc
from openagora.v1 import trajectory_pb2 as traj_pb


def _verification_report_to_dict(report) -> Optional[dict]:
    """Convert a VerificationReport protobuf message to a plain dict.

    Returns ``None`` if the report is empty (no stdout/stderr and no test cases).
    """
    if report is None:
        return None
    # In proto3 an unset message field returns a default instance. Treat it as
    # missing when there is no meaningful content.
    if (
        not report.stdout
        and not report.stderr
        and not list(report.test_cases)
        and not list(report.rewards)
    ):
        return None
    return {
        "reward": report.reward,
        "total_reward": report.total_reward,
        "rewards": [
            {
                "name": rw.name,
                "value": rw.value,
                "weight": rw.weight,
                "source": rw.source,
            }
            for rw in report.rewards
        ],
        "f2p_count": report.f2p_count,
        "p2p_count": report.p2p_count,
        "f2f_count": report.f2f_count,
        "p2f_count": report.p2f_count,
        "stdout": report.stdout,
        "stderr": report.stderr,
        "test_cases": [
            {
                "test_id": tc.test_id,
                "baseline_passed": tc.baseline_passed,
                "patch_passed": tc.patch_passed,
                "category": tc.category,
            }
            for tc in report.test_cases
        ],
    }


class _PollBackoff:
    """Exponential backoff with full jitter for status polling.

    Each call to :meth:`next_delay` returns a random delay in
    ``[0, current]`` and grows ``current`` geometrically up to ``maximum``.
    """

    def __init__(self, initial: float, maximum: float, multiplier: float):
        if initial <= 0:
            raise ValueError("initial interval must be positive")
        if maximum < initial:
            raise ValueError("maximum interval must be >= initial interval")
        if multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0")
        self.initial = initial
        self.maximum = maximum
        self.multiplier = multiplier
        self._current = initial

    def next_delay(self) -> float:
        delay = random.uniform(0.0, self._current)
        self._current = min(self._current * self.multiplier, self.maximum)
        return delay


class ArenaClient:
    """Python client for Arena gRPC server."""

    def __init__(
        self,
        endpoint: str = "localhost:9090",
        default_timeout: float = 30.0,
        create_retries: int = 3,
        poll_initial_interval: float = 0.1,
        poll_max_interval: float = 2.0,
        poll_backoff_multiplier: float = 2.0,
    ):
        self.endpoint = endpoint
        self.default_timeout = default_timeout
        self.create_retries = max(1, create_retries)
        self.poll_initial_interval = poll_initial_interval
        self.poll_max_interval = poll_max_interval
        self.poll_backoff_multiplier = poll_backoff_multiplier
        # Use round_robin to try all resolved addresses (IPv4 + IPv6).
        options = [("grpc.lb_policy_name", "round_robin")]
        self.channel = grpc.insecure_channel(endpoint, options=options)
        self.stub = arena_grpc.ArenaServiceStub(self.channel)

    def _call(self, method, request, timeout: Optional[float | str] = "default"):
        """Call a gRPC method with a bounded timeout.

        Pass ``timeout=None`` explicitly for streaming calls that should not
        have a per-call deadline.
        """
        if timeout == "default":
            timeout = self.default_timeout
        return method(request, timeout=timeout)

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
        command: Optional[list[str]] = None,
    ) -> dict:
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
        if command:
            sandbox_cfg.command.extend(command)

        sampling_cfg = None
        if sampling is not None:
            sampling_cfg = traj_pb.SamplingConfig(
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
                timeout_seconds=verify.get("timeout_seconds", 300),
                language=verify.get("language", ""),
                framework=verify.get("framework", ""),
                install_command=verify.get("install_command", ""),
                baseline_command=verify.get("baseline_command", ""),
                patch_command=verify.get("patch_command", ""),
                working_directory=verify.get("working_directory", ""),
            )
            for rw in verify.get("rewards", []):
                verify_cfg.rewards.append(
                    arena_pb.RewardSpec(
                        name=rw.get("name", ""),
                        weight=rw.get("weight", 1.0),
                        verifier_dir=rw.get("verifier_dir", ""),
                        command=rw.get("command", ""),
                        aggregation=rw.get("aggregation", "mean"),
                    )
                )

        req = arena_pb.CreateRolloutRequest(
            task_id=task_id,
            sandbox=sandbox_cfg,
            sampling=sampling_cfg,
            verify=verify_cfg,
            llm_backend=llm_backend,
        )

        last_err = None
        for attempt in range(1, self.create_retries + 1):
            try:
                resp = self._call(self.stub.CreateRollout, req)
                return {
                    "rollout_id": resp.rollout_id,
                    "proxy_url": resp.proxy_url,
                    "token": resp.token,
                }
            except grpc.RpcError as e:
                last_err = e
                if attempt < self.create_retries:
                    time.sleep(0.5 * attempt)
        raise last_err  # type: ignore[misc]

    def get_rollout(self, rollout_id: str) -> dict:
        """Get the current status of a rollout."""
        req = arena_pb.GetRolloutRequest(rollout_id=rollout_id)
        r = self._call(self.stub.GetRollout, req)
        return {
            "rollout_id": r.rollout_id,
            "task_id": r.task_id,
            "status": r.status,
            "reward": r.reward,
            "weight_version": r.weight_version,
            "verification_report": _verification_report_to_dict(r.verification_report),
        }

    def _poll_backoff(self) -> _PollBackoff:
        return _PollBackoff(
            initial=self.poll_initial_interval,
            maximum=self.poll_max_interval,
            multiplier=self.poll_backoff_multiplier,
        )

    def wait(
        self,
        rollout_id: str,
        poll_interval: Optional[float] = None,
        timeout: float = 3600.0,
        return_on_pause: bool = False,
    ) -> dict:
        """Wait for a rollout to complete and return result.

        By default the rollout status is polled with exponential backoff
        (full jitter) from ``poll_initial_interval`` up to
        ``poll_max_interval``. Pass an explicit ``poll_interval`` to use a
        fixed sleep between polls instead (legacy behavior).

        ``paused`` is not a terminal status: with the default
        ``return_on_pause=False`` a paused rollout keeps polling until it
        resumes and finishes or ``timeout`` fires. Pass
        ``return_on_pause=True`` to treat ``paused`` like a terminal state
        and return the rollout dict as soon as it is observed. Trainers that
        pause stragglers for partial rollout should either use
        ``return_on_pause=True`` here or track paused rollout IDs themselves
        and resume them with :meth:`resume_rollout`.
        """
        start = time.time()
        backoff = None if poll_interval is not None else self._poll_backoff()
        while True:
            info = self.get_rollout(rollout_id)
            if info["status"] in ("success", "failed", "stopped"):
                return info
            if return_on_pause and info["status"] == "paused":
                return info
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"rollout {rollout_id} did not complete within {timeout}s"
                )
            delay = poll_interval if poll_interval is not None else backoff.next_delay()
            time.sleep(delay)

    async def wait_async(
        self,
        rollout_id: str,
        poll_interval: Optional[float] = None,
        timeout: float = 3600.0,
        return_on_pause: bool = False,
    ) -> dict:
        """Async variant of :meth:`wait`.

        Synchronous gRPC calls run in a worker thread via
        :func:`asyncio.to_thread` and delays use :func:`asyncio.sleep`, so
        many rollouts can be awaited concurrently on one event loop.

        See :meth:`wait` for the meaning of ``return_on_pause``; trainers
        pausing stragglers for partial rollout should pass
        ``return_on_pause=True`` or track paused rollout IDs themselves.
        """
        start = time.time()
        backoff = None if poll_interval is not None else self._poll_backoff()
        while True:
            info = await asyncio.to_thread(self.get_rollout, rollout_id)
            if info["status"] in ("success", "failed", "stopped"):
                return info
            if return_on_pause and info["status"] == "paused":
                return info
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"rollout {rollout_id} did not complete within {timeout}s"
                )
            delay = poll_interval if poll_interval is not None else backoff.next_delay()
            await asyncio.sleep(delay)

    def stream_trajectory(self, rollout_id: str) -> Iterator[dict]:
        """Stream trajectory steps in real-time."""
        req = arena_pb.StreamTrajectoryRequest(rollout_id=rollout_id)
        for step in self._call(self.stub.StreamTrajectory, req, timeout=None):
            yield {
                "rollout_id": step.rollout_id,
                "step_id": step.step_id,
                "request": {
                    "endpoint": step.request.endpoint if step.request else None,
                    "model": step.request.model if step.request else None,
                },
                "response": {
                    "usage": {
                        "prompt_tokens": step.response.usage.prompt_tokens
                        if step.response and step.response.usage
                        else 0,
                        "completion_tokens": step.response.usage.completion_tokens
                        if step.response and step.response.usage
                        else 0,
                    },
                    "choices_json": step.response.choices_json
                    if step.response
                    else None,
                    "logprobs_json": step.response.logprobs_json
                    if step.response
                    else None,
                    "prompt_token_ids": list(step.response.prompt_token_ids)
                    if step.response
                    else [],
                    "completion_token_ids": list(step.response.completion_token_ids)
                    if step.response
                    else [],
                    "weight_version": step.response.weight_version
                    if step.response
                    else "",
                }
                if step.response
                else None,
                "metadata": dict(step.metadata),
            }

    def get_trajectory(self, rollout_id: str) -> list[dict]:
        """Get the full trajectory for a completed rollout."""
        req = arena_pb.GetTrajectoryRequest(rollout_id=rollout_id)
        resp = self._call(self.stub.GetTrajectory, req)
        steps = []
        for step in resp.steps:
            steps.append(
                {
                    "rollout_id": step.rollout_id,
                    "step_id": step.step_id,
                    "request": {
                        "endpoint": step.request.endpoint if step.request else None,
                        "model": step.request.model if step.request else None,
                        "messages_json": step.request.messages_json
                        if step.request
                        else None,
                    },
                    "response": {
                        "usage": {
                            "prompt_tokens": step.response.usage.prompt_tokens
                            if step.response and step.response.usage
                            else 0,
                            "completion_tokens": step.response.usage.completion_tokens
                            if step.response and step.response.usage
                            else 0,
                        },
                        "choices_json": step.response.choices_json
                        if step.response
                        else None,
                        "logprobs_json": step.response.logprobs_json
                        if step.response
                        else None,
                        "prompt_token_ids": list(step.response.prompt_token_ids)
                        if step.response
                        else [],
                        "completion_token_ids": list(step.response.completion_token_ids)
                        if step.response
                        else [],
                        "weight_version": step.response.weight_version
                        if step.response
                        else "",
                    }
                    if step.response
                    else None,
                    "metadata": dict(step.metadata),
                }
            )
        return steps

    def list_rollouts(self) -> list[dict]:
        """List all rollouts."""
        req = arena_pb.ListRolloutsRequest()
        resp = self._call(self.stub.ListRollouts, req)
        return [
            {
                "rollout_id": r.rollout_id,
                "task_id": r.task_id,
                "status": r.status,
                "reward": r.reward,
                "weight_version": r.weight_version,
                "verification_report": _verification_report_to_dict(
                    r.verification_report
                ),
            }
            for r in resp.rollouts
        ]

    def stop_rollout(self, rollout_id: str) -> None:
        """Stop a running rollout."""
        req = arena_pb.StopRolloutRequest(rollout_id=rollout_id)
        self._call(self.stub.StopRollout, req)

    def pause_rollout(self, rollout_id: str, mode: str = "freeze") -> None:
        """Pause a running rollout (partial rollout).

        ``mode="freeze"`` freezes the sandbox in place (e.g. docker pause),
        preserving agent state so it can be resumed later with
        :meth:`resume_rollout` under whatever weights the backend serves then.
        """
        req = arena_pb.PauseRolloutRequest(rollout_id=rollout_id, mode=mode)
        self._call(self.stub.PauseRollout, req)

    def resume_rollout(self, rollout_id: str) -> dict:
        """Resume a paused rollout.

        Returns the rollout's ``proxy_url`` and ``token``; the agent's
        subsequent LLM calls are served by the currently deployed weights.
        """
        req = arena_pb.ResumeRolloutRequest(rollout_id=rollout_id)
        resp = self._call(self.stub.ResumeRollout, req)
        return {
            "proxy_url": resp.proxy_url,
            "token": resp.token,
        }

    def update_weights(
        self,
        model_path: str,
        weight_version: str,
        abort_in_flight: bool = False,
    ) -> dict:
        """Ask the server to sync new weights into the inference backend.

        ``model_path`` is a shared-filesystem path to an HF checkpoint the
        trainer has saved; ``weight_version`` is an opaque version string the
        server stamps on rollouts created afterwards. With
        ``abort_in_flight=True`` the backend may abort in-flight generations
        instead of draining them.
        """
        req = arena_pb.UpdateWeightsRequest(
            model_path=model_path,
            weight_version=weight_version,
            abort_in_flight=abort_in_flight,
        )
        resp = self._call(self.stub.UpdateWeights, req)
        return {
            "success": resp.success,
            "message": resp.message,
            "weight_version": resp.weight_version,
        }

    async def pause_rollout_async(self, rollout_id: str, mode: str = "freeze") -> None:
        """Async variant of :meth:`pause_rollout` (runs gRPC in a thread)."""
        await asyncio.to_thread(self.pause_rollout, rollout_id, mode)

    async def resume_rollout_async(self, rollout_id: str) -> dict:
        """Async variant of :meth:`resume_rollout` (runs gRPC in a thread)."""
        return await asyncio.to_thread(self.resume_rollout, rollout_id)

    async def update_weights_async(
        self,
        model_path: str,
        weight_version: str,
        abort_in_flight: bool = False,
    ) -> dict:
        """Async variant of :meth:`update_weights` (runs gRPC in a thread)."""
        return await asyncio.to_thread(
            self.update_weights, model_path, weight_version, abort_in_flight
        )

    def close(self) -> None:
        """Close the gRPC channel."""
        self.channel.close()
