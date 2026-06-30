import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from mock_llm_colosseum import detect_problem, pick_solution


def test_detect_two_sum():
    msgs = [{"role": "user", "content": "def two_sum(nums, target):\nTwo Sum"}]
    assert detect_problem(msgs) == "two_sum"


def test_detect_is_valid():
    msgs = [{"role": "user", "content": "def is_valid(s):\nValid Parentheses"}]
    assert detect_problem(msgs) == "is_valid"


def test_pick_solution_variants_enabled():
    os.environ.pop("DISABLE_VARIANTS", None)
    variants = {pick_solution("two_sum", i, 0.7) for i in range(100)}
    assert len(variants) > 1


def test_pick_solution_variants_disabled():
    os.environ["DISABLE_VARIANTS"] = "1"
    variants = {pick_solution("two_sum", i, 0.7) for i in range(100)}
    assert len(variants) == 1
    os.environ.pop("DISABLE_VARIANTS", None)
