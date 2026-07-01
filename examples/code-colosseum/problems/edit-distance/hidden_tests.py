from solution import min_distance


def test_example():
    assert min_distance("horse", "ros") == 3


def test_example2():
    assert min_distance("intention", "execution") == 5


def test_identical():
    assert min_distance("abc", "abc") == 0


def test_one_empty():
    assert min_distance("", "abc") == 3
    assert min_distance("abc", "") == 3


def test_single_replace():
    assert min_distance("a", "b") == 1


def test_longer():
    assert min_distance("dinitrophenylhydrazine", "benzalphenylhydrazone") == 7
