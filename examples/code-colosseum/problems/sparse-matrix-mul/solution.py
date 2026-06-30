def sparse_matvec(
    matrix: dict[tuple[int, int], float], shape: tuple[int, int], vec: list[float]
) -> list[float]:
    if len(shape) != 2:
        raise ValueError("shape must be a tuple of two integers")
    rows, cols = shape
    if rows <= 0 or cols <= 0:
        raise ValueError("shape dimensions must be positive")
    if len(vec) != cols:
        raise ValueError("vector length must match matrix column count")

    result = [0.0 for _ in range(rows)]
    for (row, col), value in matrix.items():
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError(f"matrix key out of bounds: {(row, col)}")
        result[row] += value * vec[col]

    return result
