import re


_ROMAN_RE = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> int:
    if not isinstance(s, str) or not s:
        raise ValueError("empty or non-string input")
    if not _ROMAN_RE.fullmatch(s):
        raise ValueError(f"invalid Roman numeral: {s!r}")

    total = 0
    prev = 0
    for ch in reversed(s):
        val = _VALUES[ch]
        if val < prev:
            total -= val
        else:
            total += val
        prev = val
    return total
