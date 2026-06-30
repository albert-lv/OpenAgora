import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.benchmark import BenchmarkEngine
from backend.problems import Problem


@pytest.mark.asyncio
async def test_benchmark_aggregates_summary():
    arena = MagicMock()

    def fake_create_rollout(task_id, task_file, verify_command, agent_type):
        return {"rollout_id": f"{task_id}-{agent_type}"}

    def fake_get_rollout(rollout_id):
        # First agent passes, second fails.
        if "agent_a" in rollout_id:
            return {"status": "success", "reward": 1.0}
        return {"status": "failed", "reward": 0.0}

    def fake_get_trajectory(rollout_id):
        if "agent_a" in rollout_id:
            return [
                {
                    "response": {
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                        },
                        "choices_json": b'{"choices":[{"message":{"content":"```python\\ndef solve():\\n    pass\\n```"}}]}',
                    }
                }
            ]
        return [
            {
                "response": {
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 10,
                    },
                    "choices_json": b'{"choices":[{"message":{"content":"bad"}}]}',
                }
            }
        ]

    arena.create_rollout.side_effect = fake_create_rollout
    arena.get_rollout.side_effect = fake_get_rollout
    arena.get_trajectory.side_effect = fake_get_trajectory

    engine = BenchmarkEngine(arena=arena, max_concurrency=2)
    problems_dir = Path(__file__).parent.parent / "problems"
    problems = [
        Problem(problems_dir / "roman-to-integer-strict"),
        Problem(problems_dir / "merge-sorted-logs"),
    ]
    benchmark = await engine.start_benchmark(problems, ["agent_a", "agent_b"])

    # Wait for completion.
    for _ in range(50):
        if benchmark.status in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)

    assert benchmark.status == "completed"
    assert len(benchmark.results) == 4

    detail = engine.get_benchmark_detail(benchmark.id)
    assert detail is not None
    summary = detail["summary"]
    assert summary["agent_a"]["runs"] == 2
    assert summary["agent_a"]["passed"] == 2
    assert summary["agent_a"]["pass_at_1"] == 1.0
    assert summary["agent_a"]["total_tokens"] == 60
    # agent_a: 2 runs * (10 prompt + 20 completion) tokens
    # cost = 2 * (10*0.0015/1000 + 20*0.006/1000)
    assert summary["agent_a"]["total_cost_usd"] == pytest.approx(0.00027)
    assert summary["agent_a"]["average_cost_usd"] == pytest.approx(0.000135)
    assert summary["agent_b"]["runs"] == 2
    assert summary["agent_b"]["passed"] == 0
    assert summary["agent_b"]["pass_at_1"] == 0.0
