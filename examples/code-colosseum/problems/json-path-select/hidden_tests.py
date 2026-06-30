from solution import select


def test_empty_path():
    data = {"a": 1}
    assert select(data, "") == [data]


def test_missing_key():
    assert select({"a": 1}, "b") == []
    assert select({"a": {"b": 1}}, "a.c") == []


def test_list_index():
    assert select([10, 20, 30], "[1]") == [20]
    assert select({"items": [10, 20]}, "items.[0]") == [10]


def test_index_out_of_range():
    assert select([10, 20], "[5]") == []


def test_wildcard_dict_sorted():
    data = {"b": 2, "a": 1}
    assert select(data, "*") == [1, 2]


def test_nested_wildcards():
    data = {
        "a": [{"x": 1}, {"x": 2}],
        "b": [{"x": 3}],
    }
    assert select(data, "*.[0].x") == [1, 3]
    assert select(data, "*.*.x") == [1, 2, 3]


def test_wildcard_over_scalar():
    assert select({"a": 1}, "*.b") == []


def test_mixed_path():
    data = {
        "users": [
            {"name": "alice", "posts": [{"title": "a"}, {"title": "b"}]},
            {"name": "bob", "posts": [{"title": "c"}]},
        ]
    }
    assert select(data, "users.*.name") == ["alice", "bob"]
    assert select(data, "users.[0].posts.*.title") == ["a", "b"]
