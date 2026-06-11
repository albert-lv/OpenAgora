#!/usr/bin/env python3
"""
Minimal CPU GRPO training demo with Arena Agent Loop.

This script is a stripped-down trainer that demonstrates the full loop:
1. Load a tiny model (Qwen3.5-0.8B)
2. For each batch sample, call ArenaAgentLoop.run()
3. Post-process outputs into veRL-compatible DataProto
4. (Optional) Run one PPO update step

Designed for CPU-only environments. No Ray, no FSDP, no vLLM.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

# Ray init (connect to cluster if available, else local)
import ray
RAY_ADDRESS = os.environ.get("RAY_ADDRESS")
if RAY_ADDRESS:
    ray.init(address=RAY_ADDRESS, ignore_reinit_error=True)
    print(f"Connected to Ray cluster: {RAY_ADDRESS}")
else:
    ray.init(ignore_reinit_error=True)
    print("Ray running in local mode")

# Arena imports
sys.path.insert(0, "/opt/arena-verl/src")
sys.path.insert(0, "/opt/arena-sdk/src")

from arena_sdk.client import ArenaClient
from arena_verl.agent_loop import ArenaAgentLoop

# Mock veRL types if not available (standalone run)
try:
    from verl.experimental.agent_loop.agent_loop import AgentLoopOutput, AgentLoopMetrics
except ImportError:
    class AgentLoopMetrics:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AgentLoopOutput:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen3.5-0.8B")
DATASET_PATH = os.environ.get("DATASET_PATH", "/app/data/demo_dataset.parquet")
ARENA_ENDPOINT = os.environ.get("ARENA_ENDPOINT", "host.docker.internal:9090")
ARENA_AGENT_IMAGE = os.environ.get("ARENA_AGENT_IMAGE", "arena-agent-minimal:latest")
ARENA_LLM_BACKEND = os.environ.get("ARENA_LLM_BACKEND", "http://host.docker.internal:11434/v1")
ARENA_VERIFY_COMMAND = os.environ.get(
    "ARENA_VERIFY_COMMAND",
    "cd /sandbox && python -c 'from solution import add; assert add(2,3)==5; print(\"PASS\")'",
)
DEVICE = "cpu"
BATCH_SIZE = 2
MAX_PROMPT_LEN = 64
MAX_RESPONSE_LEN = 128


def load_dataset(path: str):
    """Load Parquet dataset into list of dicts."""
    try:
        import pandas as pd

        df = pd.read_parquet(path)
    except Exception as e:
        print(f"Failed to load {path}: {e}")
        # Fallback: generate in-memory
        return [
            {
                "index": i,
                "raw_prompt": [
                    {"role": "system", "content": "You are a helpful coding assistant."},
                    {"role": "user", "content": "Write a Python function `add(a, b)` that returns the sum of two integers."},
                ],
                "extra_info": json.dumps(
                    {"arena_verify": ARENA_VERIFY_COMMAND}
                ),
            }
            for i in range(4)
        ]

    records = df.to_dict("records")
    for r in records:
        if isinstance(r.get("raw_prompt"), str):
            r["raw_prompt"] = json.loads(r["raw_prompt"])
    return records


class SimpleArenaAgentLoop(ArenaAgentLoop):
    """ArenaAgentLoop pre-configured for the CPU demo environment."""

    def __init__(self, tokenizer, **kwargs):
        # Bypass veRL base init (no server_manager in CPU mode)
        self.tokenizer = tokenizer
        self.processor = None
        self.config = None
        self._tokenizer = tokenizer
        self._processor = None
        self._prompt_length = MAX_PROMPT_LEN
        self._response_length = MAX_RESPONSE_LEN
        self._agent_image = ARENA_AGENT_IMAGE
        self._llm_backend = ARENA_LLM_BACKEND
        self._verify_command = ARENA_VERIFY_COMMAND
        self._timeout_seconds = 300
        self._arena = ArenaClient(ARENA_ENDPOINT)


async def run_rollouts(agent_loop: SimpleArenaAgentLoop, dataset: list[dict]):
    """Run Arena rollouts for each sample and collect outputs."""
    outputs = []
    for sample in dataset[:BATCH_SIZE]:
        idx = sample["index"]
        print(f"\n--- Sample {idx} ---")
        out = await agent_loop.run(
            sampling_params={"temperature": 0.3, "top_p": 0.9},
            raw_prompt=sample["raw_prompt"],
            index=idx,
            extra_info=sample.get("extra_info", {}),
        )
        outputs.append(out)
        print(f"reward={out.reward_score}, response_tokens={len(out.response_ids)}, logprobs={'yes' if out.response_logprobs else 'no'}")
    return outputs


def postprocess_to_dataproto(outputs: list[AgentLoopOutput], tokenizer, pad_token_id: int = 0):
    """Convert AgentLoopOutputs into padded tensors (veRL DataProto style)."""
    batch_prompts = []
    batch_responses = []
    batch_masks = []
    batch_rewards = []

    for out in outputs:
        p_ids = out.prompt_ids[:MAX_PROMPT_LEN]
        r_ids = out.response_ids[:MAX_RESPONSE_LEN]
        mask = out.response_mask[:MAX_RESPONSE_LEN]

        # Pad prompt
        p_ids = p_ids + [pad_token_id] * (MAX_PROMPT_LEN - len(p_ids))
        # Pad response
        r_ids = r_ids + [pad_token_id] * (MAX_RESPONSE_LEN - len(r_ids))
        mask = mask + [0] * (MAX_RESPONSE_LEN - len(mask))

        batch_prompts.append(p_ids)
        batch_responses.append(r_ids)
        batch_masks.append(mask)
        batch_rewards.append(out.reward_score or 0.0)

    return {
        "prompts": torch.tensor(batch_prompts, dtype=torch.long),
        "responses": torch.tensor(batch_responses, dtype=torch.long),
        "response_mask": torch.tensor(batch_masks, dtype=torch.long),
        "rewards": torch.tensor(batch_rewards, dtype=torch.float32),
    }


def main():
    print("=" * 60)
    print("Arena + veRL CPU Demo Trainer")
    print("=" * 60)
    print(f"Model: {MODEL_NAME}")
    print(f"Device: {DEVICE}")
    print(f"Arena endpoint: {ARENA_ENDPOINT}")
    print(f"LLM backend: {ARENA_LLM_BACKEND}")
    print()

    # ------------------------------------------------------------------
    # 1. Load model & tokenizer
    # ------------------------------------------------------------------
    print("Loading model...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
        torch_dtype=torch.float32,
    ).to(DEVICE)
    model.eval()
    print(f"Model loaded: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M params")
    print()

    # ------------------------------------------------------------------
    # 2. Load dataset
    # ------------------------------------------------------------------
    dataset = load_dataset(DATASET_PATH)
    print(f"Dataset loaded: {len(dataset)} samples")
    print()

    # ------------------------------------------------------------------
    # 3. Run Arena rollouts
    # ------------------------------------------------------------------
    agent_loop = SimpleArenaAgentLoop(tokenizer=tokenizer)
    outputs = asyncio.run(run_rollouts(agent_loop, dataset))

    # ------------------------------------------------------------------
    # 4. Post-process to DataProto
    # ------------------------------------------------------------------
    batch = postprocess_to_dataproto(outputs, tokenizer, tokenizer.pad_token_id)
    print("\n" + "=" * 60)
    print("Batch tensor shapes (veRL DataProto compatible)")
    print("=" * 60)
    for k, v in batch.items():
        print(f"  {k:20s}: {v.shape}  dtype={v.dtype}")

    # ------------------------------------------------------------------
    # 5. (Optional) One PPO-style loss computation
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Computing policy loss (PPO-style)")
    print("=" * 60)

    with torch.no_grad():
        # Concatenate prompt + response for full sequence
        full_input_ids = torch.cat([batch["prompts"], batch["responses"]], dim=1).to(DEVICE)
        attention_mask = (full_input_ids != tokenizer.pad_token_id).long()

        outputs_logits = model(input_ids=full_input_ids, attention_mask=attention_mask)
        logits = outputs_logits.logits

        # Compute log-probs for response tokens
        response_logits = logits[:, MAX_PROMPT_LEN - 1 : -1, :]
        response_logprobs = F.log_softmax(response_logits, dim=-1)

        # Gather log-probs for actual response tokens
        response_tokens = batch["responses"].to(DEVICE)
        token_logprobs = response_logprobs.gather(2, response_tokens.unsqueeze(-1)).squeeze(-1)

        # Mask padding
        mask = batch["response_mask"].to(DEVICE)
        masked_logprobs = (token_logprobs * mask).sum(dim=1) / (mask.sum(dim=1) + 1e-8)

        # Simple policy gradient (REINFORCE-ish)
        rewards = batch["rewards"].to(DEVICE)
        baseline = rewards.mean()
        advantages = rewards - baseline

        loss = -(masked_logprobs * advantages).mean()

        print(f"  Avg reward:     {rewards.mean().item():.4f}")
        print(f"  Avg logprob:    {masked_logprobs.mean().item():.4f}")
        print(f"  Policy loss:    {loss.item():.4f}")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
