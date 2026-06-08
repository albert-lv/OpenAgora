#!/usr/bin/env python3
"""
Token-level Reward Demo for Arena + veRL

This demo shows how Arena's episode-level rewards are converted into
token-level rewards for veRL's PPO training loop.  It runs entirely in
mock mode -- no GPU, no real Arena server, no real LLM backend, no
torch / transformers / tensordict installation needed.

Usage:
    python3 examples/verl-integration/demo_token_reward.py
"""

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "python/arena-sdk/src")
sys.path.insert(0, "python/arena-verl/src")

# ------------------------------------------------------------------
# Mock heavy dependencies (torch, transformers, tensordict, verl)
# so the demo runs on any machine without GPU/CUDA.
# ------------------------------------------------------------------
import numpy as np


class MockTensor:
    def __init__(self, data, dtype=None):
        self.data = np.array(data, dtype=self._np_dtype(dtype))
        self.dtype = dtype or "float32"
        self.shape = self.data.shape

    def _np_dtype(self, dtype):
        mapping = {"float32": np.float32, "float64": np.float64,
                   "int32": np.int32, "int64": np.int64, "long": np.int64,
                   "bool": bool}
        return mapping.get(dtype, np.float32)

    def __getitem__(self, idx):
        return MockTensor(self.data[idx], self.dtype)

    def __setitem__(self, idx, value):
        if isinstance(value, MockTensor):
            self.data[idx] = value.data
        else:
            # scalar assignment to slice
            self.data[idx] = value

    def sum(self):
        return MockTensor([[self.data.sum()]], self.dtype)

    def cumsum(self, dim=0):
        return MockTensor(np.cumsum(self.data, axis=dim), self.dtype)

    def item(self):
        return float(self.data.flat[0]) if self.data.size == 1 else self.data.tolist()

    def tolist(self):
        return self.data.tolist()

    def __eq__(self, other):
        if isinstance(other, (int, float)):
            return MockTensor(self.data == other, "bool")
        return MockTensor(self.data == other.data, "bool")

    def __ne__(self, other):
        if isinstance(other, (int, float)):
            return MockTensor(self.data != other, "bool")
        return MockTensor(self.data != other.data, "bool")

    def __mul__(self, other):
        if isinstance(other, MockTensor):
            return MockTensor(self.data * other.data, self.dtype)
        return MockTensor(self.data * other, self.dtype)

    def __sub__(self, other):
        if isinstance(other, MockTensor):
            return MockTensor(self.data - other.data, self.dtype)
        return MockTensor(self.data - other, self.dtype)

    def __and__(self, other):
        return MockTensor(self.data & other.data, "bool")

    def all(self):
        return MockTensor([[bool(self.data.all())]], "bool")

    def long(self):
        return MockTensor(self.data.astype(np.int64), "int64")

    def cat(self, others, dim=0):
        arrs = [self.data] + [o.data for o in others]
        return MockTensor(np.concatenate(arrs, axis=dim), self.dtype)

    @classmethod
    def randint(cls, low, high, size):
        return MockTensor(np.random.randint(low, high, size), "int64")

    @classmethod
    def ones(cls, *shape, dtype="float32"):
        return MockTensor(np.ones(shape, dtype=np.float32), dtype)

    @classmethod
    def zeros(cls, *shape, dtype="float32"):
        return MockTensor(np.zeros(shape, dtype=np.float32), dtype)

    @classmethod
    def full(cls, shape, fill_value, dtype="float32"):
        return MockTensor(np.full(shape, fill_value, dtype=np.float32), dtype)

    @classmethod
    def arange(cls, n):
        return MockTensor(np.arange(n), "int64")

    @classmethod
    def tensor(cls, data, dtype="float32"):
        return MockTensor(np.array(data, dtype=np.float32), dtype)


