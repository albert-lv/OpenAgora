"""Duel engine for Code Colosseum."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.arena_client_wrapper import ArenaWrapper, extract_code_from_trajectory
from backend.problems import Problem


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
    def __init__(self, arena: Optional[ArenaWrapper] = None, elo_service=None):
        self.arena = arena or ArenaWrapper()
        self.elo_service = elo_service
        self.duels: dict[str, Duel] = {}

    async def start_duel(
        self,
        problem: Problem,
        agent_a_name: str = "Agent A",
        agent_b_name: str = "Agent B",
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
            )
            resp_b = self.arena.create_rollout(
                task_id=f"{problem.id}-b",
                task_file=task_file,
                verify_command=verify_command,
            )
            duel.agent_a.rollout_id = resp_a["rollout_id"]
            duel.agent_b.rollout_id = resp_b["rollout_id"]
            duel.status = "running"
        except Exception as e:
            duel.status = "failed"
            await duel.events.put({"type": "error", "message": str(e)})
            return duel

        await duel.events.put(
            {
                "type": "started",
                "duel_id": duel.id,
                "problem_id": problem.id,
                "problem_title": problem.title,
                "agent_a": {"name": agent_a_name, "rollout_id": duel.agent_a.rollout_id},
                "agent_b": {"name": agent_b_name, "rollout_id": duel.agent_b.rollout_id},
            }
        )

        # Run both rollouts concurrently.
        asyncio.create_task(self._watch_agent(duel, duel.agent_a, "agent_a"))
        asyncio.create_task(self._watch_agent(duel, duel.agent_b, "agent_b"))
        asyncio.create_task(self._wait_for_completion(duel))

        return duel

    async def _watch_agent(self, duel: Duel, agent: DuelAgent, key: str):
        """Poll rollout status and emit events."""
        if not agent.rollout_id:
            return

        previous_status = agent.status
        while True:
            try:
                info = self.arena.get_rollout(agent.rollout_id)
            except Exception as e:
                await duel.events.put({"type": "error", "agent": key, "message": str(e)})
                break

            status = info.get("status", "pending")
            if status != previous_status:
                agent.status = status
                previous_status = status
                await duel.events.put(
                    {
                        "type": "agent_status",
                        "agent": key,
                        "status": status,
                        "rollout_id": agent.rollout_id,
                    }
                )

            if status in ("success", "failed", "stopped"):
                agent.reward = info.get("reward", 0.0)
                agent.verification_report = info.get("verification_report")
                if agent.verification_report:
                    agent.stdout = agent.verification_report.get("stdout", "")
                    agent.stderr = agent.verification_report.get("stderr", "")

                # Fetch code from trajectory.
                try:
                    trajectory = self.arena.get_trajectory(agent.rollout_id)
                    agent.code = extract_code_from_trajectory(trajectory)
                except Exception as e:
                    agent.code = f"# failed to extract code: {e}"

                await duel.events.put(
                    {
                        "type": "agent_completed",
                        "agent": key,
                        "status": status,
                        "reward": agent.reward,
                        "code": agent.code,
                        "stdout": agent.stdout,
                        "stderr": agent.stderr,
                    }
                )
                break

            await asyncio.sleep(1.0)

    async def _wait_for_completion(self, duel: Duel):
        """Wait for both agents and determine winner."""
        while True:
            if duel.agent_a.status in ("success", "failed", "stopped") and duel.agent_b.status in (
                "success",
                "failed",
                "stopped",
            ):
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
                },
                "agent_b": {
                    "name": d.agent_b.name,
                    "status": d.agent_b.status,
                    "reward": d.agent_b.reward,
                },
            }
            for d in sorted(self.duels.values(), key=lambda x: x.created_at, reverse=True)
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
            },
            "agent_b": {
                "name": d.agent_b.name,
                "rollout_id": d.agent_b.rollout_id,
                "status": d.agent_b.status,
                "reward": d.agent_b.reward,
                "code": d.agent_b.code,
                "stdout": d.agent_b.stdout,
                "stderr": d.agent_b.stderr,
            },
        }
