#!/usr/bin/env python3
"""
Minimal CPU PPO training demo with Arena Agent Loop.

This script demonstrates a complete RL training loop:
1. Load a tiny model (default: Qwen/Qwen3.5-0.8B)
2. For each training iteration, run Arena rollouts
3. Post-process outputs into tensors
4. Compute old logprobs and value estimates
5. Run PPO updates (policy + value)
6. Save checkpoints

Designed for CPU-only environments. No Ray, no FSDP, no vLLM.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

# Ray init (connect to cluster if available, else local)
import ray
RAY_ADDRESS = os.environ.get("RAY_ADDRESS")
if RAY_ADDRESS:
    ray.init(address=RAY_ADDRESS, ignore_reinit_error=True)
else:
    ray.init(ignore_reinit_error=True)

# Allow running inside the Docker image (/opt paths) or from the repo root.
for _arena_path in ("/opt/arena-verl/src", "/opt/arena-sdk/src"):
    if os.path.isdir(_arena_path) and _arena_path not in sys.path:
        sys.path.insert(0, _arena_path)

from arena_sdk.client import ArenaClient  # noqa: E402
from arena_verl.agent_loop import ArenaAgentLoop  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

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
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "2"))
MAX_PROMPT_LEN = int(os.environ.get("MAX_PROMPT_LEN", "64"))
MAX_RESPONSE_LEN = int(os.environ.get("MAX_RESPONSE_LEN", "128"))

# PPO hyperparameters
LEARNING_RATE = float(os.environ.get("LEARNING_RATE", "1e-5"))
PPO_EPOCHS = int(os.environ.get("PPO_EPOCHS", "4"))
CLIP_EPS = float(os.environ.get("CLIP_EPS", "0.2"))
VF_COEF = float(os.environ.get("VF_COEF", "0.5"))
ENT_COEF = float(os.environ.get("ENT_COEF", "0.01"))
MAX_GRAD_NORM = float(os.environ.get("MAX_GRAD_NORM", "1.0"))

# Training loop
NUM_ITERATIONS = int(os.environ.get("NUM_ITERATIONS", "2"))
CHECKPOINT_DIR = os.environ.get("CHECKPOINT_DIR", "/app/checkpoints")


def load_dataset(path: str):
    """Load Parquet dataset into list of dicts."""
    try:
        import pandas as pd

        df = pd.read_parquet(path)
    except Exception as e:
        logger.info(f"Failed to load {path}: {e}")
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


class ActorCritic(nn.Module):
    """Combined actor (CausalLM) and critic (value head) for PPO."""

    def __init__(self, model_name: str, use_lora: bool = True):
        super().__init__()
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        )
        if use_lora:
            lora_config = LoraConfig(
                r=8,
                lora_alpha=16,
                target_modules=["q_proj", "v_proj"],
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
            )
            self.model = get_peft_model(self.model, lora_config)
            self.model.print_trainable_parameters()
        hidden_size = self.model.config.hidden_size
        self.value_head = nn.Linear(hidden_size, 1)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=True,
        )
        # Normalize to float32 for stable policy/value computations.
        logits = outputs.logits.to(torch.float32)
        hidden_states = outputs.hidden_states[-1].to(torch.float32)
        values = self.value_head(hidden_states).squeeze(-1)
        return logits, values


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
        logger.info(f"\n--- Sample {idx} ---")
        out = await agent_loop.run(
            sampling_params={"temperature": 0.3, "top_p": 0.9},
            raw_prompt=sample["raw_prompt"],
            index=idx,
            extra_info=sample.get("extra_info", {}),
        )
        outputs.append(out)
        logger.info(f"reward={out.reward_score}, response_tokens={len(out.response_ids)}, logprobs={'yes' if out.response_logprobs else 'no'}")
    return outputs


def postprocess_to_tensors(outputs: list[AgentLoopOutput], tokenizer, pad_token_id: int = 0):
    """Convert AgentLoopOutputs into padded tensors."""
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


def gather_logprobs(logits: torch.Tensor, tokens: torch.Tensor) -> torch.Tensor:
    """Gather per-token log-probs for the given tokens."""
    log_probs = F.log_softmax(logits, dim=-1)
    return log_probs.gather(2, tokens.unsqueeze(-1)).squeeze(-1)


def compute_ppo_metrics(
    actor_critic: ActorCritic,
    batch: dict,
    pad_token_id: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Compute old logprobs, values and advantages for a collected batch."""
    prompts = batch["prompts"].to(DEVICE)
    responses = batch["responses"].to(DEVICE)
    response_mask = batch["response_mask"].to(DEVICE)
    rewards = batch["rewards"].to(DEVICE)

    full_input_ids = torch.cat([prompts, responses], dim=1)
    attention_mask = (full_input_ids != pad_token_id).long()

    with torch.no_grad():
        logits, values = actor_critic(full_input_ids, attention_mask)
        # Response tokens correspond to positions [prompt_len-1 : prompt_len+response_len-1]
        response_logits = logits[:, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :]
        response_values = values[:, MAX_PROMPT_LEN : MAX_PROMPT_LEN + MAX_RESPONSE_LEN]

        token_logprobs = gather_logprobs(response_logits, responses)
        # Sum over valid response tokens.
        seq_logprobs = (token_logprobs * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)
        seq_values = (response_values * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)

        # Treat the reward as the return for this simple demo.
        advantages = rewards - seq_values
        returns = rewards

    return seq_logprobs, seq_values, advantages, returns


