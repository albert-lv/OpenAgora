from solution import number_to_words


def test_zero():
    assert number_to_words(0) == "zero"


def test_basic_hyphen():
    assert number_to_words(123) == "one hundred twenty-three"


def test_large_with_zeros():
    assert number_to_words(1_000_010) == "one million ten"
