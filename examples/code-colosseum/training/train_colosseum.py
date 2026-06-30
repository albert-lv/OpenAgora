#!/usr/bin/env python3
"""
Code Colosseum GRPO training skeleton.

Adapts the CPU demo trainer to train on the Code Colosseum problem bank
using Group Relative Policy Optimization (GRPO).  For each problem the
policy samples a group of rollouts; rewards are normalized within the group
to produce advantages, and the critic / value network is removed.

The trainer also starts an OpenAI-compatible LLM server that serves the
current actor policy, so every Arena rollout uses the model being trained
in real time.
"""

import asyncio
import json
import logging
import os
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

for _arena_path in ("/opt/openagora-verl/src", "/opt/openagora-sdk/src"):
    if os.path.isdir(_arena_path) and _arena_path not in sys.path:
        sys.path.insert(0, _arena_path)

from openagora_sdk.client import ArenaClient  # noqa: E402
from openagora_verl.agent_loop import ArenaAgentLoop  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from problems import load_problems  # noqa: E402
from reward_shaper import compute_reward  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from llm_server import start_server  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)

try:
    from verl.experimental.agent_loop.agent_loop import AgentLoopOutput
except ImportError:

    class AgentLoopOutput:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
ARENA_ENDPOINT = os.environ.get("ARENA_ENDPOINT", "host.docker.internal:9090")
ARENA_AGENT_IMAGE = os.environ.get(
    "ARENA_AGENT_IMAGE", "openagora-code-colosseum-agent:latest"
)
ARENA_LLM_BACKEND = os.environ.get(
    "ARENA_LLM_BACKEND", "http://host.docker.internal:8000/v1"
)
ARENA_VERIFY_COMMAND = os.environ.get("ARENA_VERIFY_COMMAND", "true")
PROBLEMS_DIR = os.environ.get(
    "PROBLEMS_DIR", str(Path(__file__).parent.parent / "problems")
)
METRICS_PATH = Path(os.environ.get("METRICS_PATH", "/app/data/metrics.jsonl"))
CHECKPOINT_DIR = Path(os.environ.get("CHECKPOINT_DIR", "/app/checkpoints"))

DEVICE = "cpu"
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "1"))
MAX_PROMPT_LEN = int(os.environ.get("MAX_PROMPT_LEN", "64"))
MAX_RESPONSE_LEN = int(os.environ.get("MAX_RESPONSE_LEN", "128"))
LEARNING_RATE = float(os.environ.get("LEARNING_RATE", "1e-5"))
GRPO_EPOCHS = int(os.environ.get("GRPO_EPOCHS", os.environ.get("PPO_EPOCHS", "1")))
CLIP_EPS = float(os.environ.get("CLIP_EPS", "0.2"))
KL_COEF = float(os.environ.get("KL_COEF", "0.01"))
ENT_COEF = float(os.environ.get("ENT_COEF", "0.01"))
MAX_GRAD_NORM = float(os.environ.get("MAX_GRAD_NORM", "1.0"))
NUM_ITERATIONS = int(os.environ.get("NUM_ITERATIONS", "1"))
GROUP_SIZE = int(os.environ.get("GROUP_SIZE", "4"))
REWARD_EPS = float(os.environ.get("REWARD_EPS", "1e-4"))


class ActorModel(nn.Module):
    """Policy network for GRPO: no value head, only the actor."""

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

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=False,
        )
        return outputs.logits.to(torch.float32)


class ReferenceModel(nn.Module):
    """Frozen reference policy used for KL divergence in GRPO."""

    def __init__(self, model_name: str):
        super().__init__()
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        )
        for param in self.model.parameters():
            param.requires_grad = False
        self.eval()

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=False,
        )
        return outputs.logits.to(torch.float32)


class ColosseumAgentLoop(ArenaAgentLoop):
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
        self._timeout_seconds = 300
        self._arena = ArenaClient(ARENA_ENDPOINT)


