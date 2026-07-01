#!/usr/bin/env python3
"""
OpenAI-compatible LLM server for the Code Colosseum RL demo.

Serves the current actor policy so that Arena rollouts use the model being
trained.  Because the same ``transformers`` model object is shared with the
trainer, every GRPO update is immediately visible to the next rollout.
"""

import logging
import os
import threading
from typing import Optional

import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)

app = FastAPI(title="Code Colosseum Policy LLM Server")

# Populated by start_server().
_model: Optional[AutoModelForCausalLM] = None
_tokenizer: Optional[AutoTokenizer] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[dict]
    temperature: float = Field(0.7, ge=0.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    max_tokens: int = Field(1024, ge=1)
    seed: Optional[int] = None
    logprobs: bool = False
    top_logprobs: Optional[int] = Field(None, ge=0, le=20)


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "policy", "object": "model", "owned_by": "openagora-code-colosseum"}
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completion(req: ChatCompletionRequest):
    if _model is None or _tokenizer is None:
        return {"error": "Model not loaded"}, 503

    # Render the chat prompt.
    if hasattr(_tokenizer, "apply_chat_template") and _tokenizer.chat_template:
        prompt_text = _tokenizer.apply_chat_template(
            req.messages, tokenize=False, add_generation_prompt=True
        )
    else:
        prompt_text = "\n".join(
            f"<{m.get('role', 'user')}>\n{m.get('content', '')}\n</{m.get('role', 'user')}>"
            for m in req.messages
        )

    inputs = _tokenizer(prompt_text, return_tensors="pt", return_attention_mask=True)
    inputs = {k: v.to(_model.device) for k, v in inputs.items()}

    if req.seed is not None:
        torch.manual_seed(req.seed)

    # Cap generation length for the CPU demo so rollouts finish before proxy
    # timeouts while still leaving room for short coding solutions.
    max_new_tokens = min(
        req.max_tokens, int(os.environ.get("POLICY_MAX_TOKENS", "256"))
    )

    generate_kwargs = {
        "input_ids": inputs["input_ids"],
        "attention_mask": inputs["attention_mask"],
        "max_new_tokens": max_new_tokens,
        "do_sample": req.temperature > 1e-6,
        "temperature": max(req.temperature, 1e-3),
        "top_p": req.top_p,
        "pad_token_id": _tokenizer.pad_token_id,
        "eos_token_id": _tokenizer.eos_token_id,
        "return_dict_in_generate": True,
        "output_scores": req.logprobs,
    }

    _model.eval()
    with torch.no_grad():
        outputs = _model.generate(**generate_kwargs)

    input_len = inputs["input_ids"].shape[1]
    generated_ids = outputs.sequences[0, input_len:]
    content = _tokenizer.decode(generated_ids, skip_special_tokens=True)

    choice = {
        "index": 0,
        "message": {"role": "assistant", "content": content},
        "finish_reason": "stop",
    }

    if req.logprobs and outputs.scores:
        logprobs_content = []
        for i, score_tensor in enumerate(outputs.scores):
            if i >= len(generated_ids):
                break
            token_id = generated_ids[i].item()
            logprob = torch.log_softmax(score_tensor[0].float(), dim=-1)[
                token_id
            ].item()
            token_text = _tokenizer.decode([token_id])
            logprobs_content.append(
                {
                    "token": token_text,
                    "logprob": logprob,
                    "top_logprobs": [],
                }
            )
        choice["logprobs"] = {"content": logprobs_content}

    return {
        "id": "colosseum-policy-completion",
        "object": "chat.completion",
        "model": req.model or "policy",
        "choices": [choice],
        "usage": {
            "prompt_tokens": input_len,
            "completion_tokens": len(generated_ids),
            "total_tokens": input_len + len(generated_ids),
        },
    }


def start_server(
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> threading.Thread:
    """Start the LLM server in a background thread.

    Returns the server thread so the caller can keep it alive.
    """
    global _model, _tokenizer
    _model = model
    _tokenizer = tokenizer

    def _run():
        # Reduce uvicorn noise.
        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["loggers"]["uvicorn.access"]["level"] = "WARNING"
        uvicorn.run(
            app, host=host, port=port, log_level="warning", log_config=log_config
        )

    server_thread = threading.Thread(target=_run, daemon=True)
    server_thread.start()
    logger.info("Policy LLM server started on http://%s:%d/v1", host, port)
    return server_thread


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", default=os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model, trust_remote_code=True)
    model.eval()

    start_server(model, tokenizer, host=args.host, port=args.port)
    # Keep main thread alive.
    import time

    while True:
        time.sleep(60)
