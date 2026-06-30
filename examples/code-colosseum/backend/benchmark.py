"""Benchmark engine for Code Colosseum.

Runs every configured agent on every problem and aggregates pass@1, token
usage, and runtime so users can compare agents quantitatively.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.agent_runner import run_agent
from backend.arena_client_wrapper import ArenaWrapper
from backend.pricing import estimate_cost
from backend.problems import Problem


@dataclass
class BenchmarkRun:
    id: str
    status: str = "pending"  # pending, running, completed, failed
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    agent_types: list[str] = field(default_factory=list)
    problem_ids: list[str] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    events: asyncio.Queue = field(default_factory=asyncio.Queue)


class BenchmarkEngine:
    def __init__(
        self,
        arena: Optional[ArenaWrapper] = None,
        max_concurrency: int = 2,
        per_agent_timeout: float = 300.0,
    ):
        self.arena = arena or ArenaWrapper()
        self.max_concurrency = max_concurrency
        self.per_agent_timeout = per_agent_timeout
        self.benchmarks: dict[str, BenchmarkRun] = {}

    async def start_benchmark(
        self,
        problems: list[Problem],
        agent_types: list[str],
    ) -> BenchmarkRun:
        benchmark = BenchmarkRun(
            id=str(uuid.uuid4())[:8],
            agent_types=agent_types,
            problem_ids=[p.id for p in problems],
        )
        self.benchmarks[benchmark.id] = benchmark
        asyncio.create_task(self._run_benchmark(benchmark, problems, agent_types))
        return benchmark

    async def _run_benchmark(
        self,
        benchmark: BenchmarkRun,
        problems: list[Problem],
        agent_types: list[str],
    ):
        benchmark.status = "running"
        await benchmark.events.put(
            {
                "type": "started",
                "benchmark_id": benchmark.id,
                "total_runs": len(problems) * len(agent_types),
            }
        )

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(problem: Problem, agent_type: str) -> dict:
            async with semaphore:
                task_file = problem.build_task_file()
                verify_command = problem.build_verify_command()
                result = await run_agent(
                    arena=self.arena,
                    problem_id=problem.id,
                    task_file=task_file,
                    verify_command=verify_command,
                    agent_type=agent_type,
                    agent_name=agent_type,
                    timeout_seconds=self.per_agent_timeout,
                )
                row = {
                    "problem_id": problem.id,
                    "problem_title": problem.title,
                    "agent_type": agent_type,
                    "status": result.status,
                    "reward": result.reward,
                    "usage": result.usage,
                    "estimated_cost_usd": estimate_cost(result.usage),
                    "duration_seconds": result.duration_seconds,
                    "rollout_id": result.rollout_id,
                }
                benchmark.results.append(row)
                await benchmark.events.put(
                    {
                        "type": "run_completed",
                        "benchmark_id": benchmark.id,
                        "result": row,
                    }
                )
                return row

        try:
            tasks = [
                run_one(problem, agent_type)
                for problem in problems
                for agent_type in agent_types
            ]
            await asyncio.gather(*tasks)
            benchmark.status = "completed"
        except Exception as e:
            benchmark.status = "failed"
            await benchmark.events.put({"type": "error", "message": str(e)})

        benchmark.finished_at = time.time()
        await benchmark.events.put(
            {
                "type": "completed",
                "benchmark_id": benchmark.id,
                "status": benchmark.status,
                "duration_seconds": round(
                    benchmark.finished_at - benchmark.created_at, 2
                ),
            }
        )
        await benchmark.events.put({"type": "done"})

    def get_benchmark(self, benchmark_id: str) -> Optional[BenchmarkRun]:
        return self.benchmarks.get(benchmark_id)

    def list_benchmarks(self) -> list[dict]:
        return [
            {
                "id": b.id,
                "status": b.status,
                "created_at": b.created_at,
                "finished_at": b.finished_at,
                "agent_types": b.agent_types,
                "problem_ids": b.problem_ids,
                "total_runs": len(b.problem_ids) * len(b.agent_types),
                "completed_runs": len(b.results),
            }
            for b in sorted(
                self.benchmarks.values(), key=lambda x: x.created_at, reverse=True
            )
        ]

    def get_benchmark_detail(self, benchmark_id: str) -> Optional[dict]:
        b = self.benchmarks.get(benchmark_id)
        if not b:
            return None

        # Aggregate per-agent summary.
        summary: dict[str, dict] = {}
        for row in b.results:
            agent = row["agent_type"]
            if agent not in summary:
                summary[agent] = {
                    "runs": 0,
                    "passed": 0,
                    "total_reward": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "total_duration_seconds": 0.0,
                    "total_cost_usd": 0.0,
                }
            s = summary[agent]
            s["runs"] += 1
            if row["status"] == "success" and row["reward"] >= 1.0:
                s["passed"] += 1
            s["total_reward"] += row["reward"]
            usage = row.get("usage") or {}
            s["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
            s["completion_tokens"] += int(usage.get("completion_tokens", 0))
            s["total_tokens"] += int(usage.get("total_tokens", 0))
            s["total_duration_seconds"] += row.get("duration_seconds", 0.0)
            s["total_cost_usd"] += row.get("estimated_cost_usd", 0.0)

        for agent, s in summary.items():
            s["pass_at_1"] = s["passed"] / s["runs"] if s["runs"] else 0.0
            s["average_reward"] = s["total_reward"] / s["runs"] if s["runs"] else 0.0
            s["average_cost_usd"] = (
                s["total_cost_usd"] / s["runs"] if s["runs"] else 0.0
            )
            s["reward_per_dollar"] = (
                s["total_reward"] / s["total_cost_usd"] if s["total_cost_usd"] else 0.0
            )

        return {
            "id": b.id,
            "status": b.status,
            "created_at": b.created_at,
            "finished_at": b.finished_at,
            "agent_types": b.agent_types,
            "problem_ids": b.problem_ids,
            "results": b.results,
            "summary": summary,
        }
