"""P-HARD1-S3 — regression suite for word matching (word_match, align_text, edits_from_text).

Word matching was fixed three times on 2026-10-11 against data nobody could see. This
suite pins the behaviour on a corpus of transcript / script pairs: the forms the
voiceover transcript (Deepgram smart_format) writes against the forms a script writes.
Every case that broke on DEV is here; add a pasted case to CORPUS when the next one does.

Two surfaces share the matcher and are both covered:
  - the script view     — align_text / align_text_to_words (boundaries only, words never change)
  - the transcript editor — edits_from_text (words may change, timing-safe)
"""

import pytest

from cf_platform.core.word_match import canonical_units, unit_spans
from cf_platform.workers.storyboard_edit import StoryboardEditError, align_text, align_text_to_words
from cf_platform.workers.transcript_edit import TranscriptEditError, edits_from_text
from cf_platform.workers.voice_production import VoiceWordTimestamp


def _words(text: str) -> list[VoiceWordTimestamp]:
    """Transcript words, 300 ms each, one per whitespace token."""
    return [
        VoiceWordTimestamp(word=t, start_ms=i * 300, end_ms=(i + 1) * 300, confidence=1.0)
        for i, t in enumerate(text.split())
    ]


def _units(text: str) -> list[str]:
    """Canonical units of a phrase, without positions."""
    return [u for u, _ in canonical_units(text.split())]


# ── 1. Canonical units: the same speech in both written forms reduces to the same units ──

SAME_SPEECH = [
    # (transcript form, script form)
    ("$109 million", "one hundred nine million dollars"),
    ("$109 million", "one hundred and nine million dollars"),
    ("60%", "sixty percent"),
    ("60 percent", "sixty percent"),
    ("2008", "two thousand eight"),
    ("2008", "two thousand and eight"),
    ("1.7", "one point seven"),
    ("1.75", "one point seven five"),
    ("$1.7 million", "one point seven million dollars"),
    ("1,200,000", "one million two hundred thousand"),
    ("$530,000", "five hundred thirty thousand dollars"),
    ("65", "sixty-five"),
    ("65%", "sixty-five percent"),
    ("3,500", "three thousand five hundred"),
    ("100", "one hundred"),
    ("21", "twenty one"),
    ("14", "fourteen"),
    # years said as two pairs (the open case from 2026-10-11)
    ("2024", "twenty twenty four"),
    ("2020", "twenty twenty"),
    ("2015", "twenty fifteen"),
    ("2031", "twenty thirty one"),
    ("1999", "nineteen ninety nine"),
    ("1980", "nineteen eighty"),
    ("1905", "nineteen oh five"),
    ("1776", "seventeen seventy six"),
    ("1900", "nineteen hundred"),
    ("in 2024 prices rose", "in twenty twenty four prices rose"),
    ("since 1999 the rate", "since nineteen ninety nine the rate"),
]


@pytest.mark.parametrize(("transcript", "script"), SAME_SPEECH)
def test_same_speech_reduces_to_the_same_units(transcript: str, script: str) -> None:
    """A number written two ways is one unit sequence."""
    assert _units(transcript) == _units(script)


DIFFERENT_SPEECH = [
    ("2024", "twenty twenty five"),
    ("1999", "nineteen ninety eight"),
    ("21", "twenty two"),
    ("60%", "seventy percent"),
    ("$109 million", "one hundred ten million dollars"),
    ("2008", "two thousand nine"),
]


@pytest.mark.parametrize(("transcript", "script"), DIFFERENT_SPEECH)
def test_different_numbers_stay_different(transcript: str, script: str) -> None:
    """The matcher never equates two different numbers."""
    assert _units(transcript) != _units(script)


def test_twenty_one_is_not_read_as_a_year() -> None:
    """Only a pair of pairs is a year: 'twenty one' is 21, 'twenty twenty one' is 2021."""
    assert _units("twenty one") == ["21"]
    assert _units("twenty twenty one") == ["2021"]


def test_percent_and_dollars_are_dropped_only_after_a_number() -> None:
    """A stray 'dollars' is a real word and stays; after a number it is the currency mark."""
    assert _units("the dollars") == ["the", "dollars"]
    assert _units("ten dollars") == ["10"]
    assert _units("fifty percent") == ["50"]


def test_hyphenated_words_that_are_not_numbers_are_untouched() -> None:
    """Only hyphens between spelled-out numbers split; other hyphenated words stay one word."""
    assert _units("long-term rates") == ["longterm", "rates"]


def test_unit_spans_tile_the_tokens_with_years_and_hyphens() -> None:
    """Spans cover every token exactly once, so edit ranges stay aligned."""
    tokens = "in twenty twenty four the sixty-five percent drop".split()
    spans = unit_spans(tokens)
    assert spans[0][1] == 0
    for (_, _, end), (_, start, _) in zip(spans, spans[1:], strict=False):
        assert end == start
    assert spans[-1][2] == len(tokens)
    assert [u for u, _, _ in spans] == ["in", "2024", "the", "65", "drop"]


# ── 2. Script view: boundaries only, words never change ──────────────────────

