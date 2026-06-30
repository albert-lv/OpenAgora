import pytest

from backend.pricing import estimate_cost


def test_estimate_cost_with_usage():
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}
    cost = estimate_cost(usage)
    expected = 1000 * 0.0015 / 1000 + 500 * 0.0060 / 1000
    assert cost == pytest.approx(expected)


def test_estimate_cost_empty():
    assert estimate_cost({}) == 0.0
    assert estimate_cost(None) == 0.0
