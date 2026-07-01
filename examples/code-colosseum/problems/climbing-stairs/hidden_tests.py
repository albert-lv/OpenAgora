from solution import climb_stairs


def test_small():
    assert climb_stairs(1) == 1
    assert climb_stairs(2) == 2
    assert climb_stairs(3) == 3


def test_medium():
    assert climb_stairs(10) == 89


def test_large():
    assert climb_stairs(35) == 14930352
