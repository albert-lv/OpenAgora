#!/usr/bin/env python3
"""Quickstart: create a rollout and wait for completion."""

import argparse
import json
import sys

sys.path.insert(0, "../../python/arena-sdk/src")

from arena_sdk.client import ArenaClient


def main():
    parser = argparse.ArgumentParser(description="Run an Arena rollout")
    parser.add_argument("--endpoint", default="localhost:9090")
    parser.add_argument("--task-file", required=True)
    args = parser.parse_args()

    with open(args.task_file) as f:
        task = json.load(f)

    client = ArenaClient(args.endpoint)

    rollout_id = client.create_rollout(
        task_id=task["task_id"],
        image=task.get("sandbox_image", "arena-agent-minimal:latest"),
        llm_backend=task.get("llm_backend", "http://localhost:8000/v1"),
        sampling=task.get("sampling"),
        verify=task.get("verify"),
        task_file=json.dumps(task).encode("utf-8"),
    )
    print(f"Rollout created: {rollout_id}")

    print("Waiting for completion...")
    result = client.wait(rollout_id)
    print(f"Status: {result['status']}")
    print(f"Reward: {result['reward']}")

    trajectory = client.get_trajectory(rollout_id)
    print(f"Trajectory steps: {len(trajectory)}")
    for step in trajectory:
        req = step.get("request", {})
        resp = step.get("response", {})
        usage = resp.get("usage", {}) if resp else {}
        print(f"  step {step['step_id']}: prompt={usage.get('prompt_tokens', 0)} completion={usage.get('completion_tokens', 0)}")

    client.close()


if __name__ == "__main__":
    main()
