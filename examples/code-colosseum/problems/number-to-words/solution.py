_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]

_TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]

_SCALES = ["", "thousand", "million", "billion", "trillion"]


def _below_hundred(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    ten, unit = divmod(n, 10)
    if unit == 0:
        return _TENS[ten]
    return f"{_TENS[ten]}-{_UNITS[unit]}"


def _below_thousand(n: int) -> str:
    if n < 100:
        return _below_hundred(n)
    hundred, rest = divmod(n, 100)
    result = f"{_UNITS[hundred]} hundred"
    if rest:
        result += " " + _below_hundred(rest)
    return result


def number_to_words(n: int) -> str:
    if not isinstance(n, int):
        raise TypeError("input must be an integer")
    if n < 0 or n > 1_000_000_000_000:
        raise ValueError("input out of supported range")
    if n == 0:
        return "zero"

    parts = []
    scale_index = 0
    while n > 0:
        chunk = n % 1000
        if chunk:
            chunk_words = _below_thousand(chunk)
            scale_word = _SCALES[scale_index]
            if scale_word:
                parts.append(f"{chunk_words} {scale_word}")
            else:
                parts.append(chunk_words)
        n //= 1000
        scale_index += 1

    return " ".join(reversed(parts))
