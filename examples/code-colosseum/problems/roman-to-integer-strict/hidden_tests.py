import pytest

from solution import roman_to_int


def test_valid_single_digits():
    assert roman_to_int("I") == 1
    assert roman_to_int("V") == 5
    assert roman_to_int("X") == 10
    assert roman_to_int("L") == 50
    assert roman_to_int("C") == 100
    assert roman_to_int("D") == 500
    assert roman_to_int("M") == 1000


def test_valid_composite():
    assert roman_to_int("XLVII") == 47
    assert roman_to_int("XCIX") == 99
    assert roman_to_int("CD") == 400
    assert roman_to_int("CM") == 900
    assert roman_to_int("MCMXCIV") == 1994
    assert roman_to_int("MMMCMXCIX") == 3999
    assert roman_to_int("MMMDCCCLXXXVIII") == 3888


def test_invalid_repeated():
    for bad in ("IIII", "VV", "LL", "DD", "MMMM", "XXXX", "CCCC"):
        with pytest.raises(ValueError):
            roman_to_int(bad)


def test_invalid_subtractive():
    for bad in (
        "IL",
        "IC",
        "ID",
        "IM",
        "VX",
        "VL",
        "VC",
        "VD",
        "VM",
        "LC",
        "LD",
        "LM",
        "DM",
        "IIV",
        "IIX",
        "XXC",
        "CCD",
    ):
        with pytest.raises(ValueError):
            roman_to_int(bad)


def test_invalid_characters_and_case():
    for bad in ("ABC", "iv", "MCMXCIV ", "  ", "123"):
        with pytest.raises(ValueError):
            roman_to_int(bad)


def test_invalid_too_long():
    with pytest.raises(ValueError):
        roman_to_int("MMMMCMXCIX")
