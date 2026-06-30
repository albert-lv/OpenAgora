def _split(path: str) -> list[str]:
    # Remove a single leading '/' and ignore a trailing '/'.
    if path == "/":
        return []
    if path.startswith("/"):
        path = path[1:]
    if path.endswith("/"):
        path = path[:-1]
    return path.split("/")


def match_route(
    path: str, routes: list[tuple[str, str]]
) -> tuple[str, dict[str, str]] | None:
    path_segments = _split(path)

    for name, pattern in routes:
        pattern_segments = _split(pattern)
        params: dict[str, str] = {}
        pi = 0
        pj = 0
        matched = True

        while pi < len(pattern_segments):
            pat = pattern_segments[pi]
            if pat == "*":
                if pi != len(pattern_segments) - 1:
                    # Invalid pattern: treat as no match.
                    matched = False
                    break
                remainder = "/".join(path_segments[pj:])
                params["*"] = remainder
                pj = len(path_segments)
                pi += 1
                break

            if pj >= len(path_segments):
                matched = False
                break

            seg = path_segments[pj]
            if pat.startswith(":"):
                param_name = pat[1:]
                if not param_name or not seg:
                    matched = False
                    break
                params[param_name] = seg
                pi += 1
                pj += 1
            else:
                if pat != seg:
                    matched = False
                    break
                pi += 1
                pj += 1

        if matched and pj == len(path_segments) and pi == len(pattern_segments):
            return name, params

    return None