# Build a package-like torch mock with submodules.
class TorchModule(MagicMock):
    """Mock that acts like the torch package."""

    Tensor = MockTensor
    float32 = "float32"
    int64 = "int64"
    long = "long"

    @staticmethod
    def cat(tensors, dim=0):
        arrs = [t.data for t in tensors]
        return MockTensor(np.concatenate(arrs, axis=dim), tensors[0].dtype)

    @staticmethod
    def allclose(a, b):
        return np.allclose(a.data, b.data)

    @staticmethod
    def ones_like(tensor):
        return MockTensor(np.ones_like(tensor.data), tensor.dtype)

    @staticmethod
    def zeros_like(tensor):
        return MockTensor(np.zeros_like(tensor.data), tensor.dtype)

    @staticmethod
    def ones(*shape, dtype="float32"):
        return MockTensor.ones(*shape, dtype=dtype)

    @staticmethod
    def zeros(*shape, dtype="float32"):
        return MockTensor.zeros(*shape, dtype=dtype)

    @staticmethod
    def full(shape, fill_value, dtype="float32"):
        return MockTensor.full(shape, fill_value, dtype)

    @staticmethod
    def arange(n):
        return MockTensor.arange(n)

    @staticmethod
    def randint(low, high, size):
        return MockTensor.randint(low, high, size)

    @staticmethod
    def tensor(data, dtype="float32"):
        return MockTensor.tensor(data, dtype)


torch_mod = TorchModule()
torch_mod.distributed = MagicMock()
torch_mod.distributed.device_mesh = MagicMock()
torch_mod.distributed.device_mesh.DeviceMesh = object
sys.modules["torch"] = torch_mod
sys.modules["torch.distributed"] = torch_mod.distributed
sys.modules["torch.distributed.device_mesh"] = torch_mod.distributed.device_mesh

sys.modules["tensordict"] = MagicMock()
sys.modules["tensordict"].TensorDict = MagicMock()


class MockTensorDict:
    def __init__(self, data, batch_size=None):
        self._data = data
        self.batch_size = batch_size

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def keys(self):
        return list(self._data.keys())

    def get(self, key, default=None):
        return self._data.get(key, default)


sys.modules["tensordict"].TensorDict = MockTensorDict


class MockAutoTokenizer:
    """Minimal tokenizer mock that behaves like GPT-2 tokenizer."""

    def __init__(self, vocab_size=50257):
        self.vocab_size = vocab_size
        self.eos_token_id = vocab_size - 1
        self.pad_token_id = self.eos_token_id
        self.padding_side = "right"
        self._word_to_id = {}
        self._next_id = 100

    @classmethod
    def from_pretrained(cls, name):
        return cls()

    def encode(self, text, add_special_tokens=True):
        if not text:
            return []
        words = text.split()
        ids = []
        for w in words:
            if w not in self._word_to_id:
                self._word_to_id[w] = self._next_id
                self._next_id += 1
            ids.append(self._word_to_id[w])
        if add_special_tokens and ids:
            ids.append(self.eos_token_id)
        return ids

    def decode(self, ids, skip_special_tokens=False):
        if not ids:
            return ""
        rev = {v: k for k, v in self._word_to_id.items()}
        words = []
        for i in ids:
            if i == self.eos_token_id and skip_special_tokens:
                continue
            words.append(rev.get(i, f"<id:{i}>"))
        return " ".join(words)

    def pad(self, encoded_inputs, padding="max_length", max_length=None,
            return_tensors=None, return_attention_mask=False):
        max_len = max(len(e["input_ids"]) for e in encoded_inputs)
        target_len = max_length or max_len
        padded_ids = []
        attn_masks = []
        for e in encoded_inputs:
            ids = list(e["input_ids"])
            pad_count = target_len - len(ids)
            if self.padding_side == "right":
                padded = ids + [self.pad_token_id] * pad_count
                mask = [1] * len(ids) + [0] * pad_count
            else:
                padded = [self.pad_token_id] * pad_count + ids
                mask = [0] * pad_count + [1] * len(ids)
            padded_ids.append(padded)
            attn_masks.append(mask)
        out = {"input_ids": MockTensor(padded_ids, "int64")}
        if return_attention_mask:
            out["attention_mask"] = MockTensor(attn_masks, "int64")
        return out


sys.modules["transformers"] = MagicMock()
sys.modules["transformers"].AutoTokenizer = MockAutoTokenizer

