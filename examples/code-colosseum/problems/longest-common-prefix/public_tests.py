import pytest
from solution import longest_common_prefix


def test_example_1():
    assert longest_common_prefix(["flower", "flow", "flight"]) == "fl"


def test_example_2():
    assert longest_common_prefix(["dog", "racecar", "car"]) == ""
