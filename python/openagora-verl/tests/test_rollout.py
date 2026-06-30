"""Unit tests for ArenaRollout."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

torch = pytest.importorskip("torch", reason="torch required for ArenaRollout tests")

# Only mock veRL if it is not already installed (e.g. local dev without GPU).
_vereal_available = False
try:
    import verl  # noqa: F401

    _vereal_available = True
except ImportError:
    _mock_verl = MagicMock()
    _mock_verl.workers = MagicMock()
    _mock_verl.workers.rollout = MagicMock()
    _mock_verl.workers.config = MagicMock()
    sys.modules["verl"] = _mock_verl
    sys.modules["verl.workers"] = _mock_verl.workers
    sys.modules["verl.workers.rollout"] = _mock_verl.workers.rollout
    sys.modules["verl.workers.rollout.base"] = _mock_verl.workers.rollout
    sys.modules["verl.workers.config"] = _mock_verl.workers.config

# test_agent_loop.py may have polluted sys.modules with a mock verl.
# Clean it up so rollout.py sees the real veRL (available in Docker).
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith("verl") or mod_name.startswith("openagora_verl"):
        del sys.modules[mod_name]

from openagora_verl.rollout import ArenaRollout, _VERL_AVAILABLE  # noqa: E402


class FakeTokenizer:
    """Minimal tokenizer stand-in."""

    def __init__(self):
        self.pad_token_id = 0

    def decode(self, ids, skip_special_tokens=False):
        return " ".join(str(i) for i in ids)

    def encode(self, text, add_special_tokens=False):
        return [
            int(x)
            for x in text.split()
            if x.isdigit() or (x.startswith("-") and x[1:].isdigit())
        ]


@pytest.fixture
def fake_tokenizer():
    return FakeTokenizer()


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.create_rollout.return_value = {"rollout_id": "r-123"}
    client.wait.return_value = {"status": "success", "reward": 1.0}
    client.get_trajectory.return_value = [
        {
            "response": {
                "choices_json": b'[{"message": {"content": "1 2 3"}}]',
                "logprobs_json": b'{"content": [{"token": "1", "logprob": -0.1}, {"token": "2", "logprob": -0.2}, {"token": "3", "logprob": -0.3}]}',
            }
        }
    ]
    return client


class TestArenaRollout:
    def test_init(self, fake_tokenizer):
        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer
        rollout = ArenaRollout(
            config=MagicMock(),
            model_config=model_config,
            device_mesh=None,
            arena_endpoint="localhost:9090",
            arena_agent_image="test:latest",
        )
        assert rollout._arena_endpoint == "localhost:9090"
        assert rollout._agent_image == "test:latest"

    def test_init_no_tokenizer_raises(self):
        class NoTokenizerConfig:
            pass

        with pytest.raises(RuntimeError, match="tokenizer"):
            ArenaRollout(
                config=MagicMock(),
                model_config=NoTokenizerConfig(),
                device_mesh=None,
            )

    def test_extract_response_text(self, fake_tokenizer):
        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer
        rollout = ArenaRollout(
            config=MagicMock(),
            model_config=model_config,
            device_mesh=None,
        )
        trajectory = [
            {"response": {"choices_json": b'[{"message": {"content": "hello"}}]'}},
            {"response": {"choices_json": b'[{"message": {"content": "world"}}]'}},
        ]
        assert rollout._extract_response_text(trajectory) == "hello\nworld"

    def test_extract_logprobs(self, fake_tokenizer):
        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer
        rollout = ArenaRollout(
            config=MagicMock(),
            model_config=model_config,
            device_mesh=None,
        )
        trajectory = [
            {
                "response": {
                    "logprobs_json": b'{"content": [{"token": "a", "logprob": -0.5}, {"token": "b", "logprob": -0.6}]}',
                }
            }
        ]
        result = rollout._extract_logprobs(trajectory, 3)
        assert result == [-0.5, -0.6, 0.0]

    def test_empty_result(self, fake_tokenizer):
        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer
        rollout = ArenaRollout(
            config=MagicMock(),
            model_config=model_config,
            device_mesh=None,
        )
        result = rollout._empty_result(4)
        assert result["response_ids"] == []
        assert result["log_probs"] == [0.0, 0.0, 0.0, 0.0]
        assert result["status"] == "failed"

    @patch("openagora_sdk.client.ArenaClient")
    @pytest.mark.skipif(not _VERL_AVAILABLE, reason="veRL not installed")
    def test_generate_sequences(self, mock_client_cls, fake_tokenizer, mock_client):
        mock_client_cls.return_value = mock_client

        # Ensure veRL types are real in Docker.
        config = MagicMock()
        config.temperature = 0.7
        config.top_p = 0.9
        config.seed = 42
        config.response_length = 8
        config.n = 1

        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer

        rollout = ArenaRollout(
            config=config,
            model_config=model_config,
            device_mesh=None,
            arena_endpoint="localhost:9090",
            max_concurrent=2,
        )

        # Build a fake input DataProto.
        import torch

        batch_size = 2
        prompt_length = 4
        input_ids = torch.tensor([[1, 2, 3, 0], [4, 5, 6, 0]], dtype=torch.long)
        attention_mask = torch.tensor([[1, 1, 1, 0], [1, 1, 1, 0]], dtype=torch.long)
        position_ids = (
            torch.arange(prompt_length).unsqueeze(0).expand(batch_size, prompt_length)
        )

        # Use real DataProto if available.
        try:
            from verl import DataProto

            prompts = DataProto.from_single_dict(
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "position_ids": position_ids,
                },
                meta_info={"eos_token_id": [2]},
            )
        except Exception:
            prompts = MagicMock()
            prompts.batch = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
            }
            prompts.meta_info = {"eos_token_id": [2]}

        output = rollout.generate_sequences(prompts)

        # Verify output structure.
        assert "responses" in output.batch
        assert "sequences" in output.batch
        assert "attention_mask" in output.batch
        assert "position_ids" in output.batch
        assert "old_log_probs" in output.batch
        mock_client.create_rollout.assert_called()

    @patch("openagora_sdk.client.ArenaClient")
    @pytest.mark.skipif(not _VERL_AVAILABLE, reason="veRL not installed")
    def test_generate_sequences_n_greater_than_one(
        self, mock_client_cls, fake_tokenizer, mock_client
    ):
        mock_client_cls.return_value = mock_client

        config = MagicMock()
        config.temperature = 0.7
        config.top_p = 0.9
        config.seed = 42
        config.response_length = 8
        config.n = 3  # n>1 for GRPO.

        model_config = MagicMock()
        model_config.tokenizer = fake_tokenizer

        rollout = ArenaRollout(
            config=config,
            model_config=model_config,
            device_mesh=None,
            arena_endpoint="localhost:9090",
            max_concurrent=4,
        )

        import torch

        batch_size = 2
        prompt_length = 4
        input_ids = torch.tensor([[1, 2, 3, 0], [4, 5, 6, 0]], dtype=torch.long)
        attention_mask = torch.tensor([[1, 1, 1, 0], [1, 1, 1, 0]], dtype=torch.long)
        position_ids = (
            torch.arange(prompt_length).unsqueeze(0).expand(batch_size, prompt_length)
        )

        try:
            from verl import DataProto

            prompts = DataProto.from_single_dict(
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "position_ids": position_ids,
                },
                meta_info={"eos_token_id": [2]},
            )
        except Exception:
            prompts = MagicMock()
            prompts.batch = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
            }
            prompts.meta_info = {"eos_token_id": [2]}

        output = rollout.generate_sequences(prompts)

        # With n=3 and batch_size=2, output batch size should be 6.
        assert output.batch["responses"].shape[0] == 6
        assert output.batch["input_ids"].shape[0] == 6
        assert output.batch["sequences"].shape[0] == 6
        # Should have created 6 rollouts.
        assert mock_client.create_rollout.call_count == 6
