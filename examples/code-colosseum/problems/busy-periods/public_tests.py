from solution import busy_periods


def test_basic_overlap():
    assert busy_periods([[1, 3], [2, 4], [5, 6]], 2) == [[2, 3]]


def test_full_coverage():
    assert busy_periods([[1, 5], [2, 6], [3, 7]], 1) == [[1, 7]]
