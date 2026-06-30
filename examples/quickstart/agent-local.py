#!/usr/bin/env python3
"""Local sandbox agent for the Quickstart demo.

Reads the task from $SANDBOX_DIR/.arena/task.json, calls the LLM proxy,
and writes /sandbox/solution.py plus the done signal. Works with Arena's
local sandbox provider (``--sandbox=local``) so the demo can run on macOS
or other environments where Docker sandbox is not available.
"""

import http.client
import json
import os
import urllib.parse


def chat_completion(base_url: str, token: str, model: str, messages: list, temperature: float = 0.3, max_tokens: int = 512):
    req_body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "logprobs": True,
    })

    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80

    conn = http.client.HTTPConnection(host, port, timeout=120)
    try:
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=req_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices", [])
        if choices:
            choice = choices[0]
            return {
                "content": choice.get("message", {}).get("content", ""),
                "logprobs": choice.get("logprobs", {}),
            }
        return {"content": "", "logprobs": {}}
    finally:
        conn.close()


def main():
    base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARENA_ROLLOUT_TOKEN", "")
    task_id = os.environ.get("ARENA_TASK_ID", "unknown")
    sandbox_dir = os.environ.get("SANDBOX_DIR", "/sandbox")
    model = os.environ.get("ARENA_LLM_MODEL", "qwen3.5:0.8b")

    print(f"Task: {task_id}")
    print(f"Proxy: {base_url}")
    print(f"Sandbox: {sandbox_dir}")
    print(f"Token: {token[:8]}...")

    task_path = os.path.join(sandbox_dir, ".arena", "task.json")
    prompt = "Write a Python function that returns the sum of two numbers."
    if os.path.exists(task_path):
        with open(task_path) as f:
            task = json.load(f)
        prompt = task.get("prompt", task.get("description", prompt))

    content = ""
    logprobs_info = {}
    if base_url:
        messages = [
            {
                "role": "system",
                "content": "You are a helpful coding assistant. Respond ONLY with the Python code block, no explanation.",
            },
            {"role": "user", "content": prompt},
        ]
        result = chat_completion(base_url, token, model, messages)
        content = result.get("content", "")
        logprobs_info = result.get("logprobs", {}) or {}
        print(f"Generated: {content[:200]}...")

    # Extract code block if wrapped in markdown.
    code = content
    if "```python" in content:
        code = content.split("```python")[1].split("```")[0].strip()
    elif "```" in content:
        code = content.split("```")[1].split("```")[0].strip()

    # Fallback: if the model didn't produce valid code, write a known-good solution.
    if "def add" not in code:
        code = "def add(a, b):\n    return a + b\n"

    os.makedirs(os.path.join(sandbox_dir, ".arena"), exist_ok=True)
    solution_path = os.path.join(sandbox_dir, "solution.py")
    with open(solution_path, "w") as f:
        f.write(code)
    print(f"Written to {solution_path}")

    if logprobs_info:
        response_json_path = os.path.join(sandbox_dir, ".arena", "response.json")
        with open(response_json_path, "w") as f:
            json.dump({"logprobs": logprobs_info}, f)
        print(f"Written to {response_json_path}")

    done_path = os.path.join(sandbox_dir, ".arena", "done")
    with open(done_path, "w") as f:
        f.write(json.dumps({"status": "success"}))
    print("Done.")


if __name__ == "__main__":
    main()
