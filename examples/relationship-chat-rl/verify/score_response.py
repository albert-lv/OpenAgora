#!/usr/bin/env python3
"""
Reward model for the relationship-chat scenario.

Reads /sandbox/response.txt and /sandbox/.arena/task.json, evaluates the
reply against the hidden rubric, and writes the scalar reward to
/sandbox/.arena/rewards.jsonl.

The script intentionally exits with code 1 so Arena's legacy binary verifier
(score 1.0 on exit 0 / 0.0 on exit non-zero) does not override the
continuous reward written to rewards.jsonl.
"""

import json
import os
import sys


def contains_any(text: str, candidates: list[str]) -> list[str]:
    """Return the subset of candidates found as substrings in text."""
    lower = text.lower()
    return [c for c in candidates if c.lower() in lower]


def score_response(response: str, rubric: dict) -> tuple[float, dict]:
    """Compute a continuous reward in [0, 1]."""
    response = response.strip()
    details: dict = {"response_length": len(response)}

    # Penalties for harmful / dismissive phrases.
    must_avoid = rubric.get("must_avoid", [])
    avoided = contains_any(response, must_avoid)
    details["avoided_phrases"] = avoided

    # Bonuses for supportive / empathetic phrases.
    must_include = rubric.get("must_include", [])
    included = contains_any(response, must_include)
    details["included_phrases"] = included

    # Start from a neutral base.
    reward = 0.5

    # Avoid penalties are strong.
    reward -= len(avoided) * 0.25

    # Include bonuses are moderate.
    reward += len(included) * 0.12

    # Length quality.
    if len(response) < 15:
        reward -= 0.2
        details["length_note"] = "too_short"
    elif len(response) > 300:
        reward -= 0.1
        details["length_note"] = "too_long"
    else:
        details["length_note"] = "ok"

    # Clamp to [0, 1].
    reward = max(0.0, min(1.0, reward))
    return reward, details


def main():
    sandbox_dir = os.environ.get("SANDBOX_DIR", "/sandbox")
    response_path = os.path.join(sandbox_dir, "response.txt")
    task_path = os.path.join(sandbox_dir, ".arena", "task.json")
    rewards_path = os.path.join(sandbox_dir, ".arena", "rewards.jsonl")

    response = ""
    if os.path.exists(response_path):
        with open(response_path, encoding="utf-8") as f:
            response = f.read()

    rubric = {}
    if os.path.exists(task_path):
        try:
            with open(task_path, encoding="utf-8") as f:
                task = json.load(f)
            rubric = task.get("rubric", {})
        except Exception as e:
            print(f"Failed to read task.json: {e}")

    reward, details = score_response(response, rubric)

    os.makedirs(os.path.dirname(rewards_path), exist_ok=True)
    with open(rewards_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "type": "custom",
                "value": reward,
                "source": "relationship_rubric",
                "detail_json": json.dumps(details, ensure_ascii=False),
            },
            f,
            ensure_ascii=False,
        )
        f.write("\n")

    print(f"REWARD: {reward:.2f}")
    print(f"AVOIDED: {details.get('avoided_phrases', [])}")
    print(f"INCLUDED: {details.get('included_phrases', [])}")
    print(f"LENGTH: {details.get('length_note')} ({details.get('response_length')} chars)")

    # Exit 1 on purpose; the reward above is what we want the trainer to see.
    sys.exit(1)


if __name__ == "__main__":
    main()
