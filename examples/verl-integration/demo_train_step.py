#!/usr/bin/env python3
"""End-to-end demo: ArenaRolloutProvider with token-level rewards.

This script demonstrates a complete Arena + veRL integration flow without
requiring a real Arena server, Docker, vLLM, or GPU.  All external
dependencies are mocked so the demo is fully self-contained and runs in
seconds on CPU-only machines.

What it does:
    1. Mocks ArenaClient so no gRPC server is needed.
    2. Mocks the tokenizer so no HuggingFace model download is needed.
    3. Creates a fake veRL DataProto with prompts.
    4. Instantiates ArenaRolloutProvider.
    5. Calls generate_sequences() and verifies the output.
    6. Asserts token_level_rewards shape, dtype, and alignment with response_mask.

Run it directly from the repo root (no build steps needed):
    cd examples/verl-integration
    python demo_train_step.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List
from unittest.mock import MagicMock

import torch

# ------------------------------------------------------------------
# 1. Mock ArenaClient before arena_verl imports it.
# ------------------------------------------------------------------
class MockArenaClient:
    """Fake ArenaClient that returns deterministic success data."""

    def __init__(self, endpoint: str = "localhost:9090") -> None:
        self.endpoint = endpoint

    def create_rollout(self, **kwargs: Any) -> Dict[str, Any]:
        return {
            "rollout_id": "mock-rollout-1",
            "proxy_url": "http://mock:8000",
            "token": "mock-token",
        }

    def wait(self, rollout_id: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "rollout_id": rollout_id,
            "task_id": "batch-0",
            "status": "success",
            "reward": 1.0,
        }

    def get_trajectory(self, rollout_id: str) -> List[Dict[str, Any]]:
        # Return a single-step trajectory with a Python print statement.
        return [
            {
                "rollout_id": rollout_id,
                "step_id": 0,
                "request": {
                    "endpoint": "http://mock:8000/v1",
                    "model": "gpt-mock",
                    "messages": [{"role": "user", "content": "Write a Python function"}],
                },
                "response": {
                    "content": "print('hello world')",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 6},
                    "logprobs": {
                        "content": [
                            {"token": "print", "logprob": -0.1},
                            {"token": "(", "logprob": -0.1},
                            {"token": "'", "logprob": -0.1},
                            {"token": "hello", "logprob": -0.1},
                            {"token": "'", "logprob": -0.1},
                            {"token": ")", "logprob": -0.1},
                        ]
                    },
                },
                "metadata": {},
            }
        ]

    def close(self) -> None:
        pass


# Inject the mock client into arena_sdk before importing arena_verl.
import arena_sdk.client as _arena_client_module

_arena_client_module.ArenaClient = MockArenaClient  # type: ignore[misc]

# ------------------------------------------------------------------
# 2. Import ArenaRolloutProvider (now it will use MockArenaClient).
# ------------------------------------------------------------------
try:
    from arena_verl import ArenaRolloutProvider
except Exception as exc:  # pragma: no cover
    print(f"ERROR: Failed to import ArenaRolloutProvider: {exc}")
    print("Make sure arena-verl is installed:  pip install -e python/arena-verl")
    sys.exit(1)

# veRL imports are optional – if they fail we skip the DataProto path.
try:
    from verl import DataProto
    from tensordict import TensorDict

    _HAS_VERL = True
except Exception:  # pragma: no cover
    _HAS_VERL = False
    DataProto = None  # type: ignore[misc,assignment]
    TensorDict = None  # type: ignore[misc,assignment]


# ------------------------------------------------------------------
# 3. Mock tokenizer (tiny vocab, no network download).
# ------------------------------------------------------------------
class MockTokenizer:
    """Minimal tokenizer sufficient for ArenaRolloutProvider._build_responses."""

    def __init__(self) -> None:
        self.vocab = {
            "<pad>": 0,
            "<eos>": 1,
            "print": 2,
            "(": 3,
            ")": 4,
            "'": 5,
            "hello": 6,
            "world": 7,
            "def": 8,
            "return": 9,
        }
        self.pad_token_id = 0
        self.eos_token_id = 1
        self.padding_side = "left"

    def encode(self, text: str, add_special_tokens: bool = False) -> List[int]:
        tokens = text.strip().split()
        return [self.vocab.get(t, 6) for t in tokens]

    def decode(self, ids, skip_special_tokens: bool = False) -> str:
        inv = {v: k for k, v in self.vocab.items()}
        if isinstance(ids, torch.Tensor):
            ids = ids.tolist()
        return " ".join([inv.get(i, "<unk>") for i in ids])

    def pad(self, encoded_inputs, padding="max_length", max_length=512, return_tensors="pt", return_attention_mask=True):
        batch_size = len(encoded_inputs)
        input_ids = torch.zeros(batch_size, max_length, dtype=torch.long)
        attention_mask = torch.zeros(batch_size, max_length, dtype=torch.long)

        for i, item in enumerate(encoded_inputs):
            ids = item["input_ids"]
            n = len(ids)
            if self.padding_side == "right":
                input_ids[i, :n] = torch.tensor(ids, dtype=torch.long)
                attention_mask[i, :n] = 1
            else:
                input_ids[i, -n:] = torch.tensor(ids, dtype=torch.long)
                attention_mask[i, -n:] = 1

        result = {"input_ids": input_ids}
        if return_attention_mask:
            result["attention_mask"] = attention_mask
        return result


# ------------------------------------------------------------------
# 4. Mock configs for provider init.
# ------------------------------------------------------------------
@dataclass
class MockRolloutConfig:
    response_length: int = 64
    sampling: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockHFModelConfig:
    model_path: str = "gpt-mock"


# ------------------------------------------------------------------
# 5. Build a fake DataProto.
# ------------------------------------------------------------------
def build_fake_prompts(batch_size: int = 2, prompt_length: int = 10) -> Any:
    """Return a DataProto that looks like a real veRL prompt batch."""
    if not _HAS_VERL:
        # Fallback: return a plain dict if verl is not installed.
        prompt_ids = torch.randint(0, 100, (batch_size, prompt_length))
        return {
            "batch": {
                "input_ids": prompt_ids,
                "attention_mask": torch.ones(batch_size, prompt_length),
                "position_ids": torch.arange(prompt_length).unsqueeze(0).expand(batch_size, -1),
            },
            "non_tensor_batch": {
                "raw_prompt": [
                    "Write a Python function to print hello",
                    "Write a Python script that outputs hello",
                ]
            },
            "meta_info": {},
        }

    prompt_ids = torch.randint(0, 100, (batch_size, prompt_length))
    batch = TensorDict(
        {
            "input_ids": prompt_ids,
            "attention_mask": torch.ones(batch_size, prompt_length),
            "position_ids": torch.arange(prompt_length).unsqueeze(0).expand(batch_size, -1),
        },
        batch_size=batch_size,
    )
    return DataProto(
        batch=batch,
        non_tensor_batch={
            "raw_prompt": [
                "Write a Python function to print hello",
                "Write a Python script that outputs hello",
            ]
        },
        meta_info={},
    )


# ------------------------------------------------------------------
# 6. Main demo.
# ------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("Arena + veRL End-to-End Demo (token-level rewards)")
    print("=" * 70)

    # 6a. Create provider.
    provider = ArenaRolloutProvider(
        config=MockRolloutConfig(response_length=64),
        model_config=MockHFModelConfig(model_path="gpt-mock"),
        device_mesh=MagicMock(),
        arena_endpoint="localhost:9090",
        sandbox_image="mock:latest",
        llm_backend="http://mock:8000/v1",
        verify_command="pytest -k test",
        max_concurrent=4,
    )
    # Inject the mock tokenizer so no HF download happens.
    provider.tokenizer = MockTokenizer()

    print("\nProvider created successfully (mock client + mock tokenizer).")

    # 6b. Build fake prompts.
    gen_batch = build_fake_prompts(batch_size=2, prompt_length=10)
    print(f"Fake prompt batch built: bsz=2, prompt_length=10")

    # 6c. Generate sequences.
    print("\nCalling generate_sequences() ...")
    output = provider.generate_sequences(gen_batch)
    print("Done.")

    # 6d. Verify output fields.
    print("\n" + "-" * 70)
    print("Output field inspection")
    print("-" * 70)

    if _HAS_VERL and hasattr(output, "batch"):
        for key in output.batch.keys():
            tensor = output.batch[key]
            print(f"  {key:25s}  shape={list(tensor.shape)}  dtype={tensor.dtype}")
    else:
        print("  (verl not installed – skipping detailed field inspection)")

    # 6e. Assert token_level_rewards.
    print("\n" + "-" * 70)
    print("Assertion checks")
    print("-" * 70)

    if not _HAS_VERL:
        print("  verl / tensordict not installed – skipping tensor assertions.")
        print("  Install with:  pip install -e python/arena-verl")
        print("  Demo completed (mock-only mode).")
        return

    assert "token_level_rewards" in output.batch, "token_level_rewards missing from DataProto!"
    tlr = output.batch["token_level_rewards"]
    assert tlr.shape == (2, 64), f"Shape mismatch: expected (2, 64), got {tlr.shape}"
    assert tlr.dtype == torch.float32, f"Dtype mismatch: expected float32, got {tlr.dtype}"
    print("  [PASS] token_level_rewards exists with shape (2, 64) and dtype float32")

    response_mask = output.batch["response_mask"]
    for i in range(2):
        valid_tokens = int(response_mask[i].sum().item())
        if valid_tokens > 0:
            expected_per_token = 1.0 / valid_tokens
            valid_rewards = tlr[i, response_mask[i] == 1]
            assert torch.allclose(
                valid_rewards, torch.full_like(valid_rewards, expected_per_token)
            ), f"Token rewards for sample {i} don't match expected value {expected_per_token}"
            pad_rewards = tlr[i, response_mask[i] == 0]
            assert torch.all(pad_rewards == 0), f"Pad tokens for sample {i} should have 0 reward"
            print(f"  [PASS] sample {i}: valid_tokens={valid_tokens}, reward_per_token={expected_per_token:.4f}")
        else:
            assert torch.all(tlr[i] == 0), f"Empty response should have all-zero rewards"
            print(f"  [PASS] sample {i}: no valid tokens, all zeros")

    # 6f. Verify episode reward conservation.
    episode_rewards = tlr.sum(dim=-1)
    print(f"\n  Episode rewards (sum over response_length): {episode_rewards.tolist()}")
    assert torch.allclose(episode_rewards, torch.tensor([1.0, 1.0])), "Episode reward should be conserved (1.0 per sample)"
    print("  [PASS] Episode reward conserved (sum == 1.0 for each sample)")

    print("\n" + "=" * 70)
    print("All assertions passed!")
    print("token_level_rewards is correctly shaped, aligned with response_mask,")
    print("and preserves the original episode reward (1.0 per sample).")
    print("=" * 70)

    # 6g. Optional: print a pretty preview of the decoded response.
    print("\nDecoded response (sample 0):")
    print("  ", provider.tokenizer.decode(output.batch["responses"][0]))


if __name__ == "__main__":
    main()
