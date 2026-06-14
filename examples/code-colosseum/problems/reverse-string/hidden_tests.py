import pytest
from solution import reverse_string


def test_empty():
    s = []
    reverse_string(s)
    assert s == []


def test_single():
    s = ["a"]
    reverse_string(s)
    assert s == ["a"]


def test_two_chars():
    s = ["a", "b"]
    reverse_string(s)
    assert s == ["b", "a"]


def test_palindrome():
    s = ["r", "a", "c", "e", "c", "a", "r"]
    reverse_string(s)
    assert s == ["r", "a", "c", "e", "c", "a", "r"]
