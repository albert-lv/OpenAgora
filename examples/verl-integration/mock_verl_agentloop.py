#!/usr/bin/env python3
"""
Minimal mock of veRL's AgentLoopWorker to validate ArenaAgentLoop output format.

This script simulates what veRL does internally:
1. Prepare a batch of prompts (like DataProto.non_tensor_batch["raw_prompt"])
2. Call ArenaAgentLoop.run() for each sample
3. Post-process outputs into the tensor shapes veRL expects

No GPU / torch / ray required. Pure validation of the integration contract.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python/arena-verl/src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python/arena-sdk/src"))

# Mock veRL types if not installed.
try:
    from verl.experimental.agent_loop.agent_loop import AgentLoopOutput, AgentLoopMetrics
except ImportError:
    # Minimal stand-in matching the schema.
    from dataclasses import dataclass, field
    from typing import Optional

    class AgentLoopMetrics:
        def __init__(self, generate_sequences=0.0, tool_calls=0.0, compute_score=0.0, num_preempted=-1):
            self.generate_sequences = generate_sequences
            self.tool_calls = tool_calls
            self.compute_score = compute_score
            self.num_preempted = num_preempted

    class AgentLoopOutput:
        prompt_ids: list[int]
        response_ids: list[int]
        response_mask: list[int]
        response_logprobs: Optional[list[float]] = None
        routed_experts: Optional[any] = None
        multi_modal_data: Optional[dict] = None
        reward_score: Optional[float] = None
        num_turns: int = 0
        metrics: AgentLoopMetrics = field(default_factory=AgentLoopMetrics)
        extra_fields: dict = field(default_factory=dict)
        mm_processor_kwargs: Optional[dict] = None


class FakeTokenizer:
    """Minimal tokenizer stand-in."""

    def __init__(self):
        self.vocab = {"<pad>": 0, "<|im_start|>": 1, "user": 2, "assistant": 3, "def": 4, "add": 5}
        self.pad_token_id = 0

    def apply_chat_template(self, messages, add_generation_prompt=False, tokenize=False, **kwargs):
        out = ""
        for msg in messages:
            out += f"{msg['role']}: {msg['content']}\n"
        if add_generation_prompt:
            out += "assistant:"
        return out

    def encode(self, text, add_special_tokens=False):
        tokens = []
        for word in text.lower().split():
            word = word.strip(".,:!?\n")
            if word in self.vocab:
                tokens.append(self.vocab[word])
            else:
                tokens.append(7)  # generic token id
        return tokens


def mock_postprocess(outputs: list[AgentLoopOutput], prompt_length: int = 128, response_length: int = 128):
    """Simulate veRL's AgentLoopWorker._postprocess() to validate tensor shapes."""
    print("\n" + "=" * 60)
    print("Mock veRL Post-Process")
    print("=" * 60)

    bsz = len(outputs)
    print(f"Batch size: {bsz}")

    for i, out in enumerate(outputs):
        p_len = len(out.prompt_ids)
        r_len = len(out.response_ids)
        seq_len = p_len + r_len
        print(f"\nSample {i}:")
        print(f"  prompt_ids   : {p_len} tokens")
        print(f"  response_ids : {r_len} tokens")
        print(f"  sequence     : {seq_len} tokens")
        print(f"  response_mask: {out.response_mask}")
        print(f"  reward_score : {out.reward_score}")
        print(f"  num_turns    : {out.num_turns}")
        print(f"  extra_fields : {out.extra_fields}")

        # Validate shape constraints (like veRL does).
        assert len(out.response_ids) == len(out.response_mask), \
            "response_ids and response_mask must match!"
        if out.response_logprobs is not None:
            assert len(out.response_logprobs) == len(out.response_ids), \
                "response_logprobs must match response_ids length!"
            print(f"  logprobs     : {len(out.response_logprobs)} values ✓")
        else:
            print(f"  logprobs     : None (actor will recompute)")

    print("\n✅ All shape constraints satisfied. Output is veRL-compatible.")
    return {
        "batch_size": bsz,
        "samples": [
            {
                "prompt_ids": out.prompt_ids,
                "response_ids": out.response_ids,
                "response_mask": out.response_mask,
                "reward": out.reward_score,
            }
            for out in outputs
        ],
    }


async def main():
    import arena_verl.agent_loop as al_module
    al_module._VERL_AVAILABLE = True  # bypass check for mock
    from arena_verl.agent_loop import ArenaAgentLoop

    print("=" * 60)
    print("Mock veRL AgentLoopManager + ArenaAgentLoop")
    print("=" * 60)
    print()

    # Simulate two training samples.
    samples = [
        {
            "index": 0,
            "raw_prompt": [{"role": "user", "content": "Write a function add(a, b) that returns a + b."}],
        },
        {
            "index": 1,
            "raw_prompt": [{"role": "user", "content": "Write a function subtract(a, b) that returns a - b."}],
        },
    ]

    # Instantiate ArenaAgentLoop with a fake tokenizer.
    loop = ArenaAgentLoop.__new__(ArenaAgentLoop)
    loop._tokenizer = FakeTokenizer()
    loop._processor = None
    loop._prompt_length = 128
    loop._response_length = 128
    loop._agent_image = "arena-demo-agent:latest"
    loop._llm_backend = "http://localhost:11434/v1"
    loop._verify_command = "cd /sandbox && python -c \"from solution import add; assert add(2,3)==5; print('PASS')\""
    loop._timeout_seconds = 120
    from arena_sdk.client import ArenaClient
    loop._arena = ArenaClient("localhost:9090")

    outputs = []
    for sample in samples:
        print(f"Running sample {sample['index']} ...")
        out = await loop.run(
            sampling_params={"temperature": 0.3, "top_p": 0.9},
            **sample,
        )
        outputs.append(out)
        print(f"  -> reward={out.reward_score}, response_tokens={len(out.response_ids)}")

    # Validate against veRL post-process expectations.
    result = mock_postprocess(outputs)

    print()
    print("=" * 60)
    print("Mock training loop complete.")
    print("=" * 60)
    print()
    print("Summary:")
    print(f"  Successful rollouts: {result['batch_size']}")
    print(f"  Avg reward: {sum(s['reward'] or 0 for s in result['samples']) / len(result['samples']):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