def build_dataset():
    """Build a dataset from the problem bank."""
    os.environ["PROBLEMS_DIR"] = PROBLEMS_DIR
    problems = load_problems()
    records = []
    for problem in problems.values():
        task_file = problem.build_task_file()
        prompt = (
            f"Solve this problem:\n\n{problem.title}\n\n"
            f"{problem.description}\n\n"
            f"Function signature:\n{problem.function_signature}\n\n"
            f"Write only the Python solution."
        )
        records.append(
            {
                "index": problem.id,
                "raw_prompt": [
                    {
                        "role": "system",
                        "content": "You are an expert competitive programmer.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "extra_info": {
                    "openagora_verify": problem.build_verify_command(),
                    "task_file": task_file.decode("utf-8"),
                },
            }
        )
    return records


async def run_rollouts(
    agent_loop: ColosseumAgentLoop, dataset: list[dict], group_size: int
):
    """Sample ``group_size`` rollouts for each problem in the batch."""
    outputs = []
    for sample in dataset[:BATCH_SIZE]:
        idx = sample["index"]
        logger.info("\n--- Problem %s (group size %d) ---", idx, group_size)
        for g in range(group_size):
            # Vary seed per group member so the policy can explore diverse
            # completions for the same prompt.
            sampling = {
                "temperature": 0.7,
                "top_p": 0.9,
                "seed": random.randint(1, 1_000_000_000),
            }
            out = await agent_loop.run(
                sampling_params=sampling,
                raw_prompt=sample["raw_prompt"],
                index=idx,
                extra_info=sample.get("extra_info", {}),
            )
            # Apply shaped reward that combines correctness, efficiency and
            # step penalty into a normalized [0, 1] scalar.
            verification_report = out.extra_fields.get("verification_report")
            shaped_reward = compute_reward(verification_report, num_steps=out.num_turns)
            out.reward_score = shaped_reward
            outputs.append(out)
            print(f"  {idx}/{g + 1}: reward={out.reward_score:.4f}")
    return outputs


def postprocess_to_tensors(
    outputs: list, group_size: int, tokenizer, pad_token_id: int
):
    """Convert rollout outputs to tensors, keeping group membership."""
    batch_prompts = []
    batch_responses = []
    batch_masks = []
    batch_rewards = []
    batch_group_ids = []

    pad_token_id = pad_token_id or tokenizer.pad_token_id or 0

    for i, out in enumerate(outputs):
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
        batch_group_ids.append(i // group_size)

    return {
        "prompts": torch.tensor(batch_prompts, dtype=torch.long),
        "responses": torch.tensor(batch_responses, dtype=torch.long),
        "response_mask": torch.tensor(batch_masks, dtype=torch.long),
        "rewards": torch.tensor(batch_rewards, dtype=torch.float32),
        "group_ids": torch.tensor(batch_group_ids, dtype=torch.long),
    }


def gather_logprobs(logits: torch.Tensor, tokens: torch.Tensor) -> torch.Tensor:
    log_probs = F.log_softmax(logits, dim=-1)
    return log_probs.gather(2, tokens.unsqueeze(-1)).squeeze(-1)


def compute_group_advantages(
    rewards: torch.Tensor, group_ids: torch.Tensor, eps: float = REWARD_EPS
):
    """Compute group-relative advantages: (r - mean) / (std + eps)."""
    advantages = torch.zeros_like(rewards)
    for gid in torch.unique(group_ids, sorted=True):
        mask = group_ids == gid
        group_rewards = rewards[mask]
        mean_r = group_rewards.mean()
        std_r = group_rewards.std(unbiased=False) + eps
        advantages[mask] = (group_rewards - mean_r) / std_r
    return advantages


def compute_group_stats(batch: dict) -> list[dict]:
    """Return per-group reward statistics for logging."""
    group_ids = batch["group_ids"]
    rewards = batch["rewards"]
    stats = []
    for gid in torch.unique(group_ids, sorted=True):
        mask = group_ids == gid
        g = rewards[mask]
        stats.append(
            {
                "group": int(gid.item()),
                "mean": round(g.mean().item(), 4),
                "std": round(g.std(unbiased=False).item(), 4),
                "min": round(g.min().item(), 4),
                "max": round(g.max().item(), 4),
            }
        )
    return stats


def compute_grpo_metrics(
    actor_model: ActorModel,
    reference_model: ReferenceModel,
    batch: dict,
    pad_token_id: int,
):
    """Compute old-policy logprobs, reference logprobs and group-relative advantages."""
    prompts = batch["prompts"].to(DEVICE)
    responses = batch["responses"].to(DEVICE)
    response_mask = batch["response_mask"].to(DEVICE)
    rewards = batch["rewards"].to(DEVICE)
    group_ids = batch["group_ids"].to(DEVICE)

    full_input_ids = torch.cat([prompts, responses], dim=1)
    attention_mask = (full_input_ids != pad_token_id).long()

    with torch.no_grad():
        logits = actor_model(full_input_ids, attention_mask)
        ref_logits = reference_model(full_input_ids, attention_mask)
        response_logits = logits[
            :, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :
        ]
        ref_response_logits = ref_logits[
            :, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :
        ]

        token_logprobs = gather_logprobs(response_logits, responses)
        ref_token_logprobs = gather_logprobs(ref_response_logits, responses)
        seq_logprobs = (token_logprobs * response_mask).sum(dim=1) / (
            response_mask.sum(dim=1) + 1e-8
        )
        ref_seq_logprobs = (ref_token_logprobs * response_mask).sum(dim=1) / (
            response_mask.sum(dim=1) + 1e-8
        )

    advantages = compute_group_advantages(rewards, group_ids)

    return seq_logprobs, ref_seq_logprobs, advantages, rewards


def grpo_update(
    actor_model: ActorModel,
    reference_model: ReferenceModel,
    optimizer: torch.optim.Optimizer,
    batch: dict,
    old_logprobs: torch.Tensor,
    ref_logprobs: torch.Tensor,
    advantages: torch.Tensor,
    pad_token_id: int,
) -> dict:
    prompts = batch["prompts"].to(DEVICE)
    responses = batch["responses"].to(DEVICE)
    response_mask = batch["response_mask"].to(DEVICE)

    full_input_ids = torch.cat([prompts, responses], dim=1)
    attention_mask = (full_input_ids != pad_token_id).long()

    logits = actor_model(full_input_ids, attention_mask)
    response_logits = logits[
        :, MAX_PROMPT_LEN - 1 : MAX_PROMPT_LEN + MAX_RESPONSE_LEN - 1, :
    ]

    token_logprobs = gather_logprobs(response_logits, responses)
    new_logprobs = (token_logprobs * response_mask).sum(dim=1) / (
        response_mask.sum(dim=1) + 1e-8
    )

    ratio = torch.exp(new_logprobs - old_logprobs)
    surr1 = ratio * advantages
    surr2 = torch.clamp(ratio, 1 - CLIP_EPS, 1 + CLIP_EPS) * advantages
    policy_loss = -torch.min(surr1, surr2).mean()

    # KL divergence against the frozen reference policy using the k3 estimator.
    ref_log_ratio = ref_logprobs - new_logprobs
    kl_loss = (torch.exp(ref_log_ratio) - ref_log_ratio - 1.0).mean()

    entropy = -(torch.exp(token_logprobs) * token_logprobs * response_mask).sum(
        dim=1
    ) / (response_mask.sum(dim=1) + 1e-8)
    entropy_loss = -entropy.mean()

    loss = policy_loss + KL_COEF * kl_loss + ENT_COEF * entropy_loss

    optimizer.zero_grad()
    loss.backward()
    trainable_params = [p for p in actor_model.parameters() if p.requires_grad]
    nn.utils.clip_grad_norm_(trainable_params, MAX_GRAD_NORM)
    optimizer.step()

    approx_kl = ((ref_logprobs - new_logprobs) ** 2).mean().item() / 2
    return {
        "loss": loss.item(),
        "policy_loss": policy_loss.item(),
        "kl_loss": kl_loss.item(),
        "entropy": entropy.mean().item(),
        "approx_kl": approx_kl,
    }


def decode_sample(outputs: list, tokenizer) -> str:
    """Return the generated code text of the first rollout as a sample."""
    if not outputs:
        return ""
    first = outputs[0]
    response_ids = getattr(first, "response_ids", [])
    if not response_ids:
        return ""
    text = tokenizer.decode(response_ids, skip_special_tokens=True)
    return text.strip()


def write_metrics(
    step: int,
    avg_reward: float,
    group_stats: list[dict],
    group_rewards: list[list[float]],
    metrics: dict,
    outputs: list,
    tokenizer,
):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "step": step,
        "avg_reward": avg_reward,
        "policy_loss": metrics.get("policy_loss", 0.0),
        "kl_loss": metrics.get("kl_loss", 0.0),
        "kl": metrics.get("approx_kl", 0.0),
        "entropy": metrics.get("entropy", 0.0),
        "group_stats": group_stats,
        "group_rewards": group_rewards,
        "pass_at_k": 1.0 if avg_reward >= 0.95 else 0.0,
        "running": True,
        "sample": decode_sample(outputs, tokenizer),
    }
    with open(METRICS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("Metrics written: %s", record)


def collect_group_rewards(batch: dict) -> list[list[float]]:
    """Return per-group rollout rewards for visualization."""
    group_ids = batch["group_ids"]
    rewards = batch["rewards"]
    result = []
    for gid in torch.unique(group_ids, sorted=True):
        mask = group_ids == gid
        result.append(rewards[mask].tolist())
    return result


def find_latest_checkpoint() -> tuple[int, Path] | None:
    """Find the highest-numbered checkpoint directory."""
    if not CHECKPOINT_DIR.exists():
        return None
    latest_iter = -1
    latest_path = None
    for entry in CHECKPOINT_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith("checkpoint-"):
            try:
                it = int(entry.name.split("-")[-1])
            except ValueError:
                continue
            if it > latest_iter:
                latest_iter = it
                latest_path = entry
    if latest_path is None:
        return None
    return latest_iter, latest_path


def load_checkpoint(actor_model: ActorModel, tokenizer, checkpoint_path: Path):
    """Load actor and tokenizer from a checkpoint directory."""
    logger.info("Loading checkpoint from %s", checkpoint_path)
    actor_model.model = AutoModelForCausalLM.from_pretrained(
        checkpoint_path,
        trust_remote_code=True,
        torch_dtype=torch.float32,
    )
    # Re-apply LoRA if the saved model is not already PEFT.
    if not hasattr(actor_model.model, "peft_config"):
        lora_config = LoraConfig(
            r=8,
            lora_alpha=16,
            target_modules=["q_proj", "v_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        actor_model.model = get_peft_model(actor_model.model, lora_config)
    tokenizer_loaded = AutoTokenizer.from_pretrained(
        checkpoint_path, trust_remote_code=True
    )
    tokenizer.__dict__.update(tokenizer_loaded.__dict__)


def save_checkpoint(actor_model: ActorModel, tokenizer, iteration: int):
    checkpoint_path = CHECKPOINT_DIR / f"checkpoint-{iteration}"
    checkpoint_path.mkdir(parents=True, exist_ok=True)
    actor_model.model.save_pretrained(checkpoint_path)
    tokenizer.save_pretrained(checkpoint_path)
    logger.info("Checkpoint saved to %s", checkpoint_path)


def main():
    print("=" * 60)
    print("Code Colosseum GRPO Trainer")
    print("=" * 60)
    print(f"Model: {MODEL_NAME}")
    print(f"Arena: {ARENA_ENDPOINT}")
    print(f"LLM backend: {ARENA_LLM_BACKEND}")
    print(f"Problems: {PROBLEMS_DIR}")
    print(f"Group size: {GROUP_SIZE}")
    print(f"GRPO epochs: {GRPO_EPOCHS}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    actor_model = ActorModel(MODEL_NAME).to(DEVICE)
    # Frozen reference policy initialized from the base model.  It stays fixed
    # throughout training so the KL divergence term measures drift from the
    # starting point, which stabilizes GRPO updates.
    reference_model = ReferenceModel(MODEL_NAME).to(DEVICE)

    optimizer = torch.optim.AdamW(actor_model.parameters(), lr=LEARNING_RATE)

    latest = find_latest_checkpoint()
    start_iteration = 1
    if latest:
        it, path = latest
        load_checkpoint(actor_model, tokenizer, path)
        start_iteration = it + 1
        print(f"Resuming from checkpoint-{it}, starting at iteration {start_iteration}")

    # Serve the current policy as an OpenAI-compatible LLM backend.  Because
    # the server shares the same model object, each GRPO update is immediately
    # reflected in the next rollout's generations.
    llm_port = int(os.environ.get("POLICY_LLM_PORT", "8000"))
    llm_host = os.environ.get("POLICY_LLM_HOST", "0.0.0.0")
    llm_advertise_host = os.environ.get("POLICY_LLM_ADVERTISE_HOST", "localhost")
    start_server(actor_model.model, tokenizer, host=llm_host, port=llm_port)
    import time

    time.sleep(1)
    os.environ.setdefault(
        "ARENA_LLM_BACKEND", f"http://{llm_advertise_host}:{llm_port}/v1"
    )

    dataset = build_dataset()
    print(f"Dataset: {len(dataset)} problems")

    agent_loop = ColosseumAgentLoop(tokenizer=tokenizer)

    for iteration in range(start_iteration, NUM_ITERATIONS + 1):
        print()
        print(f"Iteration {iteration}/{NUM_ITERATIONS}")

        random.shuffle(dataset)
        actor_model.eval()
        outputs = asyncio.run(run_rollouts(agent_loop, dataset, GROUP_SIZE))

        batch = postprocess_to_tensors(
            outputs, GROUP_SIZE, tokenizer, tokenizer.pad_token_id
        )
        old_logprobs, ref_logprobs, advantages, returns = compute_grpo_metrics(
            actor_model, reference_model, batch, tokenizer.pad_token_id
        )

        avg_reward = batch["rewards"].mean().item()
        group_stats = compute_group_stats(batch)
        group_rewards = collect_group_rewards(batch)
        print(f"  Avg reward: {avg_reward:.4f}")
        print(f"  Group stats: {group_stats}")

        actor_model.train()
        print("GRPO updates")
        for epoch in range(GRPO_EPOCHS):
            metrics = grpo_update(
                actor_model,
                reference_model,
                optimizer,
                batch,
                old_logprobs,
                ref_logprobs,
                advantages,
                tokenizer.pad_token_id,
            )
            print(
                f"  epoch {epoch + 1}/{GRPO_EPOCHS}: "
                f"loss={metrics['loss']:.4f}, policy={metrics['policy_loss']:.4f}, "
                f"kl={metrics['kl_loss']:.4f}, entropy={metrics['entropy']:.4f}, "
                f"approx_kl={metrics['approx_kl']:.6f}"
            )

        write_metrics(
            iteration,
            avg_reward,
            group_stats,
            group_rewards,
            metrics,
            outputs,
            tokenizer,
        )
        save_checkpoint(actor_model, tokenizer, iteration)

    print("=" * 60)
    print("Training complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
