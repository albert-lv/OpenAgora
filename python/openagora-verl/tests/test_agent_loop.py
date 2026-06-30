"""Unit tests for ArenaAgentLoop."""

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
sys.modules["verl.experimental.agent_loop.agent_loop"] = (
    _mock_verl.experimental.agent_loop
)
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
    def __init__(
        self,
        prompt_ids,
        response_ids,
        response_mask,
        response_logprobs=None,
        routed_experts=None,
        multi_modal_data=None,
        reward_score=None,
        num_turns=0,
        metrics=None,
        extra_fields=None,
        mm_processor_kwargs=None,
    ):
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
    def __init__(
        self,
        generate_sequences=0.0,
        tool_calls=0.0,
        compute_score=0.0,
        num_preempted=-1,
    ):
        self.generate_sequences = generate_sequences
        self.tool_calls = tool_calls
        self.compute_score = compute_score
        self.num_preempted = num_preempted


_mock_verl.experimental.agent_loop.AgentLoopBase = _MockAgentLoopBase
_mock_verl.experimental.agent_loop.AgentLoopOutput = _MockAgentLoopOutput
_mock_verl.experimental.agent_loop.AgentLoopMetrics = _MockAgentLoopMetrics

from openagora_verl.agent_loop import ArenaAgentLoop  # noqa: E402
from openagora_verl.logger import NoOpLogger  # noqa: E402


class FakeTokenizer:
    """Minimal tokenizer stand-in for tests."""

    def __init__(self):
        self.pad_token_id = 0
        self.vocab = {"hello": 1, "world": 2, "def": 3, "add": 4}

    def apply_chat_template(
        self, messages, add_generation_prompt=False, tokenize=False, **kwargs
    ):
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
                "logprobs_json": b'{"content": [{"token": "def", "logprob": -0.5}, {"token": " add", "logprob": -0.3}, {"token": ":", "logprob": -0.1}, {"token": " pass", "logprob": -0.2}, {"token": "\\n", "logprob": -0.4}]}',
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
    loop._logger = NoOpLogger()
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

    async def test_logprobs_align_with_response_ids(self, arena_loop):
        out = await arena_loop.run(
            sampling_params={"temperature": 0.5, "top_p": 0.9},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert out.response_logprobs is not None
        assert len(out.response_logprobs) == len(out.response_ids)

    async def test_global_steps_passed_to_extra_fields(self, arena_loop):
        out = await arena_loop.run(
            sampling_params={"temperature": 0.5, "top_p": 0.9},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
            global_steps=42,
        )
        assert out.extra_fields["min_global_steps"] == 42
        assert out.extra_fields["max_global_steps"] == 42

    async def test_empty_response_fallback(self, arena_loop):
        # Override trajectory to simulate an agent that never replied.
        arena_loop._arena.get_trajectory.return_value = []
        out = await arena_loop.run(
            sampling_params={"temperature": 0.5, "top_p": 0.9},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert out.response_ids
        assert out.response_mask


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
            "response": {"choices_json": b"[]"},
        }
        assert arena_loop._count_agent_turns([step]) == 1  # min 1
