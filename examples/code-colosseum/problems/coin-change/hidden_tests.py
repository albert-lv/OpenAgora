from solution import coin_change


def test_example():
    assert coin_change([1, 2, 5], 11) == 3


def test_impossible():
    assert coin_change([2], 3) == -1


def test_zero_amount():
    assert coin_change([1], 0) == 0


def test_single_coin():
    assert coin_change([1], 5) == 5


def test_multiple_denominations():
    assert coin_change([1, 3, 4], 6) == 2
