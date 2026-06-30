def _select(current, segments):
    if not segments:
        return [current]

    segment = segments[0]
    rest = segments[1:]

    if segment == "*":
        if isinstance(current, dict):
            results = []
            for key in sorted(current.keys()):
                results.extend(_select(current[key], rest))
            return results
        if isinstance(current, list):
            results = []
            for item in current:
                results.extend(_select(item, rest))
            return results
        return []

    if segment.startswith("[") and segment.endswith("]"):
        try:
            idx = int(segment[1:-1])
        except ValueError:
            return []
        if isinstance(current, list) and 0 <= idx < len(current):
            return _select(current[idx], rest)
        return []

    if isinstance(current, dict) and segment in current:
        return _select(current[segment], rest)

    return []


def select(data: dict | list, path: str) -> list:
    segments = [s for s in path.split(".") if s]
    return _select(data, segments)
