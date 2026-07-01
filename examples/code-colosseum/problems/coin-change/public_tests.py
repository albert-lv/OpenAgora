from solution import coin_change


def test_basic():
    assert coin_change([1, 2, 5], 11) == 3
