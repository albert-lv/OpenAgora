"""Unit tests for ArenaAgentLoop."""

import asyncio
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace
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
    client.get_rollout.return_value = {"status": "success", "reward": 1.0}
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
    loop._poll_initial_interval = 0.01
    loop._poll_max_interval = 0.05
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


@pytest.mark.asyncio
class TestAsyncRun:
    async def test_concurrent_runs_do_not_block_event_loop(
        self, arena_loop, mock_arena_client
    ):
        """Two runs over a slow synchronous SDK should overlap, not serialize."""

        def slow_create_rollout(**kwargs):
            time.sleep(0.4)  # blocking, like a slow sync gRPC call
            return {"rollout_id": "test-rollout-slow"}

        mock_arena_client.create_rollout.side_effect = slow_create_rollout

        start = time.monotonic()
        out1, out2 = await asyncio.gather(
            arena_loop.run(
                sampling_params={},
                raw_prompt=[{"role": "user", "content": "Write a function."}],
                index=0,
            ),
            arena_loop.run(
                sampling_params={},
                raw_prompt=[{"role": "user", "content": "Write a function."}],
                index=1,
            ),
        )
        elapsed = time.monotonic() - start

        assert out1.reward_score == 1.0
        assert out2.reward_score == 1.0
        # Serialized blocking calls would take ~0.8s; offloaded to threads the
        # two create_rollout calls overlap (~0.4s).
        assert elapsed < 0.7

    async def test_run_polls_without_blocking_wait(self, arena_loop, mock_arena_client):
        """run() must poll via get_rollout (in a thread), never call wait()."""
        await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        mock_arena_client.wait.assert_not_called()
        mock_arena_client.get_rollout.assert_called_once_with("test-rollout-123")


@pytest.mark.asyncio
class TestWaitForRollout:
    async def test_exponential_backoff_with_cap(
        self, arena_loop, mock_arena_client, monkeypatch
    ):
        """Poll intervals double from the initial value up to the cap."""
        sleeps = []

        async def fake_sleep(duration):
            sleeps.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        # Remove jitter so the backoff progression is deterministic.
        monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)

        mock_arena_client.get_rollout.side_effect = [
            {"status": "running"},
            {"status": "running"},
            {"status": "running"},
            {"status": "success", "reward": 1.0},
        ]
        arena_loop._poll_initial_interval = 0.1
        arena_loop._poll_max_interval = 0.25

        result = await arena_loop._wait_for_rollout("r-backoff", timeout=10)

        assert result["status"] == "success"
        assert sleeps == [0.1, 0.2, 0.25]
        assert mock_arena_client.get_rollout.call_count == 4

    async def test_jittered_sleeps_stay_within_cap(
        self, arena_loop, mock_arena_client, monkeypatch
    ):
        """With jitter enabled, no sleep exceeds the max interval."""
        sleeps = []

        async def fake_sleep(duration):
            sleeps.append(duration)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        mock_arena_client.get_rollout.side_effect = [{"status": "running"}] * 5 + [
            {"status": "success", "reward": 1.0}
        ]
        arena_loop._poll_initial_interval = 0.05
        arena_loop._poll_max_interval = 0.1

        result = await arena_loop._wait_for_rollout("r-jitter", timeout=10)

        assert result["status"] == "success"
        assert len(sleeps) == 5
        assert all(0.0 <= s <= 0.1 for s in sleeps)

    async def test_failed_status_is_terminal(self, arena_loop, mock_arena_client):
        mock_arena_client.get_rollout.return_value = {"status": "failed", "reward": 0.0}
        result = await arena_loop._wait_for_rollout("r-failed", timeout=10)
        assert result["status"] == "failed"
        assert mock_arena_client.get_rollout.call_count == 1

    async def test_timeout_raises(self, arena_loop, mock_arena_client):
        mock_arena_client.get_rollout.return_value = {"status": "running"}
        arena_loop._poll_initial_interval = 0.005
        arena_loop._poll_max_interval = 0.01
        with pytest.raises(TimeoutError, match="did not complete"):
            await arena_loop._wait_for_rollout("r-stuck", timeout=0.05)


