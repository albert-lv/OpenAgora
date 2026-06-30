#!/usr/bin/env python3
"""
CPU PPO training for the "relationship chat" scenario.

Goal: learn to reply to a girlfriend/wife in a way that avoids common pitfalls
and scores high on the hidden empathetic-reply rubric.

This trainer is a fork of examples/verl-integration/train_cpu.py with:
- A JSONL dataset of relationship scenarios.
- A custom Arena verify command that runs the rubric scorer inside the sandbox.
- Metrics logging (avg reward + verify success rate) to a JSONL file.
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
# Cap the object store to leave more host RAM for the model and PPO updates.
_ray_object_store_memory = int(os.environ.get("RAY_OBJECT_STORE_MEMORY", str(512 * 1024 * 1024)))
if RAY_ADDRESS:
    ray.init(address=RAY_ADDRESS, ignore_reinit_error=True)
else:
    ray.init(ignore_reinit_error=True, object_store_memory=_ray_object_store_memory)

# Allow running inside the Docker image (/opt paths) or from the repo root.
for _arena_path in ("/opt/openagora-verl/src", "/opt/openagora-sdk/src"):
    if os.path.isdir(_arena_path) and _arena_path not in sys.path:
        sys.path.insert(0, _arena_path)

from openagora_sdk.client import ArenaClient  # noqa: E402
from openagora_verl.agent_loop import ArenaAgentLoop  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

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
MODEL_NAME = os.environ.get("MODEL_NAME", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
DATASET_PATH = os.environ.get("DATASET_PATH", "/app/data/scenarios.jsonl")
ARENA_ENDPOINT = os.environ.get("ARENA_ENDPOINT", "host.docker.internal:9090")
ARENA_AGENT_IMAGE = os.environ.get("ARENA_AGENT_IMAGE", "relationship-chat-agent:latest")
ARENA_LLM_BACKEND = os.environ.get("ARENA_LLM_BACKEND", "http://host.docker.internal:11434/v1")
ARENA_LLM_MODEL = os.environ.get("ARENA_LLM_MODEL", "tinyllama")
# The verify command runs inside the agent sandbox, so it points to the scorer
# that is baked into the relationship-chat-agent image.
ARENA_VERIFY_COMMAND = os.environ.get(
    "ARENA_VERIFY_COMMAND",
    "python /app/score_response.py",
)
DEVICE = "cpu"
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "4"))
MAX_PROMPT_LEN = int(os.environ.get("MAX_PROMPT_LEN", "256"))
MAX_RESPONSE_LEN = int(os.environ.get("MAX_RESPONSE_LEN", "256"))

# PPO hyperparameters
LEARNING_RATE = float(os.environ.get("LEARNING_RATE", "2e-5"))
PPO_EPOCHS = int(os.environ.get("PPO_EPOCHS", "4"))
CLIP_EPS = float(os.environ.get("CLIP_EPS", "0.2"))
VF_COEF = float(os.environ.get("VF_COEF", "0.5"))
ENT_COEF = float(os.environ.get("ENT_COEF", "0.01"))
MAX_GRAD_NORM = float(os.environ.get("MAX_GRAD_NORM", "1.0"))

# Training loop
NUM_ITERATIONS = int(os.environ.get("NUM_ITERATIONS", "6"))
CHECKPOINT_DIR = os.environ.get("CHECKPOINT_DIR", "/app/checkpoints")
METRICS_PATH = os.environ.get("METRICS_PATH", "/app/data/metrics.jsonl")


def load_dataset(path: str):
    """Load JSONL dataset into list of dicts."""
    p = Path(path)
    if p.exists() and p.suffix == ".jsonl":
        records = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if isinstance(r.get("raw_prompt"), str):
                    r["raw_prompt"] = json.loads(r["raw_prompt"])
                records.append(r)
        return records

    logger.info(f"Dataset {path} not found, using in-memory fallback.")
    return [
        {
            "index": i,
            "raw_prompt": [
                {"role": "system", "content": "You are her caring boyfriend/husband. Please reply gently in English."},
                {"role": "user", "content": "You forgot our anniversary again. Do you even care about me?"},
            ],
            "extra_info": json.dumps({
                "task_file": json.dumps({
                    "prompt": "You forgot our anniversary again. Do you even care about me?",
                    "messages": [
                        {"role": "system", "content": "You are her caring boyfriend/husband. Please reply gently in English."},
                        {"role": "user", "content": "You forgot our anniversary again. Do you even care about me?"},
                    ],
                    "rubric": {
                        "must_avoid": ["forget it", "what's the big deal", "i'm busy"],
                        "must_include": ["sorry", "anniversary", "important"],
                    },
                }, ensure_ascii=False),
            }, ensure_ascii=False),
        }
        for i in range(4)
    ]


class ActorCritic(nn.Module):
    """Combined actor (CausalLM) and critic (value head) for PPO."""

    def __init__(self, model_name: str, use_lora: bool = True):
        super().__init__()
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.float32,
            local_files_only=True,
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
        # Trade compute for memory: recompute activations during backward pass.
        # use_reentrant=False is required so hidden_states are still returned.
        self.model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        hidden_size = self.model.config.hidden_size
        self.value_head = nn.Linear(hidden_size, 1, dtype=self.model.dtype)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=True,
        )
        logits = outputs.logits
        hidden_states = outputs.hidden_states[-1]
        values = self.value_head(hidden_states).squeeze(-1)
        return logits, values


class SimpleArenaAgentLoop(ArenaAgentLoop):
    """ArenaAgentLoop pre-configured for the relationship-chat CPU demo."""

    def __init__(self, tokenizer, **kwargs):
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
        self._timeout_seconds = int(os.environ.get("ARENA_TIMEOUT_SECONDS", "3600"))
        self._arena = ArenaClient(ARENA_ENDPOINT)


async def run_rollouts(agent_loop: SimpleArenaAgentLoop, dataset: list[dict]):
    """Run Arena rollouts for each sample and collect outputs."""
    outputs = []
    for sample in dataset[:BATCH_SIZE]:
        idx = sample["index"]
        logger.info(f"\n--- Sample {idx} ---")
        out = await agent_loop.run(
            sampling_params={"temperature": 0.7, "top_p": 0.9},
            raw_prompt=sample["raw_prompt"],
            index=idx,
            extra_info=sample.get("extra_info", {}),
        )
        outputs.append(out)
        print(
            f"  sample {idx}: reward={out.reward_score}, "
            f"response_tokens={len(out.response_ids)}, "
            f"logprobs={'yes' if out.response_logprobs else 'no'}"
        )
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

        p_ids = p_ids + [pad_token_id] * (MAX_PROMPT_LEN - len(p_ids))
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
        response_logits = logits[:, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :]
        response_values = values[:, MAX_PROMPT_LEN : MAX_PROMPT_LEN + MAX_RESPONSE_LEN]

        token_logprobs = gather_logprobs(response_logits, responses)
        seq_logprobs = (token_logprobs * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)
        seq_values = (response_values * response_mask).sum(dim=1) / (response_mask.sum(dim=1) + 1e-8)

        # Cast reward tensors to the model dtype so advantage math stays low-precision.
        rewards_t = rewards.to(logits.dtype)
        advantages = rewards_t - seq_values
        returns = rewards_t

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

    # Cast reference tensors to the model dtype to avoid float32 activation copies.
    old_logprobs = old_logprobs.to(logits.dtype)
    advantages = advantages.to(logits.dtype)
    returns = returns.to(logits.dtype)

    ratio = torch.exp(new_logprobs - old_logprobs)
    surr1 = ratio * advantages
    surr2 = torch.clamp(ratio, 1 - CLIP_EPS, 1 + CLIP_EPS) * advantages
    policy_loss = -torch.min(surr1, surr2).mean()

    value_loss = F.mse_loss(value_est, returns)

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


def write_metrics(iteration: int, rewards: torch.Tensor, metrics: dict):
    """Append training metrics to JSONL for dashboard / offline analysis."""
    Path(METRICS_PATH).parent.mkdir(parents=True, exist_ok=True)
    success_rate = (rewards > 0.0).float().mean().item()
    record = {
        "step": iteration,
        "avg_reward": rewards.mean().item(),
        "verify_success_rate": success_rate,
        "min_reward": rewards.min().item(),
        "max_reward": rewards.max().item(),
        **metrics,
    }
    with open(METRICS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _banner(msg: str):
    print("=" * 60)
    print(msg)
    print("=" * 60)


def main():
    _banner("Relationship Chat - Arena CPU PPO Trainer")
    print(f"Model: {MODEL_NAME}")
    print(f"Device: {DEVICE}")
    print(f"Arena endpoint: {ARENA_ENDPOINT}")
    print(f"LLM backend: {ARENA_LLM_BACKEND}")
    print(f"LLM model: {ARENA_LLM_MODEL}")
    print(f"Agent image: {ARENA_AGENT_IMAGE}")
    print(f"Verify command: {ARENA_VERIFY_COMMAND}")
    print(f"PPO iterations: {NUM_ITERATIONS}, epochs/iteration: {PPO_EPOCHS}")
    print()

    print("Loading model...")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME, trust_remote_code=True, local_files_only=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    actor_critic = ActorCritic(MODEL_NAME).to(DEVICE)
    print(f"Model loaded: {sum(p.numel() for p in actor_critic.parameters()) / 1e6:.1f}M params")
    print()

    # Only optimize trainable parameters (LoRA + value head) to keep CPU memory low.
    trainable_params = [p for p in actor_critic.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_params, lr=LEARNING_RATE)

    dataset = load_dataset(DATASET_PATH)
    print(f"Dataset loaded: {len(dataset)} samples")
    print()

    agent_loop = SimpleArenaAgentLoop(tokenizer=tokenizer)

    for iteration in range(1, NUM_ITERATIONS + 1):
        print()
        _banner(f"Iteration {iteration}/{NUM_ITERATIONS}")

        # 3a. Rollouts
        actor_critic.eval()
        outputs = asyncio.run(run_rollouts(agent_loop, dataset))

        # 3b. Post-process
        batch = postprocess_to_tensors(outputs, tokenizer, tokenizer.pad_token_id)
        print("\nBatch tensor shapes")
        for k, v in batch.items():
            print(f"  {k:20s}: {v.shape}  dtype={v.dtype}")

        # 3c. Compute old logprobs, values, advantages
        old_logprobs, old_values, advantages, returns = compute_ppo_metrics(
            actor_critic, batch, tokenizer.pad_token_id
        )

        avg_reward = batch["rewards"].mean().item()
        success_rate = (batch["rewards"] > 0.0).float().mean().item()
        print(f"\n  Avg reward:      {avg_reward:.4f}")
        print(f"  Verify success:  {success_rate:.2%}")
        print(f"  Avg old logprob: {old_logprobs.mean().item():.4f}")
        print(f"  Avg value:       {old_values.mean().item():.4f}")
        print(f"  Avg advantage:   {advantages.mean().item():.4f}")

        # 3d. PPO updates
        actor_critic.train()
        print("\nPPO updates")
        epoch_metrics = []
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
            epoch_metrics.append(metrics)
            print(
                f"  epoch {epoch + 1}/{PPO_EPOCHS}: "
                f"loss={metrics['loss']:.4f}, "
                f"policy_loss={metrics['policy_loss']:.4f}, "
                f"value_loss={metrics['value_loss']:.4f}, "
                f"entropy={metrics['entropy']:.4f}, "
                f"approx_kl={metrics['approx_kl']:.6f}"
            )

        write_metrics(
            iteration,
            batch["rewards"],
            {
                "policy_loss": sum(m["policy_loss"] for m in epoch_metrics) / len(epoch_metrics),
                "value_loss": sum(m["value_loss"] for m in epoch_metrics) / len(epoch_metrics),
                "entropy": sum(m["entropy"] for m in epoch_metrics) / len(epoch_metrics),
                "approx_kl": sum(m["approx_kl"] for m in epoch_metrics) / len(epoch_metrics),
            },
        )

        # 3e. Save checkpoint
        save_checkpoint(actor_critic, tokenizer, iteration)

    _banner("Training complete!")
    print(f"Checkpoints: {CHECKPOINT_DIR}")
    print(f"Metrics:     {METRICS_PATH}")


if __name__ == "__main__":
    main()
