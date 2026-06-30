def busy_periods(intervals: list[list[int]], k: int) -> list[list[int]]:
    if k <= 0:
        raise ValueError("k must be positive")

    events = []
    for start, end in intervals:
        if start < end:
            events.append((start, 1))
            events.append((end, -1))
        elif start == end:
            # Zero-length intervals contribute nothing.
            continue
        else:
            raise ValueError("invalid interval: start > end")

    if not events:
        return []

    # Sort by coordinate; for the same coordinate, starts (+1) before ends (-1)
    # so that coverage at the exact timestamp is correct for half-open intervals.
    events.sort(key=lambda x: (x[0], -x[1]))

    result = []
    count = 0
    i = 0
    n = len(events)
    while i < n:
        coord, delta = events[i]
        # Apply all events at this coordinate, processing starts before ends.
        j = i
        while j < n and events[j][0] == coord:
            count += events[j][1]
            j += 1

        next_coord = events[j][0] if j < n else None
        if next_coord is not None and count >= k:
            if result and result[-1][1] == coord:
                result[-1][1] = next_coord
            else:
                result.append([coord, next_coord])
        i = j

    return result