# Each case: the transcript, the script as pasted (paragraph per scene), expected start words.
CORPUS = [
    pytest.param(
        "Home prices rose $109 million in 2008 and 60% of buyers waited",
        "Home prices rose one hundred nine million dollars in two thousand eight\n\nand sixty percent of buyers waited",
        [0, 7],
        id="currency-year-percent",
    ),
    pytest.param(
        "In 2024 the median hit $420,000 across the country",
        "In twenty twenty four the median hit four hundred twenty thousand dollars\n\nacross the country",
        [0, 6],
        id="year-as-two-pairs",
    ),
    pytest.param(
        "Back in 1999 rates were 7.5% and nobody cared",
        "Back in nineteen ninety nine rates were seven point five percent\n\nand nobody cared",
        [0, 6],
        id="two-pair-year-decimal-percent",
    ),
    pytest.param(
        "Rates fell 1.7 points then another 2 points",
        "Rates fell one point seven points\n\nthen another two points",
        [0, 4],
        id="decimal",
    ),
    pytest.param(
        "Only 65% of owners are over 65 years old",
        "Only sixty-five percent of owners\n\nare over sixty-five years old",
        [0, 4],
        id="hyphenated-number",
    ),
    pytest.param(
        "Rents are up Wages are not",
        "rents are up.\n\nWages, are not!",
        [0, 3],
        id="case-and-punctuation-only",
    ),
]


@pytest.mark.parametrize(("transcript", "script", "expected"), CORPUS)
def test_script_view_maps_paragraphs_to_start_words(transcript: str, script: str, expected: list[int]) -> None:
    """Paragraph breaks land on the right transcript words across number spellings."""
    result = align_text(_words(transcript), script)
    assert result.starts == expected
    assert result.differences == []


def test_script_view_text_identical_to_the_transcript_is_exact() -> None:
    """Pasting the transcript's own tokens with breaks is the exact path."""
    words = _words("one two three four five six")
    starts, exact = align_text_to_words(words, "one two three\n\nfour five six")
    assert starts == [0, 3]
    assert exact is True


def test_script_view_a_few_changed_words_is_accepted_and_reported() -> None:
    """Text that reads differently in a few places uses its breaks and names the differences."""
    words = _words("home prices rose sharply last year and buyers waited for rates to fall again soon")
    text = "home prices rose slightly last year\n\nand buyers waited for rates to fall again soon"
    result = align_text(words, text)
    assert result.starts == [0, 6]
    assert result.exact is False
    assert any("sharply" in d and "slightly" in d for d in result.differences)


def test_script_view_a_different_text_is_refused_with_the_first_differences() -> None:
    """Mostly different text is a StoryboardEditError that names what differs."""
    words = _words("home prices rose sharply last year")
    with pytest.raises(StoryboardEditError, match="First differences"):
        align_text(words, "completely unrelated sentence about cooking pasta tonight")


def test_script_view_empty_text_is_refused() -> None:
    """Whitespace-only text is refused, not matched to nothing."""
    with pytest.raises(StoryboardEditError):
        align_text(_words("one two three"), "   \n\n  ")


def test_script_view_first_paragraph_always_starts_at_word_zero() -> None:
    """Even when the first paragraph opens on a differing word, scene one starts at 0."""
    words = _words("alpha beta gamma delta epsilon zeta")
    result = align_text(words, "alpha beta gamma\n\ndelta epsilon zeta")
    assert result.starts[0] == 0


# ── 3. Transcript editor: words may change, but a rewrite of the same speech is not an edit ──


@pytest.mark.parametrize(("transcript", "script", "_expected"), CORPUS)
def test_transcript_editor_sees_the_same_speech_as_nothing_to_change(
    transcript: str, script: str, _expected: list[int]
) -> None:
    """Pasting the script (paragraph breaks and all) over its own transcript is 'nothing to change'."""
    flat = " ".join(script.split())
    with pytest.raises(TranscriptEditError, match="nothing to change"):
        edits_from_text(_words(transcript), flat)


def test_transcript_editor_dollars_after_a_number_is_not_an_added_word() -> None:
    """'dollars' straight after a number was read as an added word on 2026-10-11."""
    words = _words("it cost $109 million last year")
    with pytest.raises(TranscriptEditError, match="nothing to change"):
        edits_from_text(words, "it cost one hundred nine million dollars last year")


def test_transcript_editor_stray_dollars_is_still_an_added_word() -> None:
    """A 'dollars' that does not follow a number is a real insertion and is refused."""
    words = _words("it cost a lot last year")
    with pytest.raises(TranscriptEditError, match="adds"):
        edits_from_text(words, "it cost a lot dollars last year")


def test_transcript_editor_real_correction_beside_a_rewritten_number_comes_through() -> None:
    """A wording fix next to a differently written number is one edit; the number is left alone."""
    words = _words("rates hit 7.5% in 2024 and bankers paniced")
    edits = edits_from_text(words, "rates hit seven point five percent in twenty twenty four and bankers panicked")
    assert [(e.start, e.end, e.text) for e in edits] == [(7, 7, "panicked")]


def test_transcript_editor_year_said_as_two_pairs_matches_its_digits() -> None:
    """'twenty twenty four' typed over '2024' is not a change (was refused as '20 24')."""
    words = _words("it happened in 2024 again")
    with pytest.raises(TranscriptEditError, match="nothing to change"):
        edits_from_text(words, "it happened in twenty twenty four again")


def test_transcript_editor_different_year_is_a_real_edit() -> None:
    """Typing a different year over a spoken one is an edit, not a match."""
    words = _words("it happened in 2024 again")
    edits = edits_from_text(words, "it happened in twenty twenty five again")
    assert len(edits) == 1
    assert edits[0].start == 3
    assert edits[0].end == 3
