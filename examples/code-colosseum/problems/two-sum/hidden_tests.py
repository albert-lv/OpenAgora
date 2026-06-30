from solution import two_sum


def test_negative_numbers():
    assert sorted(two_sum([-1, -2, -3, -4, -5], -8)) == [2, 4]


def test_large_numbers():
    assert sorted(two_sum([1000000, 2000000, 3000000], 4000000)) == [0, 2]


def test_unsorted_input():
    assert sorted(two_sum([1, 5, 3, 9, 7], 12)) == [2, 3]


def test_target_at_end():
    assert sorted(two_sum([0, 4, 3, 0], 0)) == [0, 3]