def ppo_update(
    actor_critic: ActorCritic,
    optimizer: torch.optim.Optimizer,
    batch: dict,
    old_logprobs: torch.Tensor,
    advantages: torch.Tensor,
    returns: torch.Tensor,
    pad_token_id: int,
) -> dict:
    """Run one epoch of PPO update and return metrics."""
    import time
    prompts = batch["prompts"].to(DEVICE)
    responses = batch["responses"].to(DEVICE)
    response_mask = batch["response_mask"].to(DEVICE)

    full_input_ids = torch.cat([prompts, responses], dim=1)
    attention_mask = (full_input_ids != pad_token_id).long()

    t0 = time.time()
    logits, values = actor_critic(full_input_ids, attention_mask)
    t1 = time.time()
    response_logits = logits[:, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :]
    response_values = values[:, MAX_PROMPT_LEN : MAX_PROMPT_LEN + MAX_RESPONSE_LEN]

    token_logprobs = gather_logprobs(response_logits, responses)
    new_logprobs = (token_logprobs * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)

    value_est = (response_values * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)

    # PPO policy loss with clipping.
    ratio = torch.exp(new_logprobs - old_logprobs)
    surr1 = ratio * advantages
    surr2 = torch.clamp(ratio, 1 - CLIP_EPS, 1 + CLIP_EPS) * advantages
    policy_loss = -torch.min(surr1, surr2).mean()

    # Value loss.
    value_loss = F.mse_loss(value_est, returns)

    # Entropy bonus.
    entropy = -(torch.exp(token_logprobs) * token_logprobs * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)
    entropy_loss = -entropy.mean()

    loss = policy_loss + VF_COEF * value_loss + ENT_COEF * entropy_loss
    t2 = time.time()

    optimizer.zero_grad()
    loss.backward()
    t3 = time.time()
    trainable_params = [p for p in actor_critic.parameters() if p.requires_grad]
    nn.utils.clip_grad_norm_(trainable_params, MAX_GRAD_NORM)
    optimizer.step()
    t4 = time.time()

    logger.info(f"    fwd={t1-t0:.1f}s loss={t2-t1:.1f}s bwd={t3-t2:.1f}s step={t4-t3:.1f}s", flush=True)

    return {
        "loss": loss.item(),
        "policy_loss": policy_loss.item(),
        "value_loss": value_loss.item(),
        "entropy": entropy.mean().item(),
        "approx_kl": ((old_logprobs - new_logprobs) ** 2).mean().item() / 2,
    }


