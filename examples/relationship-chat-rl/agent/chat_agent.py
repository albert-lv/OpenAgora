#!/usr/bin/env python3
"""
Relationship-chat Arena agent.

Flow:
1. Read task from /sandbox/.arena/task.json
2. Call LLM via OPENAI_BASE_URL (Arena Proxy -> backend, usually Ollama)
3. Write the assistant's reply to /sandbox/response.txt
4. Write /sandbox/.arena/done
"""

import json
import os
import time
import urllib.request


def chat_completion(base_url: str, token: str, model: str, messages: list, temperature: float = 0.7, max_tokens: int = 256):
    """Make an OpenAI-compatible chat completion request using urllib."""
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

    timeout = int(os.environ.get("ARENA_AGENT_TIMEOUT_SECONDS", "120"))

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices", [])
        if choices:
            choice = choices[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            # Qwen3.5 puts its thinking/reasoning in a separate field.
            if not content:
                content = message.get("reasoning", "")
            return {
                "content": content,
                "logprobs": choice.get("logprobs", {}),
            }
    return {"content": "", "logprobs": {}}


def main():
    base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARENA_ROLLOUT_TOKEN", "")
    task_id = os.environ.get("ARENA_TASK_ID", "unknown")

    print(f"Task: {task_id}")
    print(f"Proxy: {base_url}")

    # 1. Read task.
    sandbox_dir = os.environ.get("SANDBOX_DIR", "/sandbox")
    task_path = os.path.join(sandbox_dir, ".arena", "task.json")
    prompt = "She sent a message. Please reply gently."
    messages = []
    if os.path.exists(task_path):
        with open(task_path, encoding="utf-8") as f:
            task = json.load(f)
        prompt = task.get("prompt", prompt)
        messages = task.get("messages", [])

    if not messages:
        # Fallback if task file does not carry messages.
        messages = [
            {
                "role": "system",
                "content": (
                    "You are her caring boyfriend/husband. She just sent a message. Please reply in English. "
                    "First acknowledge her emotions, then gently ask or express support; "
                    "do not blame, lecture, dismiss, say \"calm down\" or \"what's the big deal\"; "
                    "be warm and sincere, keep it under 150 words."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    print(f"Prompt: {messages[-1].get('content', prompt)[:80]}...")

    # 2. Call LLM.
    content = ""
    logprobs_info = {}
    if base_url:
        model = os.environ.get("ARENA_LLM_MODEL", "tinyllama")
        try:
            max_tokens = int(os.environ.get("ARENA_AGENT_MAX_TOKENS", "64"))
            result = chat_completion(base_url, token, model, messages, max_tokens=max_tokens)
            content = result.get("content", "")
            logprobs_info = result.get("logprobs", {}) or {}
            print(f"Generated: {content[:200]}...")
            if logprobs_info:
                print(f"Received logprobs for {len(logprobs_info.get('content', []))} tokens")
        except Exception as e:
            print(f"LLM call failed: {e}", file=os.sys.stderr)
    else:
        print("OPENAI_BASE_URL not set, skipping LLM calls")

    # 3. Write response and per-response metadata.
    os.makedirs(os.path.join(sandbox_dir, ".arena"), exist_ok=True)
    with open(os.path.join(sandbox_dir, "response.txt"), "w", encoding="utf-8") as f:
        f.write(content)
    print("Written to " + os.path.join(sandbox_dir, "response.txt"))

    if logprobs_info:
        with open(os.path.join(sandbox_dir, ".arena", "response.json"), "w", encoding="utf-8") as f:
            json.dump({"logprobs": logprobs_info}, f, ensure_ascii=False)
        print("Written " + os.path.join(sandbox_dir, ".arena", "response.json"))

    # 4. Signal completion.
    with open(os.path.join(sandbox_dir, ".arena", "done"), "w") as f:
        f.write(json.dumps({"status": "success"}))
    print("Done.")

    # Keep container alive briefly so Arena verification can run.
    time.sleep(10)


if __name__ == "__main__":
    main()
