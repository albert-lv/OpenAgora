"""
Arena Agent Loop for veRL.

This module provides an AgentLoopBase implementation that delegates agent
execution to the Arena sandbox infrastructure. It is designed to be used
with veRL's AgentLoop framework.

Usage in veRL training config::

    actor_rollout_ref.rollout.agent.default_agent_loop = "arena_agent"
    +actor_rollout_ref.rollout.agent.agent_loop_config_path = "arena_agent_loop.yaml"

The agent loop will:
1. Encode the prompt messages into a text task.
2. Submit the task to Arena as a sandboxed rollout.
3. Wait for the agent to finish (LLM calls go through Arena Proxy → veRL LLM server).
4. Fetch the trajectory and compute reward from Arena verification.
5. Tokenize the prompt + response into the veRL DataProto format.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openagora_sdk.client import ArenaClient

logger = logging.getLogger(__name__)

# Conditional import of veRL types so openagora-verl can be installed without veRL.
try:
    from verl.experimental.agent_loop.agent_loop import (
        AgentLoopBase,
        AgentLoopOutput,
        AgentLoopMetrics,
        register,
    )
    _VERL_AVAILABLE = True
except ImportError:
    _VERL_AVAILABLE = False
    AgentLoopBase = object  # type: ignore[misc,assignment]

    class _MockAgentLoopOutput:  # type: ignore[no-redef]
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

    class _MockAgentLoopMetrics:  # type: ignore[no-redef]
        def __init__(self, generate_sequences=0.0, tool_calls=0.0, compute_score=0.0, num_preempted=-1):
            self.generate_sequences = generate_sequences
            self.tool_calls = tool_calls
            self.compute_score = compute_score
            self.num_preempted = num_preempted

    AgentLoopOutput = _MockAgentLoopOutput  # type: ignore[misc,assignment]
    AgentLoopMetrics = _MockAgentLoopMetrics  # type: ignore[misc,assignment]
    register = lambda name: lambda cls: cls  # type: ignore[assignment]


class _ConfigWrap:
    """Lightweight wrapper mirroring veRL's DictConfigWrap."""

    def __init__(self, config: Any):
        self.config = config


