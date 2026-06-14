import pytest
from solution import longest_common_prefix


def test_single_string():
    assert longest_common_prefix(["alone"]) == "alone"


def test_empty_list():
    assert longest_common_prefix([]) == ""


def test_all_same():
    assert longest_common_prefix(["test", "test", "test"]) == "test"


def test_prefix_is_full_string():
    assert longest_common_prefix(["ab", "abc", "abcd"]) == "ab"
