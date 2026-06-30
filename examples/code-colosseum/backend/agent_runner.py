"""Standalone agent execution helper.

Wraps the Arena rollout lifecycle (create, poll, collect reward/usage/code) so
that both duels and benchmarks can reuse the same polling logic.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from backend.arena_client_wrapper import (
    ArenaWrapper,
    extract_code_from_trajectory,
    extract_usage_from_trajectory,
)


@dataclass
class AgentResult:
    name: str
    agent_type: str
    rollout_id: Optional[str] = None
    status: str = "pending"
    code: str = ""
    reward: float = 0.0
    verification_report: Optional[dict] = None
    stdout: str = ""
    stderr: str = ""
    usage: dict = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "steps": 0,
        }
    )
    duration_seconds: float = 0.0


async def run_agent(
    arena: ArenaWrapper,
    problem_id: str,
    task_file: bytes,
    verify_command: list[str],
    agent_type: str,
    agent_name: str,
    timeout_seconds: float = 300.0,
    poll_interval: float = 1.0,
) -> AgentResult:
    """Create a rollout, poll it to completion, and return collected metrics."""
    result = AgentResult(name=agent_name, agent_type=agent_type)
    started_at = time.time()

    try:
        resp = arena.create_rollout(
            task_id=f"{problem_id}-{agent_type}",
            task_file=task_file,
            verify_command=verify_command,
            agent_type=agent_type,
        )
        result.rollout_id = resp["rollout_id"]
        result.status = "running"
    except Exception as e:
        result.status = "failed"
        result.stderr = f"failed to create rollout: {e}"
        result.duration_seconds = time.time() - started_at
        return result

    previous_status = result.status
    consecutive_errors = 0
    while True:
        if time.time() - started_at > timeout_seconds:
            result.status = "failed"
            result.stderr = f"timeout after {timeout_seconds}s"
            _stop_rollout(arena, result.rollout_id)
            result.duration_seconds = time.time() - started_at
            return result

        try:
            info = arena.get_rollout(result.rollout_id)
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                result.status = "failed"
                result.stderr = f"failed to query rollout after 3 attempts: {e}"
                result.duration_seconds = time.time() - started_at
                return result
            await asyncio.sleep(poll_interval)
            continue

        status = info.get("status", "pending")
        if status != previous_status:
            result.status = status
            previous_status = status

        if status in ("success", "failed", "stopped"):
            result.reward = info.get("reward", 0.0)
            result.verification_report = info.get("verification_report")
            if result.verification_report:
                result.stdout = result.verification_report.get("stdout", "")
                result.stderr = result.verification_report.get("stderr", "")

            try:
                trajectory = arena.get_trajectory(result.rollout_id)
                result.code = extract_code_from_trajectory(trajectory)
                result.usage = extract_usage_from_trajectory(trajectory)
            except Exception as e:
                result.code = f"# failed to extract code: {e}"

            result.duration_seconds = time.time() - started_at
            return result

        await asyncio.sleep(poll_interval)


def _stop_rollout(arena: ArenaWrapper, rollout_id: Optional[str]) -> None:
    if not rollout_id:
        return
    try:
        arena.stop_rollout(rollout_id)
    except Exception:
        pass
