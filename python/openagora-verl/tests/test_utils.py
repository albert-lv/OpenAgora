"""Unit tests for openagora_verl utility helpers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openagora_verl.utils import extract_logprobs, extract_response_text


class FakeTokenizer:
    """Tokenizer stand-in that splits on whitespace for alignment checks."""

    def __init__(self):
        self.pad_token_id = 0

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [hash(token) % 1000 for token in text.split()]


def _build_trajectory(
    response_contents: list[str], logprobs: list[list[float]]
) -> list[dict]:
    assert len(response_contents) == len(logprobs)
    trajectory = []
    for content, lps in zip(response_contents, logprobs):
        trajectory.append(
            {
                "response": {
                    "choices_json": json.dumps(
                        [{"message": {"role": "assistant", "content": content}}]
                    ).encode("utf-8"),
                    "logprobs_json": json.dumps(
                        {
                            "content": [
                                {"token": str(i), "logprob": lp}
                                for i, lp in enumerate(lps)
                            ]
                        }
                    ).encode("utf-8"),
                }
            }
        )
    return trajectory


class TestExtractResponseText:
    def test_concatenates_multiple_steps(self):
        trajectory = _build_trajectory(["def add():", "    pass"], [[], []])
        assert extract_response_text(trajectory) == "def add():\n    pass"

    def test_empty_trajectory(self):
        assert extract_response_text([]) == ""

    def test_invalid_json_is_ignored(self):
        trajectory = [
            {"response": {"choices_json": b"not json"}},
            {"response": {"choices_json": b'[{"message": {"content": "ok"}}]'}},
        ]
        assert extract_response_text(trajectory) == "ok"


class TestExtractLogprobs:
    def test_extracts_and_pads(self):
        trajectory = _build_trajectory(["hello world"], [[-0.1, -0.2]])
        result = extract_logprobs(trajectory, 3)
        assert result == [-0.1, -0.2, 0.0]

    def test_truncates(self):
        trajectory = _build_trajectory(["a b c"], [[-0.1, -0.2, -0.3]])
        result = extract_logprobs(trajectory, 2)
        assert result == [-0.1, -0.2]

    def test_missing_logprobs_returns_none(self):
        trajectory = [
            {"response": {"choices_json": b'[{"message": {"content": "x"}}]'}}
        ]
        assert extract_logprobs(trajectory, 1) is None


class TestLogprobTextAlignment:
    def test_response_text_tokens_match_logprobs_count(self):
        tokenizer = FakeTokenizer()
        trajectory = _build_trajectory(["def add()", "pass"], [[-0.1, -0.2], [-0.3]])

        response_text = extract_response_text(trajectory)
        token_count = len(tokenizer.encode(response_text))
        logprobs = extract_logprobs(trajectory, token_count)

        assert logprobs is not None
        assert len(logprobs) == token_count
