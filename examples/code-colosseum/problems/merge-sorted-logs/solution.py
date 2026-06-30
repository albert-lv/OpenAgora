def latest_logs(logs: list[list[tuple[str, str]]], n: int) -> list[tuple[str, str]]:
    if n <= 0:
        return []

    entries = []
    for source_idx, source in enumerate(logs):
        for entry_idx, entry in enumerate(source):
            # Include source order and entry order for stable sorting.
            entries.append((entry[0], source_idx, entry_idx, entry))

    # Sort descending by timestamp. Python's sort is stable, so ties keep the
    # original source order and, within a source, the original entry order.
    entries.sort(key=lambda x: x[0], reverse=True)

    return [item[3] for item in entries[:n]]
