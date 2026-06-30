"""OpenAI-compatible LLM backend powered by Kimi Code CLI.

Wraps the Kimi CLI in non-interactive mode and exposes an OpenAI-compatible
chat completions endpoint. The underlying LLM is whatever Kimi CLI is
configured to use (by default the Kimi Code API via OAuth or API key).
"""

import os
import subprocess
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Kimi Code CLI LLM Backend")

KIMI_TIMEOUT = int(os.environ.get("KIMI_TIMEOUT", "120"))


class ChatCompletionRequest(BaseModel):
    model: str = "kimi"
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None


def build_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten messages into a single prompt string."""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def call_kimi(prompt: str) -> str:
    """Call Kimi CLI in non-interactive mode.

    Tries the modern headless invocations first:
      1. kimi -p <prompt> --output-format stream-json
      2. kimi --print --output-format stream-json <prompt>
      3. kimi "<prompt>"
    """
    commands = [
        ["kimi", "-p", prompt, "--output-format", "stream-json"],
        ["kimi", "--print", "--output-format", "stream-json", prompt],
        ["kimi", prompt],
    ]

    last_error = ""
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=KIMI_TIMEOUT,
            )
            if result.returncode == 0:
                return result.stdout or result.stderr
            last_error = result.stderr or f"exit code {result.returncode}"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            last_error = str(e)
            continue

    raise RuntimeError(f"All Kimi CLI invocation attempts failed: {last_error}")


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    prompt = build_prompt(req.messages)

    try:
        content = call_kimi(prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "id": "kimi-cli-llm-1",
        "object": "chat.completion",
        "created": 0,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "kimi",
                "object": "model",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "provider": "kimi-code-cli"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
