import pytest

from solution import sparse_matvec


def test_larger_matrix():
    matrix = {
        (0, 0): 1,
        (0, 2): 2,
        (1, 1): 3,
        (2, 0): 4,
        (2, 2): 5,
    }
    vec = [1, 2, 3]
    assert sparse_matvec(matrix, (3, 3), vec) == [7.0, 6.0, 19.0]


def test_single_element():
    assert sparse_matvec({(0, 0): 5}, (1, 1), [2]) == [10.0]


def test_invalid_shape():
    with pytest.raises(ValueError):
        sparse_matvec({}, (0, 2), [1, 2])
    with pytest.raises(ValueError):
        sparse_matvec({}, (-1, 2), [1, 2])
    with pytest.raises(ValueError):
        sparse_matvec({}, (2, 2, 2), [1, 2, 3])


def test_vector_length_mismatch():
    with pytest.raises(ValueError):
        sparse_matvec({(0, 0): 1}, (2, 2), [1])


def test_out_of_bounds_key():
    with pytest.raises(ValueError):
        sparse_matvec({(2, 0): 1}, (2, 2), [1, 2])
    with pytest.raises(ValueError):
        sparse_matvec({(0, -1): 1}, (2, 2), [1, 2])


def test_float_values():
    result = sparse_matvec({(0, 0): 1.5, (0, 1): 2.5}, (1, 2), [2.0, 4.0])
    assert result == [pytest.approx(13.0)]
