#!/usr/bin/env python3
"""
Minimal SWE-agent style agent for Arena Demo.

Flow:
1. Read task from /sandbox/.arena/task.json
2. Call LLM via OPENAI_BASE_URL (Arena Proxy -> ollama)
3. Write generated code to /sandbox/solution.py
4. Write /sandbox/.arena/done
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI


def main():
    task_path = Path("/sandbox/.arena/task.json")
    done_path = Path("/sandbox/.arena/done")
    solution_path = Path("/sandbox/solution.py")

    # 1. Read task.
    if not task_path.exists():
        print("[agent] No task file found, exiting.", file=sys.stderr)
        sys.exit(1)

    task = json.loads(task_path.read_text())
    prompt = task.get("prompt", "Write a Python function.")
    print(f"[agent] Task: {prompt[:100]}...")

    # 2. Call LLM.
    base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")
    api_key = os.environ.get("ARENA_ROLLOUT_TOKEN", "dummy")

    client = OpenAI(base_url=base_url, api_key=api_key)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful coding assistant. "
                "Respond ONLY with the Python code block, no explanation."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    print(f"[agent] Calling LLM at {base_url} ...")
    try:
        resp = client.chat.completions.create(
            model="qwen3.5:0.8b",
            messages=messages,
            temperature=0.3,
            max_tokens=512,
        )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"[agent] LLM call failed: {e}", file=sys.stderr)
        # Write empty solution so verification can fail gracefully.
        content = ""

    # 3. Extract code block if wrapped in markdown.
    code = content
    if "```python" in content:
        code = content.split("```python")[1].split("```")[0].strip()
    elif "```" in content:
        code = content.split("```")[1].split("```")[0].strip()

    print(f"[agent] Generated code:\n{code[:200]}...")

    # 4. Write solution.
    solution_path.write_text(code)
    print(f"[agent] Written to {solution_path}")

    # 5. Signal completion.
    done_path.touch()
    print("[agent] Done.")

    # Keep container alive briefly so Arena verification can run.
    import time
    time.sleep(10)


if __name__ == "__main__":
    main()
