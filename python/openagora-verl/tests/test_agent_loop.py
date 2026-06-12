"""Unit tests for ArenaAgentLoop."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# Mock veRL before importing agent_loop.
_mock_verl = MagicMock()
_mock_verl.experimental = MagicMock()
_mock_verl.experimental.agent_loop = MagicMock()
_mock_verl.utils = MagicMock()
_mock_verl.utils.chat_template = MagicMock()
sys.modules["verl"] = _mock_verl
sys.modules["verl.experimental"] = _mock_verl.experimental
sys.modules["verl.experimental.agent_loop"] = _mock_verl.experimental.agent_loop
sys.modules["verl.experimental.agent_loop.agent_loop"] = _mock_verl.experimental.agent_loop
sys.modules["verl.utils"] = _mock_verl.utils
sys.modules["verl.utils.chat_template"] = _mock_verl.utils.chat_template

# Make register return a real class decorator so ArenaAgentLoop stays a real class.
def _real_register(name):
    def decorator(cls):
        cls._registered_name = name
        return cls
    return decorator

_mock_verl.experimental.agent_loop.register = _real_register

# Provide real mock base class.
class _MockAgentLoopBase:
    def __init__(self, *args, **kwargs):
        pass

class _MockAgentLoopOutput:
    def __init__(self, prompt_ids, response_ids, response_mask, response_logprobs=None,
                 routed_experts=None, multi_modal_data=None, reward_score=None,
                 num_turns=0, metrics=None, extra_fields=None, mm_processor_kwargs=None):
        self.prompt_ids = prompt_ids
        self.response_ids = response_ids
        self.response_mask = response_mask
        self.response_logprobs = response_logprobs
        self.routed_experts = routed_experts
        self.multi_modal_data = multi_modal_data
        self.reward_score = reward_score
        self.num_turns = num_turns
        self.metrics = metrics
        self.extra_fields = extra_fields or {}
        self.mm_processor_kwargs = mm_processor_kwargs

class _MockAgentLoopMetrics:
    def __init__(self, generate_sequences=0.0, tool_calls=0.0, compute_score=0.0, num_preempted=-1):
        self.generate_sequences = generate_sequences
        self.tool_calls = tool_calls
        self.compute_score = compute_score
        self.num_preempted = num_preempted

_mock_verl.experimental.agent_loop.AgentLoopBase = _MockAgentLoopBase
_mock_verl.experimental.agent_loop.AgentLoopOutput = _MockAgentLoopOutput
_mock_verl.experimental.agent_loop.AgentLoopMetrics = _MockAgentLoopMetrics

from openagora_verl.agent_loop import ArenaAgentLoop


class FakeTokenizer:
    """Minimal tokenizer stand-in for tests."""

    def __init__(self):
        self.pad_token_id = 0
        self.vocab = {"hello": 1, "world": 2, "def": 3, "add": 4}

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
                tokens.append(99)
        return tokens


@pytest.fixture
def fake_tokenizer():
    return FakeTokenizer()


@pytest.fixture
def mock_arena_client(monkeypatch):
    """Return a mock ArenaClient that simulates successful rollouts."""
    client = MagicMock()
    client.create_rollout.return_value = {"rollout_id": "test-rollout-123"}
    client.wait.return_value = {"status": "success", "reward": 1.0}
    client.get_trajectory.return_value = [
        {
            "step_id": 1,
            "request": {
                "endpoint": "/v1/chat/completions",
                "messages_json": b'{"messages": [{"role": "user", "content": "hello"}]}',
            },
            "response": {
                "choices_json": b'[{"message": {"role": "assistant", "content": "def add(): pass"}}]',
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "logprobs_json": b'{"content": [{"token": "def", "logprob": -0.5}, {"token": " add", "logprob": -0.3}, {"token": ":", "logprob": -0.1}, {"token": " pass", "logprob": -0.2}, {"token": "\n", "logprob": -0.4}]}',
            },
        }
    ]
    return client


@pytest.fixture
def arena_loop(fake_tokenizer, mock_arena_client):
    """Create an ArenaAgentLoop with mocked dependencies."""
    loop = ArenaAgentLoop.__new__(ArenaAgentLoop)
    loop._tokenizer = fake_tokenizer
    loop._processor = None
    loop._prompt_length = 128
    loop._response_length = 128
    loop._agent_image = "test-image:latest"
    loop._llm_backend = "http://test:8000/v1"
    loop._verify_command = "true"
    loop._timeout_seconds = 60
    loop._arena = mock_arena_client
    return loop


class TestApplyChatTemplate:
    def test_with_apply_chat_template(self, arena_loop, fake_tokenizer):
        messages = [{"role": "user", "content": "Hello"}]
        result = arena_loop._apply_chat_template(messages)
        assert "user: Hello" in result

    def test_fallback_concatenation(self, arena_loop):
        # Swap to a tokenizer without apply_chat_template to trigger fallback.
        class NoTemplateTokenizer:
            pass
        arena_loop._tokenizer = NoTemplateTokenizer()
        messages = [{"role": "user", "content": "Hello"}]
        result = arena_loop._apply_chat_template(messages)
        assert "<user>" in result
        assert "Hello" in result


class TestEncodeText:
    def test_encode(self, arena_loop):
        result = arena_loop._encode_text("hello world")
        assert result == [1, 2]

    def test_encode_fallback(self, arena_loop):
        # Swap to a tokenizer without encode to trigger HF fallback.
        class HFTokenizer:
            def __call__(self, text, add_special_tokens=False):
                return {"input_ids": [1, 2]}
        arena_loop._tokenizer = HFTokenizer()
        result = arena_loop._encode_text("hello world")
        assert result == [1, 2]


class TestExtractResponseText:
    def test_single_step(self, arena_loop):
        trajectory = [
            {
                "response": {
                    "choices_json": b'[{"message": {"content": "answer"}}]',
                }
            }
        ]
        result = arena_loop._extract_response_text(trajectory)
        assert result == "answer"

    def test_multiple_steps(self, arena_loop):
        trajectory = [
            {
                "response": {
                    "choices_json": b'[{"message": {"content": "part1"}}]',
                }
            },
            {
                "response": {
                    "choices_json": b'[{"message": {"content": "part2"}}]',
                }
            },
        ]
        result = arena_loop._extract_response_text(trajectory)
        assert result == "part1\npart2"

    def test_empty_trajectory(self, arena_loop):
        result = arena_loop._extract_response_text([])
        assert result == ""

    def test_invalid_json(self, arena_loop):
        trajectory = [
            {"response": {"choices_json": b"not json"}},
            {"response": {"choices_json": b'[{"message": {"content": "valid"}}]'}},
        ]
        result = arena_loop._extract_response_text(trajectory)
        assert result == "valid"


class TestExtractResponseLogprobs:
    def test_extracts_logprobs(self, arena_loop):
        trajectory = [
            {
                "response": {
                    "logprobs_json": b'{"content": [{"token": "a", "logprob": -0.1}, {"token": "b", "logprob": -0.2}]}',
                }
            }
        ]
        result = arena_loop._extract_response_logprobs(trajectory, 2)
        assert result == [-0.1, -0.2]

    def test_pads_short(self, arena_loop):
        trajectory = [
            {
                "response": {
                    "logprobs_json": b'{"content": [{"token": "a", "logprob": -0.1}]}',
                }
            }
        ]
        result = arena_loop._extract_response_logprobs(trajectory, 3)
        assert result == [-0.1, 0.0, 0.0]

    def test_truncates_long(self, arena_loop):
        trajectory = [
            {
                "response": {
                    "logprobs_json": b'{"content": [{"token": "a", "logprob": -0.1}, {"token": "b", "logprob": -0.2}, {"token": "c", "logprob": -0.3}]}',
                }
            }
        ]
        result = arena_loop._extract_response_logprobs(trajectory, 2)
        assert result == [-0.1, -0.2]

    def test_missing_logprobs(self, arena_loop):
        trajectory = [{"response": {}}]
        result = arena_loop._extract_response_logprobs(trajectory, 2)
        assert result is None

    def test_excludes_tool_steps(self, arena_loop):
        trajectory = [
            {
                "request": {
                    "messages_json": b'{"messages": [{"role": "assistant", "content": "prev"}]}',
                },
                "response": {
                    "logprobs_json": b'{"content": [{"token": "tool", "logprob": -0.1}]}',
                },
            }
        ]
        result = arena_loop._extract_response_logprobs(trajectory, 1)
        # Tool steps are excluded by default.
        assert result is None


class TestStepRole:
    def test_assistant_role(self, arena_loop):
        step = {
            "request": {
                "messages_json": b'{"messages": [{"role": "user", "content": "hi"}]}',
            }
        }
        assert arena_loop._step_role(step) == "assistant"

    def test_tool_role(self, arena_loop):
        step = {
            "request": {
                "messages_json": b'{"messages": [{"role": "assistant", "content": "prev"}]}',
            }
        }
        assert arena_loop._step_role(step) == "tool"

    def test_unknown_role(self, arena_loop):
        step = {"request": {}, "response": {}}
        assert arena_loop._step_role(step) == "unknown"

    def test_tool_call_in_response(self, arena_loop):
        step = {
            "response": {
                "choices_json": b'[{"message": {"tool_calls": [{"id": "1"}]}}]',
            }
        }
        assert arena_loop._step_role(step) == "tool"


@pytest.mark.asyncio
class TestRun:
    async def test_run_success(self, arena_loop, mock_arena_client):
        out = await arena_loop.run(
            sampling_params={"temperature": 0.5, "top_p": 0.9},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert out.reward_score == 1.0
        assert len(out.prompt_ids) > 0
        assert len(out.response_ids) > 0
        assert len(out.response_mask) == len(out.response_ids)
        assert out.num_turns == 1
        mock_arena_client.create_rollout.assert_called_once()

    async def test_run_missing_raw_prompt(self, arena_loop):
        with pytest.raises(ValueError, match="raw_prompt"):
            await arena_loop.run(sampling_params={}, index=0)


class TestCountAgentTurns:
    def test_assistant_turn_counts(self, arena_loop):
        step = {
            "request": {
                "messages_json": b'{"messages": [{"role": "user", "content": "hi"}]}'
            },
            "response": {
                "choices_json": b'[{"message": {"role": "assistant", "content": "hello"}}]'
            },
        }
        assert arena_loop._count_agent_turns([step]) == 1

    def test_tool_turn_counts(self, arena_loop):
        step = {
            "request": {
                "messages_json": b'{"messages": [{"role": "user", "content": "hi"}]}'
            },
            "response": {
                "choices_json": b'[{"message": {"role": "assistant", "tool_calls": [{"id": "t1"}]}}]'
            },
        }
        assert arena_loop._count_agent_turns([step]) == 1

    def test_user_steps_do_not_count(self, arena_loop):
        step = {
            "request": {
                "messages_json": b'{"messages": [{"role": "user", "content": "hi"}]}'
            },
            "response": {"choices_json": b'[]'},
        }
        assert arena_loop._count_agent_turns([step]) == 1  # min 1


class TestRolloutProvider:
    def test_init(self):
        from openagora_verl.rollout_provider import ArenaRolloutProvider
        provider = ArenaRolloutProvider(
            arena_endpoint="localhost:9090",
            sandbox_image="test:latest",
            llm_backend="http://test:8000/v1",
            verify_command="true",
        )
        assert provider.sandbox_image == "test:latest"

    def test_generate(self, monkeypatch):
        from openagora_verl.rollout_provider import ArenaRolloutProvider
        provider = ArenaRolloutProvider(
            arena_endpoint="localhost:9090",
            sandbox_image="test:latest",
            llm_backend="http://test:8000/v1",
            verify_command="true",
            max_concurrent=2,
        )

        def mock_run_one(index, prompt, sampling):
            return {
                "rollout_id": f"r{index}",
                "task_id": f"t{index}",
                "status": "success",
                "reward": float(index),
                "trajectory": [],
            }

        monkeypatch.setattr(provider, "_run_one", mock_run_one)
        results = provider.generate(["prompt1", "prompt2"])
        assert len(results) == 2
        assert results[0]["reward"] == 0.0
        assert results[1]["reward"] == 1.0

    @pytest.mark.asyncio
    async def test_generate_async(self, monkeypatch):
        from openagora_verl.rollout_provider import ArenaRolloutProvider
        provider = ArenaRolloutProvider(
            arena_endpoint="localhost:9090",
            sandbox_image="test:latest",
            llm_backend="http://test:8000/v1",
            verify_command="true",
            max_concurrent=2,
        )

        def mock_run_one(index, prompt, sampling):
            return {
                "rollout_id": f"r{index}",
                "task_id": f"t{index}",
                "status": "success",
                "reward": float(index),
                "trajectory": [],
            }

        monkeypatch.setattr(provider, "_run_one", mock_run_one)
        results = []
        async for result in provider.generate_async(["prompt1", "prompt2"]):
            results.append(result)
        assert len(results) == 2
        rewards = sorted([r["reward"] for r in results])
        assert rewards == [0.0, 1.0]
