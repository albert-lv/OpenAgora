#!/usr/bin/env python3
"""
Minimal Arena agent for code generation.
Uses only stdlib (urllib) to keep the Alpine image small.

Flow:
1. Read task from /sandbox/.arena/task.json
2. Call LLM via OPENAI_BASE_URL (Arena Proxy -> ollama)
3. Write generated code to /sandbox/solution.py
4. Write /sandbox/.arena/done
"""

import json
import os
import time
import urllib.request


def chat_completion(base_url: str, token: str, model: str, messages: list, temperature: float = 0.3, max_tokens: int = 512):
    """Make an OpenAI-compatible chat completion request using urllib."""
    req_body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
    return ""


def main():
    base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARENA_ROLLOUT_TOKEN", "")
    task_id = os.environ.get("ARENA_TASK_ID", "unknown")

    print(f"Task: {task_id}")
    print(f"Proxy: {base_url}")

    # 1. Read task.
    task_path = "/sandbox/.arena/task.json"
    prompt = "Write a Python function."
    if os.path.exists(task_path):
        with open(task_path) as f:
            task = json.load(f)
        prompt = task.get("prompt", prompt)

    print(f"Prompt: {prompt[:100]}...")

    # 2. Call LLM.
    content = ""
    if base_url:
        model = os.environ.get("ARENA_LLM_MODEL", "qwen3.5:0.8b")
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
        try:
            content = chat_completion(base_url, token, model, messages)
            print(f"Generated: {content[:200]}...")
        except Exception as e:
            print(f"LLM call failed: {e}", file=os.sys.stderr)
    else:
        print("OPENAI_BASE_URL not set, skipping LLM calls")

    # 3. Extract code block if wrapped in markdown.
    code = content
    if "```python" in content:
        code = content.split("```python")[1].split("```")[0].strip()
    elif "```" in content:
        code = content.split("```")[1].split("```")[0].strip()

    # 4. Write solution.
    os.makedirs("/sandbox/.arena", exist_ok=True)
    with open("/sandbox/solution.py", "w") as f:
        f.write(code)
    print(f"Written to /sandbox/solution.py")

    # 5. Signal completion.
    with open("/sandbox/.arena/done", "w") as f:
        f.write(json.dumps({"status": "success"}))
    print("Done.")

    # Keep container alive briefly so Arena verification can run.
    time.sleep(10)


if __name__ == "__main__":
    main()
