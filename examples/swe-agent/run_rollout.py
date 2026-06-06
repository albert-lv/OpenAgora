#!/usr/bin/env python3
"""Run an Arena rollout with the SWE-agent sandbox image."""

import argparse
import json
import sys

sys.path.insert(0, "../../python/arena-sdk/src")

from arena_sdk.client import ArenaClient


def main():
    parser = argparse.ArgumentParser(description="Run a SWE-agent Arena rollout")
    parser.add_argument("--endpoint", default="localhost:9090")
    parser.add_argument("--task-file", required=True)
    args = parser.parse_args()

    with open(args.task_file) as f:
        task = json.load(f)

    client = ArenaClient(args.endpoint)

    rollout_id = client.create_rollout(
        task_id=task["task_id"],
        image=task.get("sandbox_image", "arena-swe-agent:latest"),
        llm_backend=task.get("llm_backend", "http://localhost:8000/v1"),
        task_file=json.dumps(task).encode("utf-8"),
        memory="16g",
        cpus=4.0,
        timeout_seconds=7200,
        verify={"command": task.get("test_command", "")} if task.get("test_command") else None,
    )
    print(f"Rollout created: {rollout_id}")

    print("Waiting for completion (this may take a while)...")
    result = client.wait(rollout_id, poll_interval=5.0, timeout=7200.0)
    print(f"Status: {result['status']}")
    print(f"Reward: {result['reward']}")

    trajectory = client.get_trajectory(rollout_id)
    print(f"Trajectory steps: {len(trajectory)}")
    total_prompt = sum(
        s.get("response", {}).get("usage", {}).get("prompt_tokens", 0)
        for s in trajectory
    )
    total_completion = sum(
        s.get("response", {}).get("usage", {}).get("completion_tokens", 0)
        for s in trajectory
    )
    print(f"Total tokens: prompt={total_prompt} completion={total_completion}")

    client.close()


if __name__ == "__main__":
    main()
