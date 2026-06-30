import pytest

from solution import evaluate


def test_basic_arithmetic():
    assert evaluate("3 + 4") == 7.0
    assert evaluate("10 - 4") == 6.0
    assert evaluate("3 * 4") == 12.0
    assert evaluate("10 / 4") == 2.5


def test_operator_precedence():
    assert evaluate("3 + 4 * 2") == 11.0
    assert evaluate("(3 + 4) * 2") == 14.0
    assert evaluate("10 / 2 + 3") == 8.0
    assert evaluate("10 / (2 + 3)") == 2.0


def test_nested_parentheses():
    assert evaluate("((1 + 2) * (3 + 4))") == 21.0
    assert evaluate("(((5)))") == 5.0


def test_unary_operators():
    assert evaluate("-5") == -5.0
    assert evaluate("+5") == 5.0
    assert evaluate("--5") == 5.0
    assert evaluate("---5") == -5.0
    assert evaluate("- ( - ( - 1 ) )") == -1.0


def test_whitespace():
    assert evaluate("  1  +   2 * 3  ") == 7.0
    assert evaluate("\t3\n+\r4") == 7.0


def test_decimals():
    assert evaluate("3.5 + 2.1") == pytest.approx(5.6)
    assert evaluate("0.25 * 4") == 1.0


def test_division_by_zero():
    with pytest.raises(ValueError):
        evaluate("1 / 0")
    with pytest.raises(ValueError):
        evaluate("1 / (2 - 2)")


def test_invalid_syntax():
    for bad in ("", "   ", "2 +", "+ * 3", "2 + a", "(1 + 2", "1 + 2)", "3.4.5 + 1"):
        with pytest.raises(ValueError):
            evaluate(bad)
