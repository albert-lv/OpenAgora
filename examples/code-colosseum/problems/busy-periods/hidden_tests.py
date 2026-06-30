import pytest

from solution import busy_periods


def test_empty_intervals():
    assert busy_periods([], 1) == []


def test_no_overlap_meet_threshold():
    assert busy_periods([[1, 2], [3, 4], [5, 6]], 2) == []


def test_adjacent_intervals_merge():
    assert busy_periods([[1, 3], [3, 5]], 1) == [[1, 5]]


def test_zero_length_ignored():
    assert busy_periods([[1, 1], [1, 2]], 1) == [[1, 2]]
    assert busy_periods([[1, 1], [2, 2]], 1) == []


def test_unsorted_input():
    assert busy_periods([[5, 7], [1, 4], [3, 6]], 2) == [[3, 4], [5, 6]]


def test_k_larger_than_max_overlap():
    assert busy_periods([[1, 4], [2, 5], [3, 6]], 4) == []


def test_invalid_k():
    with pytest.raises(ValueError):
        busy_periods([[1, 2]], 0)
    with pytest.raises(ValueError):
        busy_periods([[1, 2]], -1)


def test_invalid_interval():
    with pytest.raises(ValueError):
        busy_periods([[3, 1]], 1)


def test_exact_threshold_boundaries():
    assert busy_periods([[1, 4], [2, 5], [3, 6]], 3) == [[3, 4]]


def test_large_overlap():
    intervals = [[i, i + 10] for i in range(5)]
    assert busy_periods(intervals, 3) == [[2, 12]]
