from solution import evaluate


def test_precedence():
    assert evaluate("1 + 2 * 3") == 7.0


def test_unary_and_parentheses():
    assert evaluate("-5 + (2.5 * 2)") == 0.0
