"""OpenAI-compatible LLM backend powered by Kimi Code API.

Used as the OpenCode agent's LLM backend in Code Colosseum.
Forwards OpenAI-compatible chat completion requests to the Kimi Code API.
"""

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="OpenCode LLM Backend (Kimi)")

KIMI_API_KEY = os.environ.get("KIMI_API_KEY")
KIMI_BASE_URL = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")

DEFAULT_TIMEOUT = 120.0


class ChatCompletionRequest(BaseModel):
    model: str = KIMI_MODEL
    messages: list[dict[str, Any]]
    temperature: float | None = 0.3
    top_p: float | None = 0.9
    max_tokens: int | None = 2048
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    if not KIMI_API_KEY:
        raise HTTPException(
            status_code=500, detail="KIMI_API_KEY environment variable not set"
        )

    payload = {
        "model": req.model or KIMI_MODEL,
        "messages": req.messages,
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
    }
    if req.seed is not None:
        payload["seed"] = req.seed
    if req.logprobs is not None:
        payload["logprobs"] = req.logprobs
    if req.top_logprobs is not None:
        payload["top_logprobs"] = req.top_logprobs

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        try:
            response = await client.post(
                f"{KIMI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {KIMI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={k: v for k, v in payload.items() if v is not None},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Kimi API error: {e.response.text}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503, detail=f"Kimi API request failed: {e}"
            )


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": KIMI_MODEL,
                "object": "model",
            }
        ],
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": "kimi",
        "model": KIMI_MODEL,
        "base_url": KIMI_BASE_URL,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
