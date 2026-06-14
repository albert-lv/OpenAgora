#!/usr/bin/env python3
"""
Mock LLM server for the Code Colosseum demo.

Returns deterministic correct Python solutions for known problems so the
entire Arena + verification + RL pipeline can run without a real model.
"""

import json
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
            code = SOLUTIONS.get(problem, SOLUTIONS["two_sum"])
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
