import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "training"))

from reward_shaper import compute_reward


def test_full_pass():
    report = {"reward": 1.0, "stdout": "0.01s"}
    r = compute_reward(report, num_steps=1)
    assert 0.95 < r <= 1.0


def test_partial_pass():
    report = {"reward": 0.5, "stdout": ""}
    r = compute_reward(report, num_steps=1)
    assert 0.15 < r < 0.25


def test_fail():
    report = {"reward": 0.0, "stdout": ""}
    r = compute_reward(report, num_steps=1)
    assert r == 0.0


def test_no_report():
    r = compute_reward(None, num_steps=3)
    assert r == 0.0
