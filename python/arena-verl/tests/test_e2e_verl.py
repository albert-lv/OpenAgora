#!/usr/bin/env python3
"""Minimal end-to-end test for ArenaRolloutProvider.

Verifies:
1. generate_sequences() returns real response_ids (not all zeros).
2. response_mask.sum() > 0 (at least one real token is marked).
3. Data shapes match veRL conventions.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

import torch
from transformers import AutoTokenizer


class MockDataProto:
    """Minimal mock of verl.DataProto for testing."""

    def __init__(self, batch, non_tensor_batch=None, meta_info=None):
        import numpy as np
        self.batch = batch
        self.non_tensor_batch = {
            k: (np.array(v) if not isinstance(v, np.ndarray) else v)
            for k, v in (non_tensor_batch or {}).items()
        }
        self.meta_info = meta_info or {}


def make_mock_prompts(batch_size=2, prompt_length=8):
    """Create a fake prompt batch."""
    input_ids = torch.randint(0, 1000, (batch_size, prompt_length))
    attention_mask = torch.ones_like(input_ids)
    batch = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    non_tensor_batch = {
        "raw_prompt": [f"Solve task {i}" for i in range(batch_size)]
    }
    return MockDataProto(batch, non_tensor_batch)


class TestArenaRolloutProvider(unittest.TestCase):
    @patch("arena_verl.rollout_provider.ArenaClient")
    @patch("arena_verl.rollout_provider.AutoTokenizer.from_pretrained")
    def test_generate_sequences_returns_real_tokens(self, mock_tokenizer_cls, mock_client_cls):
        """Test that response_ids are not all zeros and response_mask is valid."""
        # ------------------------------------------------------------------
        # 1. Build a mock tokenizer that behaves like a real one.
        # ------------------------------------------------------------------
        vocab = {"hello": 1, "world": 2, "solve": 3, "task": 4, "done": 5}
        tokenizer = MagicMock(spec=AutoTokenizer)
        tokenizer.pad_token_id = 0
        tokenizer.eos_token_id = 0
        tokenizer.padding_side = "left"

        def encode(text, add_special_tokens=False):
            # deterministic fake encoding based on text length
            tokens = [vocab.get(w, 99) for w in text.lower().split() if w in vocab]
            if not tokens:
                tokens = [99]  # at least one token
            return tokens

        def decode(ids, skip_special_tokens=True):
            return " ".join(f"tok{i}" for i in ids)

        tokenizer.encode = encode
        tokenizer.decode = decode

        def pad(encoded_inputs, **kwargs):
            max_len = kwargs.get("max_length", 512)
            input_ids = []
            attn = []
            for item in encoded_inputs:
                ids = item["input_ids"]
                padding = [0] * (max_len - len(ids))
                input_ids.append(ids + padding)
                attn.append([1] * len(ids) + [0] * len(padding))
            return {
                "input_ids": torch.tensor(input_ids),
                "attention_mask": torch.tensor(attn),
            }

        tokenizer.pad = pad
        mock_tokenizer_cls.return_value = tokenizer

        # ------------------------------------------------------------------
        # 2. Mock ArenaClient so we don't need a real server.
        # ------------------------------------------------------------------
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Fake rollout response with a trajectory containing assistant messages.
        fake_trajectory = [
            {
                "response": {
                    "content": "hello world",
                    "role": "assistant",
                }
            },
            {
                "response": {
                    "content": "solve task done",
                    "role": "assistant",
                }
            },
        ]

        mock_client.create_rollout.return_value = {"rollout_id": "r-001"}
        mock_client.wait.return_value = {"status": "success", "reward": 1.0}
        mock_client.get_trajectory.return_value = fake_trajectory

        # ------------------------------------------------------------------
        # 3. Instantiate provider with minimal config mocks.
        # ------------------------------------------------------------------
        from arena_verl.rollout_provider import ArenaRolloutProvider

        config_mock = MagicMock()
        config_mock.sampling = {"temperature": 0.7}
        config_mock.response_length = 16

        model_config_mock = MagicMock()
        model_config_mock.model_path = "mock-model"

        device_mesh_mock = MagicMock()

        provider = ArenaRolloutProvider(
            config=config_mock,
            model_config=model_config_mock,
            device_mesh=device_mesh_mock,
            arena_endpoint="localhost:9090",
        )

        # ------------------------------------------------------------------
        # 4. Run generate_sequences.
        # ------------------------------------------------------------------
        prompts = make_mock_prompts(batch_size=2, prompt_length=8)
        output = provider.generate_sequences(prompts)

        # ------------------------------------------------------------------
        # 5. Assertions.
        # ------------------------------------------------------------------
        responses = output.batch["responses"]          # [bsz, response_length]
        response_mask = output.batch["response_mask"]   # [bsz, response_length]
        input_ids = output.batch["input_ids"]            # [bsz, prompt+response]

        print(f"responses shape: {responses.shape}")
        print(f"response_mask shape: {response_mask.shape}")
        print(f"input_ids shape: {input_ids.shape}")
        print(f"responses[0]: {responses[0].tolist()}")
        print(f"response_mask[0]: {response_mask[0].tolist()}")
        print(f"response_mask.sum(): {response_mask.sum().item()}")

        # A) response_ids must NOT be all zeros.
        self.assertFalse(
            (responses == 0).all().item(),
            "response_ids are all zeros – trajectory tokenization failed."
        )

        # B) response_mask must have at least one real token.
        self.assertGreater(
            response_mask.sum().item(),
            0,
            "response_mask.sum() == 0 – no real tokens marked."
        )

        # C) Shape sanity checks.
        bsz = prompts.batch["input_ids"].shape[0]
        prompt_len = prompts.batch["input_ids"].shape[1]
        self.assertEqual(responses.shape[0], bsz)
        self.assertEqual(response_mask.shape[0], bsz)
        self.assertEqual(input_ids.shape[0], bsz)
        self.assertEqual(input_ids.shape[1], prompt_len + responses.shape[1])

        # D) response_mask must be 1 where response is non-pad, 0 otherwise.
        for i in range(bsz):
            real_tokens = (responses[i] != tokenizer.pad_token_id).nonzero(as_tuple=True)[0]
            for idx in real_tokens:
                self.assertEqual(response_mask[i, idx].item(), 1)

        print("\n✅ All assertions passed – ArenaRolloutProvider produces valid response_ids and response_mask.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
