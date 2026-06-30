"""OpenAI-compatible LLM backend powered by Claude Code or Kimi Code API.

The service name in docker-compose is "codex-llm" for backward compatibility,
but the Codex CLI itself cannot be routed to Kimi because it relies on OpenAI's
/v1/responses WebSocket API, which Kimi does not expose.  When
OPENAI_API_KEY == KIMI_API_KEY (the default compose setup), the codex provider
falls back to a direct Kimi Code API chat/completions call.
"""

import os
import subprocess
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Claude/Kimi LLM Backend")

PROVIDER = os.environ.get("MODEL_PROVIDER", "claude").lower()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY")
KIMI_BASE_URL = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")


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


def _call_kimi_api(prompt: str) -> str:
    """Direct Kimi Code API call for the codex backend fallback."""
    if not KIMI_API_KEY:
        raise RuntimeError("KIMI_API_KEY not set; cannot route codex backend to Kimi")

    messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": KIMI_MODEL,
        "messages": messages,
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 2048,
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{KIMI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
    return ""


def call_codex(prompt: str) -> str:
    """Return code from the codex backend.

    The official Codex CLI targets OpenAI's /v1/responses WebSocket API, which
    Kimi does not implement.  When KIMI_API_KEY is available we therefore fall
    back to a direct Kimi Code API chat/completions call so that the Code
    Colosseum "codex" agent still functions end-to-end.  Only when no Kimi key
    is configured do we attempt the real Codex CLI against OpenAI.
    """
    if KIMI_API_KEY:
        return _call_kimi_api(prompt)

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
        raise HTTPException(
            status_code=400, detail=f"Unknown MODEL_PROVIDER: {PROVIDER}"
        )

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
