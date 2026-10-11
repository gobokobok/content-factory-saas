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


def plain(token: str) -> str:
    """Lower-case a token and keep only letters, digits and a decimal point between digits."""
    t = token.casefold().replace("\u2019", "'")
    t = re.sub(r"(?<=\d)[,](?=\d{3}\b)", "", t)            # 1,700,000 -> 1700000
    t = re.sub(r"[^0-9a-z.]+", "", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", "", t)                # a point that is not inside a number
    return t


def canonical_units(tokens: list[str]) -> list[tuple[str, int]]:
    """Reduce tokens to comparable units: (unit, index of the token it starts at).

    Case, punctuation, currency and percent marks are dropped; runs of spelled-out
    numbers become digits ("two thousand eight" -> "2008", "one point seven" -> "1.7").
    """
    plains = [plain(t) for t in tokens]
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
            units.append((number, i))
            i = j
            continue
        units.append((word.replace("$", ""), i))
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
