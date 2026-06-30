#!/usr/bin/env python3
"""Run an Arena rollout with the SWE-agent sandbox image."""

import argparse
import json
import os
import sys

sys.path.insert(0, "../../python/openagora-sdk/src")

from openagora_sdk.client import ArenaClient


def main():
    parser = argparse.ArgumentParser(description="Run a SWE-agent Arena rollout")
    parser.add_argument("--endpoint", default="localhost:9090")
    parser.add_argument("--task-file", required=True)
    args = parser.parse_args()

    with open(args.task_file) as f:
        task = json.load(f)

    client = ArenaClient(args.endpoint)

    llm_backend = task.get("llm_backend") or os.environ.get("ARENA_LLM_BACKEND", "http://localhost:8000/v1")
    rollout_info = client.create_rollout(
        task_id=task["task_id"],
        image=task.get("sandbox_image", "openagora-swe-agent:latest"),
        llm_backend=llm_backend,
        task_file=json.dumps(task).encode("utf-8"),
        memory="16g",
        cpus=4.0,
        timeout_seconds=7200,
        verify={"command": task.get("test_command", "")} if task.get("test_command") else None,
        env_vars=task.get("env_vars"),
    )
    rollout_id = rollout_info["rollout_id"]
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
