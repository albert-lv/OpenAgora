#!/usr/bin/env python3
"""
Arena × SWE-agent Adapter

This entrypoint bridges the Arena sandbox contract with SWE-agent (mini-swe-agent).
It reads task.json, sets up the environment, runs the agent, and signals completion.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ARENA_DIR = Path("/sandbox/.arena")
TASK_FILE = ARENA_DIR / "task.json"
DONE_FILE = ARENA_DIR / "done"
REWARDS_FILE = ARENA_DIR / "rewards.jsonl"
WORKSPACE = Path("/sandbox/workspace")


def log(msg: str):
    print(f"[openagora-swe-agent] {msg}", flush=True)


def read_task() -> dict:
    with open(TASK_FILE) as f:
        return json.load(f)


def write_done(status: str, reason: str = ""):
    ARENA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DONE_FILE, "w") as f:
        json.dump({"status": status, "reason": reason}, f)


def write_reward(value: float, source: str):
    ARENA_DIR.mkdir(parents=True, exist_ok=True)
    with open(REWARDS_FILE, "a") as f:
        f.write(json.dumps({"type": "verify", "value": value, "source": source}) + "\n")


def clone_repo(repo_url: str, commit: str = "") -> bool:
    """Clone the target repository into the workspace."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    log(f"Cloning {repo_url} ...")
    result = subprocess.run(
        ["git", "clone", repo_url, str(WORKSPACE)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log(f"git clone failed: {result.stderr}")
        return False
    if commit:
        log(f"Checking out commit {commit} ...")
        result = subprocess.run(
            ["git", "-C", str(WORKSPACE), "reset", "--hard", commit],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log(f"git checkout failed: {result.stderr}")
            return False
    return True


def run_miniswe(task: dict) -> int:
    """Run mini-swe-agent with the given task configuration."""
    # mini-swe-agent is expected to be installed and available on PATH.
    # It uses OPENAI_BASE_URL and OPENAI_API_KEY from the environment.
    # Arena injects OPENAI_BASE_URL pointing to its proxy.

    issue_text = task.get("description", "")
    repo_name = task.get("repository", "").rstrip("/").split("/")[-1].replace(".git", "")

    if not issue_text:
        log("No issue description in task.json")
        return 1

    # Try to run mini-swe-agent via its CLI if available.
    # The exact CLI may vary; we try common invocation patterns.
    commands_to_try = [
        # Pattern 1: mini-swe-agent CLI with --problem-spec
        [
            "python", "-m", "minisweagent.run.benchmarks.swebench_single",
            "--problem-spec", issue_text,
            "--repo-name", repo_name,
        ],
        # Pattern 2: Direct script invocation
        [
            "python", "-c", f"""
import sys
sys.path.insert(0, '/usr/local/lib/python3.12/site-packages')
try:
    from minisweagent.run.benchmarks.swebench_single import main
    main()
except Exception as e:
    print(f'Error: {{e}}')
    sys.exit(1)
"""
        ],
    ]

    for cmd in commands_to_try:
        log(f"Trying: {' '.join(cmd[:4])}...")
        result = subprocess.run(cmd, cwd=str(WORKSPACE), capture_output=True, text=True)
        if result.returncode == 0:
            log("mini-swe-agent completed successfully")
            return 0
        log(f"Attempt failed: {result.stderr[:500]}")

    # Fallback: if mini-swe-agent CLI is not available, run a minimal
    # agent loop directly using the OpenAI API (pointing to Arena proxy).
    log("Falling back to minimal agent loop...")
    return run_fallback_agent(task)


def run_fallback_agent(task: dict) -> int:
    """
    Minimal SWE-agent fallback that uses bash + OpenAI API directly.
    This ensures the integration works even if mini-swe-agent CLI changes.
    """
    try:
        import openai
    except ImportError:
        log("openai package not installed; cannot run fallback agent")
        return 1

    client = openai.OpenAI()
    issue = task.get("description", "")
    repo = task.get("repository", "")
    test_cmd = task.get("test_command", "")

    system_prompt = f"""You are a software engineering agent. Your task:
{issue}

Repository: {repo}
Workspace: {WORKSPACE}

You have access to bash commands. Solve the issue step by step.
When done, output exactly: SUBMIT
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Start working on the issue. Use bash commands to explore and edit files."},
    ]

    max_turns = 30
    for turn in range(max_turns):
        try:
            resp = client.chat.completions.create(
                model=os.environ.get("ARENA_MODEL", "gpt-4o"),
                messages=messages,
                temperature=0.2,
            )
            content = resp.choices[0].message.content or ""
        except Exception as e:
            log(f"LLM call failed: {e}")
            return 1

        log(f"Turn {turn + 1}: {content[:200]}...")

        if "SUBMIT" in content.upper():
            log("Agent signaled completion")
            break

        # Extract bash commands from markdown code blocks
        bash_commands = extract_bash_commands(content)
        if not bash_commands:
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Please use bash commands to make progress."})
            continue

        outputs = []
        for cmd in bash_commands:
            log(f"Executing: {cmd}")
            result = subprocess.run(
                cmd, shell=True, cwd=str(WORKSPACE),
                capture_output=True, text=True, timeout=60,
            )
            stdout = result.stdout[:2000] if result.stdout else ""
            stderr = result.stderr[:1000] if result.stderr else ""
            outputs.append(f"$ {cmd}\n{stdout}\n{stderr}")

        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "\n".join(outputs)})

    # Run verification if test_command is provided
    if test_cmd:
        log(f"Running verification: {test_cmd}")
        result = subprocess.run(
            test_cmd, shell=True, cwd=str(WORKSPACE),
            capture_output=True, text=True, timeout=120,
        )
        reward = 1.0 if result.returncode == 0 else 0.0
        write_reward(reward, "verify:test_command")
        log(f"Verification reward: {reward}")

    return 0


def extract_bash_commands(content: str) -> list:
    """Extract bash commands from markdown code blocks."""
    commands = []
    import re
    # Match ```bash ... ``` or ``` ... ``` blocks
    for block in re.findall(r"```(?:bash)?\n(.*?)\n```", content, re.DOTALL):
        for line in block.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


def main():
    log("Arena × SWE-agent adapter starting...")

    # Ensure arena directory exists
    ARENA_DIR.mkdir(parents=True, exist_ok=True)

    if not TASK_FILE.exists():
        log(f"Task file not found: {TASK_FILE}")
        write_done("failed", "task.json not found")
        sys.exit(1)

    task = read_task()
    log(f"Task: {task.get('task_id', 'unknown')}")
    log(f"Description: {task.get('description', '')[:100]}...")

    # Clone repository if specified
    repo = task.get("repository", "")
    if repo:
        commit = task.get("commit", "")
        if not clone_repo(repo, commit):
            write_done("failed", "repository clone failed")
            sys.exit(1)
    else:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        log("No repository specified; using empty workspace")

    # Log environment
    proxy_url = os.environ.get("OPENAI_BASE_URL", "(not set)")
    token = os.environ.get("ARENA_ROLLOUT_TOKEN", "(not set)")[:8] + "..."
    log(f"OPENAI_BASE_URL={proxy_url}")
    log(f"ARENA_ROLLOUT_TOKEN={token}")

    # Run the agent
    exit_code = run_miniswe(task)

    if exit_code == 0:
        write_done("success", "agent completed")
    else:
        write_done("failed", "agent exited with error")

    log("Done.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
