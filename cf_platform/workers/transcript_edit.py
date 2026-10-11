"""Timing-safe transcript edits for uploaded voiceovers (P14b-S2).

The transcript's words carry the audio's timing, and scenes later index into the
word list (`start_word` / `end_word`). So an edit may change what a word *says*,
never *when* it is spoken:

* replace one word with one word — the word keeps its time slot;
* replace one word with several, or several with one — the new words share the
  combined slot (split evenly, strictly increasing, summing to the original slot);
* replace several with the same number — each keeps its own slot;
* never delete a spoken word, never add a word that is not spoken (use on-screen
  text for that).

Everything here is pure: lists in, lists out, `TranscriptEditError` on a refused
edit. A whole edit is validated before any word changes, so a refusal changes nothing.
"""

import difflib

from pydantic import BaseModel

from cf_platform.core.word_match import unit_spans
from cf_platform.workers.voice_production import _PUNCT_RE, VoiceWordTimestamp

_EDGE_PUNCT = ".,!?;:"
ON_SCREEN_HINT = "Words that are not spoken belong in on-screen text, not in the transcript."


class TranscriptEditError(ValueError):
    """An edit that would break the audio timing; the message says what to do instead."""


class WordEdit(BaseModel):
    """Replace words `start`..`end` (0-based, inclusive) with the words in `text`."""

    start: int
    end: int
    text: str


def sanitize_token(token: str) -> str:
    """Strip a typed token to the form stored in the transcript (as Deepgram words are)."""
    return _PUNCT_RE.sub("", token).strip()


def _match_key(token: str) -> str:
    """Comparison form of a token: no punctuation, no edge dots, case-folded."""
    return sanitize_token(token).strip(_EDGE_PUNCT).casefold()


def transcript_text(words: list[VoiceWordTimestamp]) -> str:
    """Return the transcript as the run's script: the words, space-separated."""
    return " ".join(w.word for w in words)


def _tokens(text: str) -> list[str]:
    """Split typed text into sanitized tokens, dropping tokens that are only punctuation."""
    return [tok for tok in (sanitize_token(t) for t in text.split()) if tok]


