from solution import roman_to_int


def test_basic_values():
    assert roman_to_int("III") == 3
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9


def test_invalid_empty():
    import pytest

    with pytest.raises(ValueError):
        roman_to_int("")