def _get_env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@register("arena_agent")
class ArenaAgentLoop(AgentLoopBase):  # type: ignore[valid-type,misc]
    """Arena-backed agent loop for veRL.

    The agent runs inside an Arena sandbox (e.g. Docker). All LLM calls made
    by the agent are transparently proxied through Arena's LLM Proxy, which
    can be pointed at veRL's vLLM/SGLang inference server.

    Required environment variables (or passed via ``tools_kwargs``):

    - ``ARENA_ENDPOINT``: gRPC endpoint of the Arena server (default: localhost:9090).
    - ``ARENA_AGENT_IMAGE``: Docker image for the sandboxed agent.
    - ``ARENA_LLM_BACKEND``: URL of the LLM backend (e.g. veRL's vLLM server).
    - ``ARENA_VERIFY_COMMAND``: Optional verification command (default: "true").
    """

    def __init__(self, *args: Any, **kwargs: Any):
        # veRL's AgentLoopBase expects specific args, but we only need a subset.
        # Accept everything and extract what we need.
        super().__init__(*args, **kwargs)

        # Resolve rollout config.
        cfg = getattr(self, "config", None)
        if cfg is None:
            cfg = kwargs.get("trainer_config")
        if hasattr(cfg, "config"):
            cfg = cfg.config
        self._trainer_config = cfg

        # Arena client.
        arena_endpoint = _get_env("ARENA_ENDPOINT", "localhost:9090")
        self._arena = ArenaClient(arena_endpoint)

        # Arena runtime parameters.
        self._agent_image = _get_env("ARENA_AGENT_IMAGE", "openagora-agent-minimal:latest")
        self._llm_backend = _get_env("ARENA_LLM_BACKEND", "http://localhost:8000/v1")
        self._verify_command = _get_env("ARENA_VERIFY_COMMAND", "true")
        self._timeout_seconds = int(_get_env("ARENA_TIMEOUT_SECONDS", "3600"))

        # Tokenizer / processor come from base class init in veRL.
        self._tokenizer = getattr(self, "tokenizer", None)
        self._processor = getattr(self, "processor", None)

        # Prompt / response length caps from veRL rollout config.
        rollout_cfg = getattr(self, "rollout_config", None)
        if rollout_cfg is None:
            rollout_cfg = kwargs.get("rollout_config")
        self._prompt_length = getattr(rollout_cfg, "prompt_length", 512)
        self._response_length = getattr(rollout_cfg, "response_length", 512)

        logger.info(
            "ArenaAgentLoop initialized: endpoint=%s image=%s backend=%s",
            arena_endpoint, self._agent_image, self._llm_backend,
        )

    async def run(self, sampling_params: dict[str, Any], **kwargs: Any) -> AgentLoopOutput:  # type: ignore[return]
        """Run one Arena rollout and return tokenized results for veRL."""
        if not _VERL_AVAILABLE:
            logger.warning("veRL is not installed; running in standalone mode.")

        messages: list[dict[str, Any]] = list(kwargs.get("raw_prompt", []))
        if not messages:
            raise ValueError("ArenaAgentLoop requires 'raw_prompt' in kwargs")

        # 1. Build prompt text from messages.
        prompt_text = self._apply_chat_template(messages)

        # 2. Tokenize prompt to get prompt_ids.
        prompt_ids = self._encode_text(prompt_text, add_generation_prompt=True)
        if len(prompt_ids) > self._prompt_length:
            logger.warning(
                "Prompt truncated from %d to %d tokens", len(prompt_ids), self._prompt_length
            )
            prompt_ids = prompt_ids[-self._prompt_length :]

        # 3. Create Arena rollout.
        # Allow per-sample task file override via extra_info (e.g., Code Colosseum problems).
        extra = kwargs.get("extra_info", {})
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except json.JSONDecodeError:
                extra = {}

        custom_task_file = extra.get("task_file")
        if custom_task_file:
            if isinstance(custom_task_file, str):
                task_payload = custom_task_file.encode("utf-8")
            else:
                task_payload = custom_task_file
        else:
            task_payload = json.dumps(
                {
                    "task_id": kwargs.get("index", "0"),
                    "prompt": prompt_text,
                    "messages": messages,
                }
            ).encode("utf-8")

        sampling_cfg = {
            "temperature": sampling_params.get("temperature", 1.0),
            "top_p": sampling_params.get("top_p", 1.0),
            "seed": sampling_params.get("seed", 0),
        }

        verify_cmd = extra.get("openagora_verify", self._verify_command)

        rollout_info = self._arena.create_rollout(
            task_id=f"verl-{kwargs.get('index', '0')}",
            image=self._agent_image,
            llm_backend=self._llm_backend,
            sampling=sampling_cfg,
            verify={"command": verify_cmd} if verify_cmd else None,
            task_file=task_payload,
            timeout_seconds=self._timeout_seconds,
        )
        rollout_id = rollout_info["rollout_id"]
        logger.info("Arena rollout created: %s", rollout_id)

        # 4. Wait for completion.
        result = self._arena.wait(rollout_id, timeout=self._timeout_seconds)
        logger.info("Arena rollout %s finished: status=%s reward=%s", rollout_id, result["status"], result.get("reward"))

        # 5. Fetch trajectory and extract response text.
        trajectory = self._arena.get_trajectory(rollout_id)
        response_text = self._extract_response_text(trajectory)

        # 6. Tokenize response.
        response_ids = self._encode_text(response_text, add_generation_prompt=False)
        if len(response_ids) > self._response_length:
            logger.warning(
                "Response truncated from %d to %d tokens", len(response_ids), self._response_length
            )
            response_ids = response_ids[: self._response_length]

        response_mask = [1] * len(response_ids)

        # 7. Extract per-token logprobs if available.
        response_logprobs = self._extract_response_logprobs(trajectory, len(response_ids))

        # 8. Extract reward.
        reward_score = float(result.get("reward", 0.0))

        # 9. Count agent turns from the trajectory.
        num_turns = self._count_agent_turns(trajectory)

        metrics = AgentLoopMetrics(generate_sequences=0.0, tool_calls=0.0, compute_score=0.0)

        extra_fields = {
            "arena_rollout_id": rollout_id,
            "arena_status": result["status"],
            "trajectory_steps": len(trajectory),
        }
        if hasattr(self, "_last_logprob_meta"):
            extra_fields["logprob_step_breakdown"] = self._last_logprob_meta

        return AgentLoopOutput(
            prompt_ids=prompt_ids,
            response_ids=response_ids,
            response_mask=response_mask,
            response_logprobs=response_logprobs,
            reward_score=reward_score,
            num_turns=num_turns,
            metrics=metrics,
            extra_fields=extra_fields,
        )

    def _apply_chat_template(self, messages: list[dict[str, Any]]) -> str:
        """Render messages to a single text string."""
        processing_class = self._processor if self._processor is not None else self._tokenizer
        if processing_class is None:
            raise RuntimeError("ArenaAgentLoop requires a tokenizer or processor")

        # Prefer apply_chat_template if available (HF transformers).
        if hasattr(processing_class, "apply_chat_template"):
            try:
                return processing_class.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=False
                )
            except ValueError:
                # chat_template not set on this tokenizer; fallback.
                pass
        # Fallback: naive concatenation.
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"<{role}>\n{content}\n</{role}>")
        return "\n".join(parts)

    def _encode_text(self, text: str, add_generation_prompt: bool = False) -> list[int]:
        """Encode text to token IDs."""
        processing_class = self._processor if self._processor is not None else self._tokenizer
        if processing_class is None:
            raise RuntimeError("ArenaAgentLoop requires a tokenizer or processor")

        if hasattr(processing_class, "encode"):
            return processing_class.encode(text, add_special_tokens=False)
        # Fallback for HF tokenizers.
        return processing_class(text, add_special_tokens=False)["input_ids"]

    def _extract_response_text(self, trajectory: list[dict[str, Any]]) -> str:
        """Extract the agent's final response text from the Arena trajectory.

        Trajectory steps contain raw HTTP request/response bodies. We attempt to
        parse each step's response choices and concatenate assistant messages.
        Handles both raw ``choices`` arrays and full OpenAI response JSON.
        """
        texts = []
        for step in trajectory:
            resp = step.get("response") or {}
            choices_json = resp.get("choices_json") or resp.get("choices")
            if not choices_json:
                continue
            try:
                if isinstance(choices_json, bytes):
                    choices_json = choices_json.decode("utf-8")
                data = json.loads(choices_json)
                # choices_json may be the full OpenAI response dict or just the choices list.
                if isinstance(data, dict):
                    choices = data.get("choices", [])
                elif isinstance(data, list):
                    choices = data
                else:
                    continue
                if isinstance(choices, list) and len(choices) > 0:
                    choice = choices[0]
                    msg = choice.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        texts.append(content)
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("Failed to parse choices JSON in trajectory step")
                continue
        return "\n".join(texts)

    def _count_agent_turns(self, trajectory: list[dict[str, Any]]) -> int:
        """Count the number of assistant/tool turns in the trajectory.

        The initial user prompt is not counted; each assistant response or
        tool call/observation emitted by the agent counts as one turn.
        """
        count = 0
        for step in trajectory:
            role = self._step_role(step)
            if role in ("assistant", "tool", "observation"):
                count += 1
        return max(count, 1)

    def _step_role(self, step: dict[str, Any]) -> str:
        """Infer the role of a trajectory step from request/response messages.

        Returns one of: ``assistant``, ``tool``, ``observation``, ``unknown``.
        """
        req = step.get("request") or {}
        messages_json = req.get("messages_json")
        if messages_json:
            try:
                if isinstance(messages_json, bytes):
                    messages_json = messages_json.decode("utf-8")
                data = json.loads(messages_json)
                msgs = data.get("messages", [])
                if msgs:
                    last_role = msgs[-1].get("role", "unknown")
                    if last_role in ("user", "system"):
                        return "assistant"  # LLM is generating a response to user/system
                    if last_role == "assistant":
                        return "tool"  # Next call is likely tool execution
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        # Fallback: inspect response content.
        resp = step.get("response") or {}
        choices_json = resp.get("choices_json") or resp.get("choices")
        if choices_json:
            try:
                if isinstance(choices_json, bytes):
                    choices_json = choices_json.decode("utf-8")
                choices = json.loads(choices_json)
                if isinstance(choices, list) and len(choices) > 0:
                    msg = choices[0].get("message", {})
                    if msg.get("tool_calls"):
                        return "tool"
                    if msg.get("role") == "assistant":
                        return "assistant"
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        return "unknown"

    def _should_include_step_logprobs(self, step: dict[str, Any]) -> bool:
        """Decide whether a step's logprobs should be included in policy gradient.

        Controlled by ``ARENA_LOGPROB_INCLUDE_ROLES`` env var (comma-separated).
        Default: ``assistant,unknown`` (unknown steps are included for backward
        compatibility with simple agents that don't annotate roles).
        """
        include_roles = _get_env("ARENA_LOGPROB_INCLUDE_ROLES", "assistant,unknown")
        allowed = {r.strip() for r in include_roles.split(",")}
        role = self._step_role(step)
        return role in allowed

    def _extract_response_logprobs(
        self, trajectory: list[dict[str, Any]], response_length: int
    ) -> Optional[list[float]]:
        """Extract per-token logprobs from trajectory if available.

        Respects ``_should_include_step_logprobs()`` so that tool/observation
        tokens can be excluded from the policy gradient.

        OpenAI-compatible logprobs format::

            {
                "content": [
                    {"token": "...", "logprob": -0.123, "top_logprobs": [...]},
                    ...
                ]
            }

        Returns a flat list of logprob floats, or None if unavailable.
        """
        logprobs: list[float] = []
        step_meta: list[dict[str, Any]] = []
        for step in trajectory:
            role = self._step_role(step)
            include = self._should_include_step_logprobs(step)
            resp = step.get("response") or {}
            lp_raw = resp.get("logprobs_json")
            step_lp_count = 0
            if lp_raw and include:
                try:
                    if isinstance(lp_raw, bytes):
                        lp_raw = lp_raw.decode("utf-8")
                    lp_data = json.loads(lp_raw)
                    content = lp_data.get("content") or lp_data.get("text")
                    if isinstance(content, list):
                        for item in content:
                            lp = item.get("logprob")
                            if lp is not None:
                                logprobs.append(float(lp))
                                step_lp_count += 1
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                    logger.debug("Failed to parse logprobs JSON in trajectory step")
            step_meta.append({
                "step_id": step.get("step_id"),
                "role": role,
                "included": include,
                "logprob_tokens": step_lp_count,
            })
        if not logprobs:
            return None
        # Pad or truncate to response_length.
        if len(logprobs) < response_length:
            logprobs.extend([0.0] * (response_length - len(logprobs)))
        self._last_logprob_meta = step_meta
        return logprobs[:response_length]
