from solution import max_sub_array


def test_example():
    assert max_sub_array([-2, 1, -3, 4, -1, 2, 1, -5, 4]) == 6


def test_single_element():
    assert max_sub_array([1]) == 1
    assert max_sub_array([-1]) == -1


def test_all_negative():
    assert max_sub_array([-5, -2, -8, -1]) == -1


def test_all_positive():
    assert max_sub_array([1, 2, 3, 4, 5]) == 15


def test_large_array():
    nums = [1] * 10000
    assert max_sub_array(nums) == 10000
