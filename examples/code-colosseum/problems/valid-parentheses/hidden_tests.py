from solution import is_valid


def test_empty():
    assert is_valid("") is True


def test_single_open():
    assert is_valid("(") is False


def test_single_close():
    assert is_valid(")") is False


def test_nested():
    assert is_valid("{[()]}") is True


def test_mismatched_nested():
    assert is_valid("{[(])}") is False


def test_long_valid():
    assert is_valid("(" * 1000 + ")" * 1000) is True


def test_long_invalid():
    assert is_valid("(" * 1000 + ")" * 999) is False