# Mock verl.
_mock_verl = MagicMock()
_mock_verl.DataProto = lambda **kw: MagicMock(**kw)
_mock_verl.utils.config.omega_conf_to_dataclass = lambda x: x
_mock_verl.workers.config.HFModelConfig = MagicMock
_mock_verl.workers.config.RolloutConfig = MagicMock
_mock_verl.workers.rollout.base.BaseRollout = object
sys.modules["verl"] = _mock_verl
sys.modules["verl.utils"] = MagicMock()
sys.modules["verl.utils.config"] = _mock_verl.utils.config
sys.modules["verl.workers"] = MagicMock()
sys.modules["verl.workers.config"] = _mock_verl.workers.config
sys.modules["verl.workers.rollout"] = MagicMock()
sys.modules["verl.workers.rollout.base"] = _mock_verl.workers.rollout.base

# Now we can import the real ArenaRolloutProvider.
from arena_verl.rollout_provider import ArenaRolloutProvider


class DemoDataProto:
    """Minimal DataProto stand-in for demo purposes."""

    def __init__(self, batch, non_tensor_batch=None, meta_info=None):
        self.batch = batch
        self.non_tensor_batch = non_tensor_batch or {}
        self.meta_info = meta_info or {}

    def __repr__(self):
        lines = ["DemoDataProto(", f"  batch keys: {list(self.batch.keys())}"]
        for k, v in self.batch.items():
            if hasattr(v, "shape"):
                lines.append(f"    {k}: {tuple(v.shape)} dtype={v.dtype}")
        lines.append(")")
        return "\n".join(lines)


def create_mock_rollout_result(reward: float, response_text: str):
    """Build a fake Arena rollout result with trajectory and reward."""
    return {
        "index": 0,
        "rollout_id": "demo-001",
        "task_id": "batch-0",
        "status": "success",
        "reward": reward,
        "trajectory": [
            {
                "rollout_id": "demo-001",
                "step_id": 0,
                "request": {"endpoint": "/v1/chat/completions", "model": "mock"},
                "response": {
                    "content": response_text,
                    "usage": {"prompt_tokens": 10, "completion_tokens": len(response_text.split())},
                    "logprobs": None,
                },
                "metadata": {},
            }
        ],
    }


def demo_build_responses():
    """Demo: how _build_responses turns trajectories into tensors."""
    print("=" * 60)
    print("Demo 1: _build_responses (trajectory → token tensors)")
    print("=" * 60)

    tokenizer = MockAutoTokenizer()

    results = [
        create_mock_rollout_result(reward=1.0, response_text="def add(a, b): return a + b"),
        create_mock_rollout_result(reward=0.0, response_text=""),  # empty response
        create_mock_rollout_result(reward=0.5, response_text="print('hello')"),
    ]

    provider = MagicMock()
    provider.tokenizer = tokenizer
    provider.config = MagicMock()
    provider.config.response_length = 16

    response_ids, response_mask, token_level_rewards = ArenaRolloutProvider._build_responses(
        provider, results, prompt_length=8, bsz=len(results)
    )

    print(f"\nBatch size: {len(results)}")
    print(f"Response length (max): {provider.config.response_length}")
    print(f"\nresponse_ids shape: {tuple(response_ids.shape)}")
    print(f"response_mask shape:  {tuple(response_mask.shape)}")
    print(f"token_level_rewards shape: {tuple(token_level_rewards.shape)}")

    print("\nPer-sample breakdown:")
    for i in range(len(results)):
        ids = response_ids[i]
        mask = response_mask[i]
        rewards = token_level_rewards[i]
        n_real = int(mask.sum().item())
        text = tokenizer.decode(ids.data[:n_real].tolist(), skip_special_tokens=True)
        print(f"\n  Sample {i}:")
        print(f"    episode_reward = {results[i]['reward']}")
        print(f"    decoded_text   = {text!r}")
        print(f"    real_tokens    = {n_real}")
        print(f"    raw rewards row= {rewards.data.tolist()}")
        print(f"    reward_vector  = {rewards[:n_real].tolist()}")
        print(f"    padding_rewards= {rewards[n_real:].tolist()}")

    assert response_ids.shape == (3, 16)
    assert response_mask.shape == (3, 16)
    assert token_level_rewards.shape == (3, 16)
    assert token_level_rewards.dtype == "float32"

    for i in range(3):
        n_real = int(response_mask[i].sum().item())
        if n_real > 0:
            expected_reward = results[i]["reward"]
            actual_rewards = token_level_rewards[i, :n_real]
            expected = MockTensor.full((n_real,), expected_reward, "float32")
            assert TorchModule.allclose(actual_rewards, expected), \
                f"Sample {i}: token rewards should all equal episode reward {expected_reward}"

    padding_mask = (response_mask.data == 0)
    assert np.all(token_level_rewards.data[padding_mask] == 0.0), \
        "Padding positions must have 0.0 reward"

    print("\n✅ All assertions passed.")


