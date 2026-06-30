"""Duel engine for Code Colosseum."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.agent_runner import AgentResult, run_agent
from backend.arena_client_wrapper import ArenaWrapper
from backend.pricing import estimate_cost
from backend.problems import Problem


# Maximum time a duel may run before the orchestrator forces both agents to
# stop.  This is a safety net independent of the per-rollout sandbox timeout.
DEFAULT_DUEL_TIMEOUT_SECONDS = 600.0


@dataclass
class DuelAgent:
    name: str
    rollout_id: Optional[str] = None
    status: str = "pending"  # pending, running, success, failed, stopped
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
    estimated_cost_usd: float = 0.0

    @classmethod
    def from_result(cls, result: AgentResult) -> "DuelAgent":
        return cls(
            name=result.name,
            rollout_id=result.rollout_id,
            status=result.status,
            code=result.code,
            reward=result.reward,
            verification_report=result.verification_report,
            stdout=result.stdout,
            stderr=result.stderr,
            usage=result.usage,
            estimated_cost_usd=estimate_cost(result.usage),
        )


@dataclass
class Duel:
    id: str
    problem_id: str
    problem_title: str
    agent_a: DuelAgent
    agent_b: DuelAgent
    status: str = "pending"
    winner: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    events: asyncio.Queue = field(default_factory=asyncio.Queue)


class DuelEngine:
    def __init__(
        self,
        arena: Optional[ArenaWrapper] = None,
        elo_service=None,
        duel_timeout: float = DEFAULT_DUEL_TIMEOUT_SECONDS,
    ):
        self.arena = arena or ArenaWrapper()
        self.elo_service = elo_service
        self.duel_timeout = duel_timeout
        self.duels: dict[str, Duel] = {}

    async def start_duel(
        self,
        problem: Problem,
        agent_a_name: str = "Agent A",
        agent_b_name: str = "Agent B",
        agent_a_type: str = "mock",
        agent_b_type: str = "mock",
    ) -> Duel:
        duel = Duel(
            id=str(uuid.uuid4())[:8],
            problem_id=problem.id,
            problem_title=problem.title,
            agent_a=DuelAgent(name=agent_a_name),
            agent_b=DuelAgent(name=agent_b_name),
        )
        self.duels[duel.id] = duel

        task_file = problem.build_task_file()
        verify_command = problem.build_verify_command()

        # Create both rollouts.
        try:
            resp_a = self.arena.create_rollout(
                task_id=f"{problem.id}-a",
                task_file=task_file,
                verify_command=verify_command,
                agent_type=agent_a_type,
            )
            resp_b = self.arena.create_rollout(
                task_id=f"{problem.id}-b",
                task_file=task_file,
                verify_command=verify_command,
                agent_type=agent_b_type,
            )
            duel.agent_a.rollout_id = resp_a["rollout_id"]
            duel.agent_b.rollout_id = resp_b["rollout_id"]
            duel.status = "running"
        except Exception as e:
            duel.status = "failed"
            await duel.events.put({"type": "error", "message": str(e)})
            await duel.events.put({"type": "done"})
            return duel

        await duel.events.put(
            {
                "type": "started",
                "duel_id": duel.id,
                "problem_id": problem.id,
                "problem_title": problem.title,
                "agent_a": {
                    "name": agent_a_name,
                    "rollout_id": duel.agent_a.rollout_id,
                },
                "agent_b": {
                    "name": agent_b_name,
                    "rollout_id": duel.agent_b.rollout_id,
                },
            }
        )

        # Run both rollouts concurrently.
        watch_a = asyncio.create_task(
            self._watch_agent(
                duel, duel.agent_a, "agent_a", task_file, verify_command, agent_a_type
            )
        )
        watch_b = asyncio.create_task(
            self._watch_agent(
                duel, duel.agent_b, "agent_b", task_file, verify_command, agent_b_type
            )
        )
        completion = asyncio.create_task(self._wait_for_completion(duel))

        # Attach tasks to the duel so they can be cancelled if needed.
        duel._tasks = [watch_a, watch_b, completion]  # type: ignore[attr-defined]

        return duel

    async def _watch_agent(
        self,
        duel: Duel,
        agent: DuelAgent,
        key: str,
        task_file: bytes,
        verify_command: list[str],
        agent_type: str,
    ):
        """Poll rollout status and emit events."""
        if not agent.rollout_id:
            agent.status = "failed"
            await duel.events.put(
                {"type": "error", "agent": key, "message": "missing rollout id"}
            )
            return

        # Notify initial running status.
        await duel.events.put(
            {
                "type": "agent_status",
                "agent": key,
                "status": "running",
                "rollout_id": agent.rollout_id,
            }
        )

        result = await run_agent(
            arena=self.arena,
            problem_id=duel.problem_id,
            task_file=task_file,
            verify_command=verify_command,
            agent_type=agent_type,
            agent_name=agent.name,
            timeout_seconds=self.duel_timeout,
        )

        # Sync result back to the duel agent.
        agent.rollout_id = result.rollout_id
        agent.status = result.status
        agent.code = result.code
        agent.reward = result.reward
        agent.verification_report = result.verification_report
        agent.stdout = result.stdout
        agent.stderr = result.stderr
        agent.usage = result.usage
        agent.estimated_cost_usd = estimate_cost(result.usage)

        await duel.events.put(
            {
                "type": "agent_status",
                "agent": key,
                "status": result.status,
                "rollout_id": result.rollout_id,
            }
        )
        await duel.events.put(
            {
                "type": "agent_completed",
                "agent": key,
                "status": result.status,
                "reward": result.reward,
                "code": result.code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "usage": result.usage,
                "estimated_cost_usd": agent.estimated_cost_usd,
            }
        )

    async def _wait_for_completion(self, duel: Duel):
        """Wait for both agents and determine winner."""
        deadline = duel.created_at + self.duel_timeout
        while True:
            if duel.agent_a.status in (
                "success",
                "failed",
                "stopped",
            ) and duel.agent_b.status in (
                "success",
                "failed",
                "stopped",
            ):
                break

            if time.time() > deadline:
                # Force any still-running agents to failed so the duel can
                # finish even if a watcher is stuck.
                for agent in (duel.agent_a, duel.agent_b):
                    if agent.status not in ("success", "failed", "stopped"):
                        agent.status = "failed"
                        agent.stderr = f"duel timeout after {self.duel_timeout}s"
                        if agent.rollout_id:
                            try:
                                self.arena.stop_rollout(agent.rollout_id)
                            except Exception:
                                pass
                break

            await asyncio.sleep(0.5)

        duel.status = "completed"
        duel.finished_at = time.time()

        # Determine winner based on reward.
        a_reward = duel.agent_a.reward
        b_reward = duel.agent_b.reward

        if a_reward > b_reward:
            duel.winner = duel.agent_a.name
            score_a = 1.0
        elif b_reward > a_reward:
            duel.winner = duel.agent_b.name
            score_a = 0.0
        else:
            duel.winner = "draw"
            score_a = 0.5

        await duel.events.put(
            {
                "type": "completed",
                "duel_id": duel.id,
                "winner": duel.winner,
                "agent_a_reward": a_reward,
                "agent_b_reward": b_reward,
                "duration_seconds": round(duel.finished_at - duel.created_at, 2),
                "score_a": score_a,
            }
        )

        if self.elo_service:
            self.elo_service.record_match(
                duel.agent_a.name,
                duel.agent_b.name,
                score_a,
                name_a=duel.agent_a.name,
                name_b=duel.agent_b.name,
            )

        await duel.events.put({"type": "done"})

    def get_duel(self, duel_id: str) -> Optional[Duel]:
        return self.duels.get(duel_id)

    def list_duels(self) -> list[dict]:
        return [
            {
                "id": d.id,
                "problem_id": d.problem_id,
                "problem_title": d.problem_title,
                "status": d.status,
                "winner": d.winner,
                "created_at": d.created_at,
                "finished_at": d.finished_at,
                "agent_a": {
                    "name": d.agent_a.name,
                    "status": d.agent_a.status,
                    "reward": d.agent_a.reward,
                    "usage": d.agent_a.usage,
                    "estimated_cost_usd": d.agent_a.estimated_cost_usd,
                },
                "agent_b": {
                    "name": d.agent_b.name,
                    "status": d.agent_b.status,
                    "reward": d.agent_b.reward,
                    "usage": d.agent_b.usage,
                    "estimated_cost_usd": d.agent_b.estimated_cost_usd,
                },
            }
            for d in sorted(
                self.duels.values(), key=lambda x: x.created_at, reverse=True
            )
        ]

    def get_duel_detail(self, duel_id: str) -> Optional[dict]:
        d = self.duels.get(duel_id)
        if not d:
            return None
        return {
            "id": d.id,
            "problem_id": d.problem_id,
            "problem_title": d.problem_title,
            "status": d.status,
            "winner": d.winner,
            "created_at": d.created_at,
            "finished_at": d.finished_at,
            "agent_a": {
                "name": d.agent_a.name,
                "rollout_id": d.agent_a.rollout_id,
                "status": d.agent_a.status,
                "reward": d.agent_a.reward,
                "code": d.agent_a.code,
                "stdout": d.agent_a.stdout,
                "stderr": d.agent_a.stderr,
                "usage": d.agent_a.usage,
                "estimated_cost_usd": d.agent_a.estimated_cost_usd,
            },
            "agent_b": {
                "name": d.agent_b.name,
                "rollout_id": d.agent_b.rollout_id,
                "status": d.agent_b.status,
                "reward": d.agent_b.reward,
                "code": d.agent_b.code,
                "stdout": d.agent_b.stdout,
                "stderr": d.agent_b.stderr,
                "usage": d.agent_b.usage,
                "estimated_cost_usd": d.agent_b.estimated_cost_usd,
            },
        }
