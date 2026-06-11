#!/usr/bin/env python3
"""Run a single Arena rollout demo with ollama backend."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python/arena-sdk/src"))

from arena_sdk.client import ArenaClient


def main():
    client = ArenaClient("localhost:9090")

    with open(Path(__file__).parent / "demo_task.json") as f:
        task = json.load(f)

    print("=" * 60)
    print("Arena + ollama Demo Rollout")
    print("=" * 60)
    print(f"Task: {task['task_id']}")
    print(f"Prompt: {task['prompt'][:80]}...")
    print()

    # llm_backend is where Arena Proxy forwards requests.
    # Proxy runs on the host, so it should use localhost to reach ollama.
    # The agent inside Docker will see OPENAI_BASE_URL pointing to the Proxy
    # via host.docker.internal (configured in arena-server).
    llm_backend = "http://localhost:11434/v1"

    print(f"Creating rollout (image=arena-demo-agent, llm_backend={llm_backend})...")
    rollout = client.create_rollout(
        task_id=task["task_id"],
        image="arena-demo-agent:latest",
        llm_backend=llm_backend,
        sampling={"temperature": 0.3, "max_tokens_budget": 2048},
        verify={"command": "cd /sandbox && python -c 'from solution import add; assert add(2,3)==5; assert add(-1,1)==0; print(\"PASS\")'"},
        task_file=json.dumps(task).encode("utf-8"),
        timeout_seconds=120,
    )
    rollout_id = rollout["rollout_id"]
    print(f"Rollout created: {rollout_id}")
    print(f"Proxy URL: {rollout['proxy_url']}")
    print()

    print("Waiting for completion...")
    result = client.wait(rollout_id, poll_interval=1.0, timeout=120.0)
    print(f"Status: {result['status']}")
    print(f"Reward: {result['reward']}")
    print()

    print("Fetching trajectory...")
    trajectory = client.get_trajectory(rollout_id)
    print(f"Steps captured: {len(trajectory)}")
    for step in trajectory:
        req = step.get("request", {})
        resp = step.get("response", {})
        usage = resp.get("usage", {}) if resp else {}
        print(f"  step {step['step_id']}: prompt={usage.get('prompt_tokens', 0)} completion={usage.get('completion_tokens', 0)}")
        if resp and resp.get("logprobs_json"):
            print(f"    -> logprobs captured: {len(resp['logprobs_json'])} bytes")

    print()
    print("=" * 60)
    print("Demo complete.")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
