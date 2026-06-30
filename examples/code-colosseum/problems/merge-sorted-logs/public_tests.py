from solution import latest_logs


def test_single_source():
    assert latest_logs([[("2024-01-01T10:00:00Z", "a")]], 1) == [
        ("2024-01-01T10:00:00Z", "a")
    ]


def test_multiple_sources():
    logs = [
        [("2024-01-01T10:00:00Z", "a")],
        [("2024-01-01T09:00:00Z", "b")],
    ]
    assert latest_logs(logs, 1) == [("2024-01-01T10:00:00Z", "a")]
