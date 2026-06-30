from solution import is_valid


def test_example_1():
    assert is_valid("()") is True


def test_example_2():
    assert is_valid("()[]{}") is True


def test_example_3():
    assert is_valid("(]") is False