def demo_generate_sequences_shape():
    """Demo: generate_sequences returns correct DataProto with token-level rewards."""
    print("\n" + "=" * 60)
    print("Demo 2: generate_sequences output shape validation")
    print("=" * 60)

    tokenizer = MockAutoTokenizer()

    with patch("arena_verl.rollout_provider.ArenaClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.create_rollout.return_value = {
            "rollout_id": "demo-001",
            "proxy_url": "http://localhost:9999/v1",
            "token": "tok",
        }
        mock_client.wait.return_value = {"status": "success", "reward": 0.75}
        mock_client.get_trajectory.return_value = [
            {
                "rollout_id": "demo-001",
                "step_id": 0,
                "request": {"endpoint": "/v1/chat/completions", "model": "mock"},
                "response": {
                    "content": "return x + y",
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    "logprobs": None,
                },
                "metadata": {},
            }
        ]

        config = MagicMock()
        config.response_length = 16
        config.sampling = {}
        model_config = MagicMock()
        model_config.model_path = "gpt2"
        device_mesh = MagicMock()

        provider = ArenaRolloutProvider(
            config=config,
            model_config=model_config,
            device_mesh=device_mesh,
            arena_endpoint="localhost:9090",
            sandbox_image="mock:latest",
            llm_backend="http://localhost:8000/v1",
        )

        bsz, prompt_length = 2, 8
        input_ids = MockTensor.randint(0, 50000, (bsz, prompt_length))
        batch = MockTensorDict(
            {
                "input_ids": input_ids,
                "attention_mask": MockTensor.ones(bsz, prompt_length, dtype="int64"),
                "position_ids": MockTensor.arange(prompt_length),
            },
            batch_size=bsz,
        )
        prompts = DemoDataProto(
            batch=batch,
            non_tensor_batch={"raw_prompt": ["Write a function.", "Print hello."]},
        )

        output = provider.generate_sequences(prompts)

        print(f"\nOutput DataProto keys: {list(output.batch.keys())}")
        for k in output.batch.keys():
            v = output.batch[k]
            print(f"  {k}: {tuple(v.shape)} dtype={v.dtype}")

        assert "prompts" in output.batch.keys()
        assert "responses" in output.batch.keys()
        assert "response_mask" in output.batch.keys()
        assert "input_ids" in output.batch.keys()
        assert "attention_mask" in output.batch.keys()
        assert "position_ids" in output.batch.keys()
        assert "token_level_rewards" in output.batch.keys()

        assert output.batch["responses"].shape == (bsz, config.response_length)
        assert output.batch["token_level_rewards"].shape == (bsz, config.response_length)
        assert output.batch["input_ids"].shape == (bsz, prompt_length + config.response_length)

        response_mask = output.batch["response_mask"]
        token_rewards = output.batch["token_level_rewards"]
        for i in range(bsz):
            n_real = int(response_mask[i].sum().item())
            if n_real > 0:
                assert token_rewards[i, :n_real].sum().item() > 0, \
                    f"Sample {i}: real tokens must carry positive reward"
                assert np.all(token_rewards[i, n_real:].data == 0.0), \
                    f"Sample {i}: padding must be 0.0"

        print("\n✅ All shape and reward assertions passed.")


def main():
    print("\n🔧 Arena + veRL Token-level Reward Demo")
    print("   (mock mode — no GPU, no server, no torch install needed)\n")

    demo_build_responses()
    demo_generate_sequences_shape()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("""
Key take-aways:
1. Arena returns a single episode reward per rollout (e.g. 0/1 from pytest).
2. ArenaRolloutProvider broadcasts that reward to every response token.
3. The resulting `token_level_rewards` tensor has shape [bsz, response_length]
   and is 0.0 for all padding positions.
4. This plugs directly into veRL's PPO advantage computation:
       advantages = token_level_rewards - value_estimates
""")
    print("Demo complete — all checks passed. 🎉")


if __name__ == "__main__":
    main()
