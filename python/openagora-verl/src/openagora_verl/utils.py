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
