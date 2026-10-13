"""Comparing words by what they say, not how they are written (P-PROJ1 follow-up).

The voiceover's words come from the transcript (Deepgram `smart_format`): numbers
are digits and currency or percent marks are attached ("$109", "60%"), and
punctuation is mostly gone. A script says "one hundred nine million dollars" and
"sixty percent". Both describe the same speech. `canonical_units` reduces a token
list to comparable units so the two can be matched; the editing code that uses it
still decides what may change (boundaries only, or timing-safe word edits).
"""

import re

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
# Words that carry no information once the number is written as digits: "60%" = "sixty percent".
# Dropped only when they follow a number: "sixty percent" = "60%", "109 million dollars" = "$109 million".
# A stray "dollars" elsewhere is a real word and stays.
_DROPPED = {"percent", "dollars", "dollar", "cents", "cent"}
_MAGNITUDES = {"thousand", "million", "billion", "trillion"}
_BIG_MAGNITUDES = {"million": 10**6, "billion": 10**9, "trillion": 10**12}
# A year said as two pairs: "twenty twenty four" = 2024, "nineteen ninety nine" = 1999,
# "nineteen oh five" = 1905. The first pair is one of these; the second is a tens word
# (with an optional ones digit), a teen, or "oh" + a digit. "twenty one" stays 21.
_YEAR_FIRST = {"seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20}
_OH = {"oh", "o", "zero"}


def plain(token: str) -> str:
    """Lower-case a token and keep only letters, digits and a decimal point between digits."""
    t = token.casefold().replace("\u2019", "'")
    t = re.sub(r"(?<=\d)[,](?=\d{3}\b)", "", t)            # 1,700,000 -> 1700000
    t = re.sub(r"[^0-9a-z.]+", "", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", "", t)                # a point that is not inside a number
    return t


def _is_number_word(word: str) -> bool:
    """True for a spelled-out number word the matcher knows."""
    return word in _ONES or word in _TENS or word == "hundred"


def _pieces(tokens: list[str]) -> tuple[list[str], list[int]]:
    """Plain-form pieces of the tokens, and the token index each piece came from.

    "sixty-five" (a hyphen between spelled-out number words) becomes two pieces so it
    matches the transcript's "65"; so does the same word with its hyphen already
    stripped ("sixtyfive", as the transcript editor stores typed words). Any other
    token is one piece.
    """
    pieces: list[str] = []
    origin: list[int] = []
    for index, token in enumerate(tokens):
        parts = [plain(part) for part in re.split(r"[-\u2010-\u2015]", token)]
        if len(parts) > 1 and all(_is_number_word(part) for part in parts):
            pieces.extend(parts)
            origin.extend([index] * len(parts))
            continue
        fused = plain(token)
        split = next(
            ((t, fused[len(t):]) for t in _TENS if fused.startswith(t) and fused[len(t):] in _ONES
             and 1 <= _ONES[fused[len(t):]] <= 9),
            None,
        )
        if split is not None:
            pieces.extend(split)
            origin.extend([index] * 2)
        else:
            pieces.append(fused)
            origin.append(index)
    return pieces, origin


def _year_at(plains: list[str], i: int) -> tuple[str, int] | None:
    """(year as digits, index after it) when a year said as two pairs starts at i, else None."""
    first = _YEAR_FIRST.get(plains[i])
    if first is None or i + 1 >= len(plains):
        return None
    j = i + 1
    second = plains[j]
    if second in _OH and j + 1 < len(plains) and plains[j + 1] in _ONES and 1 <= _ONES[plains[j + 1]] <= 9:
        return f"{first}{_ONES[plains[j + 1]]:02d}", j + 2
    if second in _TENS:
        value, j = _TENS[second], j + 1
        if j < len(plains) and plains[j] in _ONES and 1 <= _ONES[plains[j]] <= 9:
            value, j = value + _ONES[plains[j]], j + 1
        return f"{first}{value:02d}", j
    if second in _ONES and 10 <= _ONES[second] <= 19:
        return f"{first}{_ONES[second]:02d}", j + 1
    return None


def canonical_units(tokens: list[str]) -> list[tuple[str, int]]:
    """Reduce tokens to comparable units: (unit, index of the token it starts at).

    Case, punctuation, currency and percent marks are dropped; runs of spelled-out
    numbers become digits ("two thousand eight" -> "2008", "one point seven" -> "1.7",
    "twenty twenty four" -> "2024", "sixty-five" -> "65").
    """
    plains, origin = _pieces(tokens)
    units: list[tuple[str, int]] = []
    i = 0
    while i < len(plains):
        word = plains[i]
        if not word:
            i += 1
            continue
        if word in _DROPPED and units and (units[-1][0] in _MAGNITUDES or units[-1][0][:1].isdigit()):
            i += 1
            continue
        year = _year_at(plains, i)
        if year is not None:
            units.append((year[0], origin[i]))
            i = year[1]
            continue
        if word in _ONES or word in _TENS or word == "hundred":
            value, j, last = 0, i, None
            current = 0
            while j < len(plains):
                w = plains[j]
                if w in _ONES:
                    current += _ONES[w]
                elif w in _TENS:
                    current += _TENS[w]
                elif w == "hundred":
                    current = (current or 1) * 100
                elif w == "thousand":
                    value += (current or 1) * 1000
                    current = 0
                elif w in _BIG_MAGNITUDES and j + 1 < len(plains) and _is_number_word(plains[j + 1]):
                    # "one million two hundred thousand" is one number; a magnitude that
                    # ends the run ("109 million") stays a separate unit, as the transcript has it.
                    value += (current or 1) * _BIG_MAGNITUDES[w]
                    current = 0
                elif w == "and" and last in ("hundred", "thousand"):
                    pass
                else:
                    break
                last = w
                j += 1
            number = str(value + current)
            if j < len(plains) and plains[j] == "point":
                digits = []
                k = j + 1
                while k < len(plains) and plains[k] in _ONES and _ONES[plains[k]] < 10:
                    digits.append(str(_ONES[plains[k]]))
                    k += 1
                if digits:
                    number, j = f"{number}.{''.join(digits)}", k
            units.append((number, origin[i]))
            i = j
            continue
        units.append((word.replace("$", ""), origin[i]))
        i += 1
    return units


def unit_spans(tokens: list[str]) -> list[tuple[str, int, int]]:
    """(unit, first token, end token) for each canonical unit; the spans tile the token list.

    Tokens that carry no unit of their own — "percent" after a number, a lone dash —
    belong to the unit before them (or the first unit, when they lead).
    """
    units = canonical_units(tokens)
    spans: list[tuple[str, int, int]] = []
    for k, (unit, at) in enumerate(units):
        start = 0 if k == 0 else at
        end = units[k + 1][1] if k + 1 < len(units) else len(tokens)
        spans.append((unit, start, end))
    return spans
