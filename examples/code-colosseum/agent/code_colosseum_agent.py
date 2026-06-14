#!/usr/bin/env python3
"""
Code Colosseum agent.

Reads a problem from /sandbox/.arena/task.json, calls the LLM through the
Arena proxy, writes /sandbox/solution.py, and signals completion.

The task.json format expected by this agent:
{
  "problem": {
    "id": "two-sum",
    "title": "Two Sum",
    "description": "...",
    "function_signature": "def two_sum(...):",
    "language": "python"
  },
  "hidden_tests": "# pytest content"
}
"""

import json
import os
import time
import urllib.request


def chat_completion(base_url: str, token: str, model: str, messages: list, temperature: float = 0.3, max_tokens: int = 1024):
    """OpenAI-compatible chat completion using urllib."""
    req_body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "logprobs": True,
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
            choice = choices[0]
            return {
                "content": choice.get("message", {}).get("content", ""),
                "logprobs": choice.get("logprobs", {}),
            }
    return {"content": "", "logprobs": {}}


def extract_code(content: str) -> str:
    """Extract the first Python code block."""
    if "```python" in content:
        return content.split("```python")[1].split("```")[0].strip()
    if "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content.strip()


def main():
    base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARENA_ROLLOUT_TOKEN", "")
    task_id = os.environ.get("ARENA_TASK_ID", "unknown")

    print(f"Task: {task_id}")
    print(f"Proxy: {base_url}")

    task_path = "/sandbox/.arena/task.json"
    problem = {}
    hidden_tests = ""
    if os.path.exists(task_path):
        with open(task_path) as f:
            task = json.load(f)
        problem = task.get("problem", {})
        hidden_tests = task.get("hidden_tests", "")

    title = problem.get("title", "Coding Problem")
    description = problem.get("description", "")
    signature = problem.get("function_signature", "def solve():")

    prompt = (
        f"Solve the following coding problem.\n\n"
        f"Title: {title}\n\n"
        f"Description:\n{description}\n\n"
        f"Function signature:\n{signature}\n\n"
        f"Write a complete Python solution. Respond ONLY with a Python code block. "
        f"Do not include explanations."
    )

    print(f"Prompt:\n{prompt[:200]}...")

    content = ""
    logprobs_info = {}
    if base_url:
        model = os.environ.get("ARENA_LLM_MODEL", "qwen3.5:0.8b")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert competitive programmer. "
                    "Respond ONLY with a Python code block containing the solution. "
                    "No explanation, no markdown outside the code block."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        try:
            result = chat_completion(base_url, token, model, messages)
            content = result.get("content", "")
            logprobs_info = result.get("logprobs", {}) or {}
            print(f"Generated:\n{content[:300]}...")
        except Exception as e:
            print(f"LLM call failed: {e}", file=os.sys.stderr)
    else:
        print("OPENAI_BASE_URL not set, skipping LLM calls")

    code = extract_code(content)

    os.makedirs("/sandbox/.arena", exist_ok=True)
    with open("/sandbox/solution.py", "w") as f:
        f.write(code)
    print("Written /sandbox/solution.py")

    if hidden_tests:
        with open("/sandbox/hidden_tests.py", "w") as f:
            f.write(hidden_tests)
        print("Written /sandbox/hidden_tests.py")

    if logprobs_info:
        with open("/sandbox/.arena/response.json", "w") as f:
            json.dump({"logprobs": logprobs_info}, f)

    with open("/sandbox/.arena/done", "w") as f:
        f.write(json.dumps({"status": "success"}))
    print("Done.")

    time.sleep(10)


if __name__ == "__main__":
    main()