class TestConfigurableLengths:
    def test_defaults_are_512(self):
        loop = ArenaAgentLoop()
        assert loop._prompt_length == 512
        assert loop._response_length == 512

    def test_constructor_kwargs(self):
        loop = ArenaAgentLoop(prompt_length=256, response_length=1024)
        assert loop._prompt_length == 256
        assert loop._response_length == 1024

    def test_rollout_config_fallback(self):
        cfg = SimpleNamespace(prompt_length=64, response_length=32)
        loop = ArenaAgentLoop(rollout_config=cfg)
        assert loop._prompt_length == 64
        assert loop._response_length == 32

    def test_constructor_kwargs_override_rollout_config(self):
        cfg = SimpleNamespace(prompt_length=64, response_length=32)
        loop = ArenaAgentLoop(prompt_length=128, rollout_config=cfg)
        assert loop._prompt_length == 128
        assert loop._response_length == 32

    def test_poll_interval_defaults(self, monkeypatch):
        monkeypatch.delenv("ARENA_POLL_INITIAL_INTERVAL", raising=False)
        monkeypatch.delenv("ARENA_POLL_MAX_INTERVAL", raising=False)
        loop = ArenaAgentLoop()
        assert loop._poll_initial_interval == 0.05
        assert loop._poll_max_interval == 1.0

    def test_poll_intervals_from_env(self, monkeypatch):
        monkeypatch.setenv("ARENA_POLL_INITIAL_INTERVAL", "0.2")
        monkeypatch.setenv("ARENA_POLL_MAX_INTERVAL", "3")
        loop = ArenaAgentLoop()
        assert loop._poll_initial_interval == 0.2
        assert loop._poll_max_interval == 3.0

    @pytest.mark.asyncio
    async def test_run_truncates_to_configured_lengths(self, arena_loop):
        arena_loop._prompt_length = 2
        arena_loop._response_length = 2
        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert len(out.prompt_ids) == 2
        assert len(out.response_ids) == 2
        assert len(out.response_mask) == 2
        assert len(out.response_logprobs) == 2


@pytest.mark.asyncio
class TestNativeTokenIds:
    async def test_native_ids_used_without_retokenization(
        self, arena_loop, mock_arena_client
    ):
        mock_arena_client.get_trajectory.return_value = [
            {
                "step_id": 1,
                "response": {
                    "choices_json": b'[{"message": {"role": "assistant", "content": "def add(): pass"}}]',
                    "prompt_token_ids": [1, 2, 3],
                    "completion_token_ids": [7, 8, 9],
                },
            }
        ]
        encode_calls = []
        orig_encode = arena_loop._encode_text

        def spy(text, add_generation_prompt=False):
            encode_calls.append(text)
            return orig_encode(text, add_generation_prompt=add_generation_prompt)

        arena_loop._encode_text = spy

        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )

        # response_ids come verbatim from the engine-native token IDs.
        assert out.response_ids == [7, 8, 9]
        assert out.response_mask == [1, 1, 1]
        # The tokenizer was only used for the prompt, never for the response.
        assert len(encode_calls) == 1

    async def test_native_ids_truncated_to_response_length(
        self, arena_loop, mock_arena_client
    ):
        arena_loop._response_length = 2
        mock_arena_client.get_trajectory.return_value = [
            {
                "step_id": 1,
                "response": {
                    "choices_json": b'[{"message": {"role": "assistant", "content": "x"}}]',
                    "completion_token_ids": [7, 8, 9],
                },
            }
        ]
        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert out.response_ids == [7, 8]
        assert out.response_mask == [1, 1]

    async def test_fallback_retokenizes_when_native_ids_absent(
        self, arena_loop, mock_arena_client
    ):
        # Default mock trajectory has no token-id fields.
        encode_calls = []
        orig_encode = arena_loop._encode_text

        def spy(text, add_generation_prompt=False):
            encode_calls.append(text)
            return orig_encode(text, add_generation_prompt=add_generation_prompt)

        arena_loop._encode_text = spy

        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )

        # Prompt + response were both tokenized via the tokenizer.
        assert len(encode_calls) == 2
        # "def add(): pass" re-tokenized by FakeTokenizer.
        assert out.response_ids == [3, 99, 99]

    async def test_mixed_weight_versions_propagated(
        self, arena_loop, mock_arena_client
    ):
        mock_arena_client.get_rollout.return_value = {
            "status": "success",
            "reward": 1.0,
            "weight_version": "v1",
        }
        mock_arena_client.get_trajectory.return_value = [
            {
                "step_id": 1,
                "response": {
                    "choices_json": b'[{"message": {"role": "assistant", "content": "hello"}}]',
                    "completion_token_ids": [7],
                    "weight_version": "v1",
                },
            },
            {
                "step_id": 2,
                "response": {
                    "choices_json": b'[{"message": {"role": "assistant", "content": "world"}}]',
                    "completion_token_ids": [8],
                    "weight_version": "v2",
                },
            },
        ]
        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert out.response_ids == [7, 8]
        assert out.extra_fields["weight_version"] == "v1"
        assert out.extra_fields["min_weight_version"] == "v1"
        assert out.extra_fields["max_weight_version"] == "v2"

    async def test_no_weight_version_keys_when_absent(
        self, arena_loop, mock_arena_client
    ):
        out = await arena_loop.run(
            sampling_params={},
            raw_prompt=[{"role": "user", "content": "Write a function."}],
            index=0,
        )
        assert "weight_version" not in out.extra_fields
        assert "min_weight_version" not in out.extra_fields
        assert "max_weight_version" not in out.extra_fields
