from solution import select


def test_nested_dict():
    assert select({"a": {"b": 1}}, "a.b") == [1]


def test_wildcard_list():
    assert select([{"x": 1}, {"x": 2}], "*.x") == [1, 2]
