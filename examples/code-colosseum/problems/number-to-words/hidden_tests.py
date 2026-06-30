import pytest

from solution import number_to_words


def test_small_numbers():
    assert number_to_words(1) == "one"
    assert number_to_words(10) == "ten"
    assert number_to_words(15) == "fifteen"
    assert number_to_words(20) == "twenty"
    assert number_to_words(21) == "twenty-one"
    assert number_to_words(30) == "thirty"
    assert number_to_words(99) == "ninety-nine"


def test_hundreds():
    assert number_to_words(100) == "one hundred"
    assert number_to_words(101) == "one hundred one"
    assert number_to_words(110) == "one hundred ten"
    assert number_to_words(111) == "one hundred eleven"
    assert number_to_words(121) == "one hundred twenty-one"
    assert number_to_words(999) == "nine hundred ninety-nine"


def test_scales():
    assert number_to_words(1000) == "one thousand"
    assert number_to_words(1001) == "one thousand one"
    assert number_to_words(12345) == "twelve thousand three hundred forty-five"
    assert number_to_words(1_000_000) == "one million"
    assert number_to_words(1_000_000_000) == "one billion"
    assert number_to_words(1_000_000_000_000) == "one trillion"


def test_complex_numbers():
    assert number_to_words(1_001_001) == "one million one thousand one"
    assert number_to_words(1_000_000_012) == "one billion twelve"
    assert number_to_words(999_999_999_999) == (
        "nine hundred ninety-nine billion "
        "nine hundred ninety-nine million "
        "nine hundred ninety-nine thousand "
        "nine hundred ninety-nine"
    )
    assert number_to_words(10_000_020_000) == "ten billion twenty thousand"


def test_out_of_range():
    with pytest.raises(ValueError):
        number_to_words(-1)
    with pytest.raises(ValueError):
        number_to_words(1_000_000_000_001)


def test_no_trailing_spaces():
    assert number_to_words(1_000_000).strip() == number_to_words(1_000_000)
    assert "  " not in number_to_words(1_000_000)
