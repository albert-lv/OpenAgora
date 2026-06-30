"""Reward shaping for Code Colosseum."""

import re
from typing import Optional


def compute_reward(
    verification_report: Optional[dict],
    num_steps: int,
    runtime_baseline_ms: float = 100.0,
) -> float:
    """
    Combine correctness and efficiency into a scalar reward in [0, 1].

    - All hidden tests pass: base 100 + efficiency bonus
    - Partial pass: fraction * 50
    - Step penalty: -0.5 per step

    The raw score is normalized against a theoretical maximum of 120 so that
    downstream dashboards and GRPO group statistics stay on a [0, 1] scale.
    """
    raw = _compute_raw_reward(verification_report, num_steps, runtime_baseline_ms)
    return max(0.0, min(1.0, raw / 120.0))


def _compute_raw_reward(
    verification_report: Optional[dict],
    num_steps: int,
    runtime_baseline_ms: float = 100.0,
) -> float:
    """Un-normalized reward combining correctness and efficiency."""
    if not verification_report:
        return 0.0

    correctness = float(verification_report.get("reward", 0.0))

    # Extract runtime from stdout if available.
    stdout = verification_report.get("stdout", "")
    runtime_ms = _extract_runtime_ms(stdout) or runtime_baseline_ms

    if correctness < 1.0:
        return correctness * 50.0 - num_steps * 0.5

    efficiency_bonus = max(0.0, 1.0 - runtime_ms / runtime_baseline_ms) * 20.0
    return 100.0 + efficiency_bonus - num_steps * 0.5


def _extract_runtime_ms(stdout: str) -> Optional[float]:
    """Try to parse pytest runtime like '0.01s'."""
    match = re.search(r"(\d+\.?\d*)s", stdout)
    if match:
        return float(match.group(1)) * 1000.0
    return None
