"""Common utilities for Arena rollout providers.

This module extracts shared logic between agent_loop.py and rollout.py
to avoid code duplication in trajectory parsing and logprob extraction.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_response_text(trajectory: list[dict[str, Any]]) -> str:
    """Extract the agent's final response text from the Arena trajectory.

    Trajectory steps contain raw HTTP request/response bodies. We attempt to
    parse each step's response choices and concatenate assistant messages.
    Handles both raw ``choices`` arrays and full OpenAI response JSON.

    Args:
        trajectory: List of trajectory step dicts from Arena.

    Returns:
        Concatenated assistant response text.
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


def extract_logprobs(
    trajectory: list[dict[str, Any]], response_length: int
) -> Optional[list[float]]:
    """Extract per-token logprobs from trajectory if available.

    OpenAI-compatible logprobs format::

        {
            "content": [
                {"token": "...", "logprob": -0.123, "top_logprobs": [...]},
                ...
            ]
        }

    Args:
        trajectory: List of trajectory step dicts from Arena.
        response_length: Expected number of response tokens (for padding/truncation).

    Returns:
        A flat list of logprob floats, or None if unavailable.
    """
    logprobs: list[float] = []
    for step in trajectory:
        resp = step.get("response") or {}
        lp_raw = resp.get("logprobs_json")
        if lp_raw:
            try:
                if isinstance(lp_raw, bytes):
                    lp_raw = lp_raw.decode("utf-8")
                # strict=False allows stray control characters in token strings.
                lp_data = json.loads(lp_raw, strict=False)
                content = lp_data.get("content") or lp_data.get("text")
                if isinstance(content, list):
                    for item in content:
                        lp = item.get("logprob")
                        if lp is not None:
                            logprobs.append(float(lp))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                continue
    if not logprobs:
        return None
    # Pad or truncate to response_length.
    if len(logprobs) < response_length:
        logprobs.extend([0.0] * (response_length - len(logprobs)))
    return logprobs[:response_length]


def extract_native_token_ids(
    trajectory: list[dict[str, Any]],
) -> Optional[dict[str, list[int]]]:
    """Extract engine-native token IDs from trajectory steps if available.

    The Arena proxy populates ``prompt_token_ids``/``completion_token_ids`` on
    each step's ``LLMResponse`` when the inference backend reports them (e.g.
    SGLang ``meta_info``). Using them verbatim avoids the train/inference
    tokenization mismatch of re-tokenizing response text.

    Args:
        trajectory: List of trajectory step dicts from Arena.

    Returns:
        ``{"prompt_token_ids": [...], "completion_token_ids": [...]}`` with the
        per-step IDs concatenated in order, or ``None`` when no step carries
        completion token IDs (callers should fall back to re-tokenization).
    """
    prompt_ids: list[int] = []
    completion_ids: list[int] = []
    for step in trajectory:
        resp = step.get("response") or {}
        prompt_ids.extend(int(t) for t in resp.get("prompt_token_ids") or [])
        completion_ids.extend(int(t) for t in resp.get("completion_token_ids") or [])
    if not completion_ids:
        return None
    return {
        "prompt_token_ids": prompt_ids,
        "completion_token_ids": completion_ids,
    }


def extract_weight_versions(trajectory: list[dict[str, Any]]) -> list[str]:
    """Collect the per-step weight versions reported by the inference engine.

    Steps of a partial rollout that was paused and resumed under new weights
    may report different versions; the returned list preserves trajectory
    order (one entry per step that reports a version).

    Args:
        trajectory: List of trajectory step dicts from Arena.

    Returns:
        List of non-empty ``weight_version`` strings, possibly empty.
    """
    versions: list[str] = []
    for step in trajectory:
        resp = step.get("response") or {}
        version = resp.get("weight_version")
        if version:
            versions.append(version)
    return versions
