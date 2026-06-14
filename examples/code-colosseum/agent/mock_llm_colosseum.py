#!/usr/bin/env python3
"""
Mock LLM server for the Code Colosseum demo.

Returns deterministic Python solutions for known problems so the entire
Arena + verification + RL pipeline can run without a real model.  When a
``seed`` is provided by the Arena proxy, the server deterministically picks
one of several variants (correct / buggy / inefficient) so that GRPO group
sampling sees reward variance within a group.
"""

import json
import random
import re
from http.server import HTTPServer, BaseHTTPRequestHandler


SOLUTIONS = {
    "two_sum": """def two_sum(nums: list[int], target: int) -> list[int]:
    seen = {}
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []
""",
    "reverse_string": """def reverse_string(s: list[str]) -> None:
    left, right = 0, len(s) - 1
    while left < right:
        s[left], s[right] = s[right], s[left]
        left += 1
        right -= 1
""",
    "longest_common_prefix": """def longest_common_prefix(strs: list[str]) -> str:
    if not strs:
        return ""
    prefix = strs[0]
    for s in strs[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
""",
}

# Variants used when seeded sampling is requested.  Index 0 is always correct;
# higher indices introduce clear bugs so GRPO group advantages are non-degenerate.
VARIANTS = {
    "two_sum": [
        SOLUTIONS["two_sum"],
        """def two_sum(nums: list[int], target: int) -> list[int]:
    return [0, 1]
""",
        """def two_sum(nums: list[int], target: int) -> list[int]:
    seen = {}
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [i, seen[complement]]  # order swapped
        seen[num] = i
    return []
""",
        """def two_sum(nums: list[int], target: int) -> list[int]:
    result = []
    for i, num in enumerate(nums):
        if num == target:
            result.append(i)
    return result[:2]
""",
    ],
    "reverse_string": [
        SOLUTIONS["reverse_string"],
        """def reverse_string(s: list[str]) -> list[str]:
    return s[::-1]
""",
        """def reverse_string(s: list[str]) -> None:
    left, right = 0, len(s) - 1
    while left <= right:
        s[left], s[right] = s[right], s[left]
        left += 1
        right -= 1
""",
        """def reverse_string(s: list[str]) -> None:
    s = s[::-1]
""",
    ],
    "longest_common_prefix": [
        SOLUTIONS["longest_common_prefix"],
        """def longest_common_prefix(strs: list[str]) -> str:
    return ""
""",
        """def longest_common_prefix(strs: list[str]) -> str:
    if not strs:
        return ""
    prefix = strs[0]
    for s in strs[1:]:
        while not s.startswith(prefix):
            prefix = prefix[1:]
            if not prefix:
                return ""
    return prefix
""",
        """def longest_common_prefix(strs: list[str]) -> str:
    if not strs:
        return ""
    prefix = ""
    for i in range(len(strs[0])):
        prefix += strs[0][i]
        for s in strs[1:]:
            if not s.startswith(prefix):
                prefix = prefix[:-1]
                break
    return prefix
""",
    ],
}


def detect_problem(messages: list) -> str:
    """Detect which problem is being requested from the conversation."""
    text = "\n".join(m.get("content", "") for m in messages)
    lower = text.lower()

    # Match by function signature.
    if re.search(r"def\s+two_sum\s*\(", text):
        return "two_sum"
    if re.search(r"def\s+reverse_string\s*\(", text):
        return "reverse_string"
    if re.search(r"def\s+longest_common_prefix\s*\(", text):
        return "longest_common_prefix"

    # Fallback by keywords.
    if "two sum" in lower or "target" in lower:
        return "two_sum"
    if "reverse" in lower and "string" in lower:
        return "reverse_string"
    if "common prefix" in lower:
        return "longest_common_prefix"

    return "two_sum"


def pick_solution(problem: str, seed: int | None, temperature: float) -> str:
    """Pick a solution variant.

    If ``seed`` is absent, always return the canonical correct solution so
    existing deterministic tests keep passing.  When seeded, use the seed to
    choose a variant deterministically; ``temperature`` controls how often
    non-canonical variants are selected.
    """
    variants = VARIANTS.get(problem, [SOLUTIONS.get(problem, "")])
    if seed is None or not variants:
        return variants[0]

    rng = random.Random(seed)
    # temperature > 0 biases selection toward non-canonical variants;
    # temperature == 0 forces the canonical correct answer.
    if temperature <= 0.0:
        return variants[0]

    # Probability of picking the canonical solution decreases with temperature.
    correct_weight = max(0.1, 1.0 - temperature)
    weights = [correct_weight] + [(1.0 - correct_weight) / max(1, len(variants) - 1)] * (
        len(variants) - 1
    )
    return rng.choices(variants, weights=weights, k=1)[0]


def build_mock_logprobs(content: str) -> list:
    """Generate fake per-token logprobs of the right length."""
    tokens = content.split()
    # Rough tokenization: keep some punctuation attached.
    result = []
    for t in tokens:
        result.append({"token": t, "logprob": -0.1})
        result.append({"token": " ", "logprob": -0.05})
    return result[: len(content)] or [{"token": content, "logprob": -0.1}]


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                payload = {}

            messages = payload.get("messages", [])
            problem = detect_problem(messages)

            # Arena proxy injects seed/temperature from the rollout sampling config.
            seed = payload.get("seed")
            temperature = float(payload.get("temperature", 0.0))

            code = pick_solution(problem, seed, temperature)
            content = f"```python\n{code}```"

            response = {
                "choices": [
                    {
                        "message": {"content": content},
                        "logprobs": {"content": build_mock_logprobs(code)},
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": len(code.split())},
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), MockLLMHandler)
    print(f"Mock LLM (Code Colosseum) serving on http://{args.host}:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
