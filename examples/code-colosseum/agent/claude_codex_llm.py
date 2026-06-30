"""OpenAI-compatible LLM backend powered by Claude Code or Codex CLI."""

import os
import subprocess
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Claude/Codex LLM Backend")

PROVIDER = os.environ.get("MODEL_PROVIDER", "claude").lower()


class ChatCompletionRequest(BaseModel):
    model: str = "default"
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


def call_claude(prompt: str) -> str:
    """Call Claude Code CLI in non-interactive mode via Kimi Code API.

    --bare forces auth to come from ANTHROPIC_API_KEY only,
    avoiding interactive login.  ANTHROPIC_BASE_URL is set to Kimi Code's
    Anthropic-compatible endpoint so the underlying LLM calls hit Kimi.
    """
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = os.environ.get(
        "ANTHROPIC_BASE_URL", "https://api.kimi.com/coding/"
    )
    result = subprocess.run(
        [
            "claude",
            "-p",
            "--bare",
            "--dangerously-skip-permissions",
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return result.stdout or result.stderr


def call_codex(prompt: str) -> str:
    """Call OpenAI Codex CLI in non-interactive mode via Kimi Code API.

    OPENAI_BASE_URL is set to Kimi Code's OpenAI-compatible endpoint
    so the underlying LLM calls hit Kimi.
    """
    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = os.environ.get(
        "OPENAI_BASE_URL", "https://api.kimi.com/coding/v1"
    )
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            prompt,
        ],
        capture_output=True,
        text=True,
        input="",
        timeout=120,
        env=env,
    )
    return result.stdout or result.stderr


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    prompt = build_prompt(req.messages)

    if PROVIDER == "claude":
        content = call_claude(prompt)
    elif PROVIDER == "codex":
        content = call_codex(prompt)
    else:
        raise ValueError(f"Unknown MODEL_PROVIDER: {PROVIDER}")

    return {
        "id": "claude-codex-llm-1",
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
                "id": "claude-code" if PROVIDER == "claude" else "codex",
                "object": "model",
            }
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "provider": PROVIDER}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