def save_checkpoint(actor_critic: ActorCritic, tokenizer, iteration: int):
    """Save actor-critic checkpoint."""
    checkpoint_path = Path(CHECKPOINT_DIR) / f"checkpoint-{iteration}"
    checkpoint_path.mkdir(parents=True, exist_ok=True)
    actor_critic.model.save_pretrained(checkpoint_path)
    tokenizer.save_pretrained(checkpoint_path)
    torch.save(actor_critic.value_head.state_dict(), checkpoint_path / "value_head.pt")
    logger.info(f"Checkpoint saved to {checkpoint_path}")


def main():
    logger.info("=" * 60)
    logger.info("Arena + veRL CPU PPO Demo Trainer")
    logger.info("=" * 60)
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Device: {DEVICE}")
    logger.info(f"Arena endpoint: {ARENA_ENDPOINT}")
    logger.info(f"LLM backend: {ARENA_LLM_BACKEND}")
    logger.info(f"PPO iterations: {NUM_ITERATIONS}, epochs/iteration: {PPO_EPOCHS}")
    logger.info()

    # ------------------------------------------------------------------
    # 1. Load model & tokenizer
    # ------------------------------------------------------------------
    logger.info("Loading model...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    actor_critic = ActorCritic(MODEL_NAME).to(DEVICE)
    logger.info(f"Model loaded: {sum(p.numel() for p in actor_critic.parameters()) / 1e6:.1f}M params")

    optimizer = torch.optim.AdamW(actor_critic.parameters(), lr=LEARNING_RATE)
    logger.info()

    # ------------------------------------------------------------------
    # 2. Load dataset
    # ------------------------------------------------------------------
    dataset = load_dataset(DATASET_PATH)
    logger.info(f"Dataset loaded: {len(dataset)} samples")
    logger.info()

    agent_loop = SimpleArenaAgentLoop(tokenizer=tokenizer)

    # ------------------------------------------------------------------
    # 3. Training loop
    # ------------------------------------------------------------------
    for iteration in range(1, NUM_ITERATIONS + 1):
        logger.info("\n" + "=" * 60)
        logger.info(f"Iteration {iteration}/{NUM_ITERATIONS}")
        logger.info("=" * 60)

        # 3a. Rollouts
        actor_critic.eval()
        outputs = asyncio.run(run_rollouts(agent_loop, dataset))

        # 3b. Post-process
        batch = postprocess_to_tensors(outputs, tokenizer, tokenizer.pad_token_id)
        logger.info("\nBatch tensor shapes")
        for k, v in batch.items():
            logger.info(f"  {k:20s}: {v.shape}  dtype={v.dtype}")

        # 3c. Compute old logprobs, values, advantages
        old_logprobs, old_values, advantages, returns = compute_ppo_metrics(
            actor_critic, batch, tokenizer.pad_token_id
        )

        avg_reward = batch["rewards"].mean().item()
        logger.info(f"\n  Avg reward:     {avg_reward:.4f}")
        logger.info(f"  Avg old logprob: {old_logprobs.mean().item():.4f}")
        logger.info(f"  Avg value:      {old_values.mean().item():.4f}")
        logger.info(f"  Avg advantage:  {advantages.mean().item():.4f}")

        # 3d. PPO updates
        actor_critic.train()
        logger.info("\nPPO updates")
        for epoch in range(PPO_EPOCHS):
            metrics = ppo_update(
                actor_critic,
                optimizer,
                batch,
                old_logprobs,
                advantages,
                returns,
                tokenizer.pad_token_id,
            )
            logger.info(
                f"  epoch {epoch + 1}/{PPO_EPOCHS}: "
                f"loss={metrics['loss']:.4f}, "
                f"policy_loss={metrics['policy_loss']:.4f}, "
                f"value_loss={metrics['value_loss']:.4f}, "
                f"entropy={metrics['entropy']:.4f}, "
                f"approx_kl={metrics['approx_kl']:.6f}"
            )

        # 3e. Save checkpoint
        save_checkpoint(actor_critic, tokenizer, iteration)

    logger.info("\n" + "=" * 60)
    logger.info("Training complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
