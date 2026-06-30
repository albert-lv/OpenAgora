from solution import latest_logs


def test_stable_ties_across_sources():
    logs = [
        [("2024-01-01T10:00:00Z", "a1")],
        [("2024-01-01T10:00:00Z", "b1")],
        [("2024-01-01T10:00:00Z", "c1")],
    ]
    result = latest_logs(logs, 2)
    assert result == [
        ("2024-01-01T10:00:00Z", "a1"),
        ("2024-01-01T10:00:00Z", "b1"),
    ]


def test_stable_ties_within_source():
    logs = [
        [
            ("2024-01-01T10:00:00Z", "a1"),
            ("2024-01-01T10:00:00Z", "a2"),
        ]
    ]
    assert latest_logs(logs, 2) == [
        ("2024-01-01T10:00:00Z", "a1"),
        ("2024-01-01T10:00:00Z", "a2"),
    ]


def test_n_zero_or_negative():
    assert latest_logs([[("2024-01-01T10:00:00Z", "a")]], 0) == []
    assert latest_logs([[("2024-01-01T10:00:00Z", "a")]], -5) == []


def test_n_larger_than_total():
    logs = [
        [("2024-01-01T08:00:00Z", "a")],
        [("2024-01-01T09:00:00Z", "b")],
    ]
    assert latest_logs(logs, 10) == [
        ("2024-01-01T09:00:00Z", "b"),
        ("2024-01-01T08:00:00Z", "a"),
    ]


def test_empty_sources():
    assert latest_logs([], 5) == []
    assert latest_logs([[], [], []], 5) == []


def test_does_not_modify_inputs():
    logs = [[("2024-01-01T10:00:00Z", "a")]]
    original = [list(source) for source in logs]
    latest_logs(logs, 1)
    assert logs == original


def test_mixed_ordering():
    logs = [
        [("2024-01-01T07:00:00Z", "a"), ("2024-01-01T11:00:00Z", "b")],
        [("2024-01-01T09:00:00Z", "c"), ("2024-01-01T10:00:00Z", "d")],
    ]
    assert latest_logs(logs, 3) == [
        ("2024-01-01T11:00:00Z", "b"),
        ("2024-01-01T10:00:00Z", "d"),
        ("2024-01-01T09:00:00Z", "c"),
    ]
