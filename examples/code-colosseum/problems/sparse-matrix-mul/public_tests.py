from solution import sparse_matvec


def test_basic():
    matrix = {(0, 0): 1, (0, 1): 2, (1, 0): 3}
    assert sparse_matvec(matrix, (2, 2), [1, 2]) == [5.0, 3.0]


def test_empty_matrix():
    assert sparse_matvec({}, (2, 3), [1, 2, 3]) == [0.0, 0.0]