def _replacement_words(old: list[VoiceWordTimestamp], tokens: list[str]) -> list[VoiceWordTimestamp]:
    """Build the words that replace `old` under the shared-slot rule, or raise."""
    m, n = len(old), len(tokens)
    old_text = " ".join(w.word for w in old)
    if n == 0:
        raise TranscriptEditError(
            f"This would delete the spoken word(s) \"{old_text}\". Spoken words stay in the "
            "transcript — replace them with what is actually said instead."
        )
    confidence = min(w.confidence for w in old)
    if m == n:
        return [w.model_copy(update={"word": tok}) for w, tok in zip(old, tokens)]
    if m > 1 and n > 1:
        raise TranscriptEditError(
            f"Cannot replace {m} words with {n}: replace one word with several, several with "
            "one, or the same number of words — split this into separate edits."
        )
    start_ms, end_ms = old[0].start_ms, old[-1].end_ms
    if m > 1:  # several → one: the new word takes the combined slot
        return [VoiceWordTimestamp(word=tokens[0], start_ms=start_ms, end_ms=end_ms, confidence=confidence)]
    slot = end_ms - start_ms  # one → several: split the slot evenly
    if slot < n:
        raise TranscriptEditError(
            f"The word \"{old_text}\" is spoken too quickly to split into {n} words "
            f"({slot} ms). Replace it with fewer words."
        )
    bounds = [start_ms + (slot * k) // n for k in range(n + 1)]
    return [
        VoiceWordTimestamp(word=tok, start_ms=bounds[i], end_ms=bounds[i + 1], confidence=confidence)
        for i, tok in enumerate(tokens)
    ]


def apply_word_edits(words: list[VoiceWordTimestamp], edits: list[WordEdit]) -> list[VoiceWordTimestamp]:
    """Return a new word list with every edit applied, or raise TranscriptEditError.

    Indices refer to `words` as passed in. Edits must not overlap. Nothing is
    changed unless every edit is valid.
    """
    if not edits:
        raise TranscriptEditError("No edits given.")
    ordered = sorted(edits, key=lambda e: e.start)
    previous_end = -1
    for edit in ordered:
        if edit.start < 0 or edit.end < edit.start or edit.end >= len(words):
            raise TranscriptEditError(
                f"Word range {edit.start}-{edit.end} is outside the transcript ({len(words)} words)."
            )
        if edit.start <= previous_end:
            raise TranscriptEditError("Edits overlap — each word can be edited once per change.")
        previous_end = edit.end
    result: list[VoiceWordTimestamp] = []
    cursor = 0
    for edit in ordered:
        result.extend(words[cursor:edit.start])
        result.extend(_replacement_words(words[edit.start:edit.end + 1], _tokens(edit.text)))
        cursor = edit.end + 1
    result.extend(words[cursor:])
    return result


def edits_from_text(words: list[VoiceWordTimestamp], text: str) -> list[WordEdit]:
    """Map corrected transcript text onto the existing words, or raise TranscriptEditError.

    Words are compared by what they say: case, punctuation and the way a number is
    written do not count ("$109 million" = "one hundred nine million dollars",
    "60%" = "sixty percent"), so text copied from the script matches the transcript
    it was spoken from. A differing stretch must obey the same rule as a manual edit:
    one-to-one, one-to-several or several-to-one. A stretch that only deletes or only
    inserts words is refused.
    """
    new_tokens = _tokens(text)
    if not new_tokens:
        raise TranscriptEditError("The corrected text is empty.")
    old_tokens = [w.word for w in words]
    old_spans, new_spans = unit_spans(old_tokens), unit_spans(new_tokens)
    matcher = difflib.SequenceMatcher(None, [u for u, _, _ in old_spans], [u for u, _, _ in new_spans], autojunk=False)

    def old_range(i1: int, i2: int) -> tuple[int, int]:
        """Word indices [from, to) covered by units i1..i2."""
        if not old_spans:
            return 0, 0
        first = old_spans[i1][1] if i1 < len(old_spans) else len(old_tokens)
        last = old_spans[i2 - 1][2] if i2 > i1 else first
        return first, last

    def new_range(j1: int, j2: int) -> tuple[int, int]:
        """Token indices [from, to) covered by units j1..j2."""
        first = new_spans[j1][1] if j1 < len(new_spans) else len(new_tokens)
        last = new_spans[j2 - 1][2] if j2 > j1 else first
        return first, last

    edits: list[WordEdit] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        w1, w2 = old_range(i1, i2)
        t1, t2 = new_range(j1, j2)
        if tag == "delete":
            gone = " ".join(old_tokens[w1:w2])
            raise TranscriptEditError(
                f"The text leaves out the spoken word(s) \"{gone}\". Spoken words cannot be removed."
            )
        if tag == "insert":
            added = " ".join(new_tokens[t1:t2])
            raise TranscriptEditError(f"The text adds \"{added}\", which is not spoken. {ON_SCREEN_HINT}")
        old_n, new_n = w2 - w1, t2 - t1
        if old_n == new_n:
            edits.extend(WordEdit(start=w1 + k, end=w1 + k, text=new_tokens[t1 + k]) for k in range(old_n))
        elif old_n == 1 or new_n == 1:
            edits.append(WordEdit(start=w1, end=w2 - 1, text=" ".join(new_tokens[t1:t2])))
        else:
            was = " ".join(old_tokens[w1:w2])
            now = " ".join(new_tokens[t1:t2])
            raise TranscriptEditError(
                f"Cannot map \"{was}\" onto \"{now}\" ({old_n} words to {new_n}). Change one word "
                "at a time, or replace one word with several."
            )
    if not edits:
        raise TranscriptEditError(
            "The text says the same as the transcript — nothing to change. (Numbers and punctuation "
            "written differently do not count.)"
        )
    return edits


def describe_edits(words: list[VoiceWordTimestamp], edits: list[WordEdit]) -> list[str]:
    """One readable line per edit, e.g. 'word 12: "wheel" → "or wheel"'."""
    lines = []
    for edit in sorted(edits, key=lambda e: e.start):
        old = " ".join(w.word for w in words[edit.start:edit.end + 1])
        new = " ".join(_tokens(edit.text))
        place = f"word {edit.start + 1}" if edit.start == edit.end else f"words {edit.start + 1}-{edit.end + 1}"
        lines.append(f'{place}: "{old}" → "{new}"')
    return lines
