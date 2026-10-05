"""Timing-safe transcript edit rule (P14b-S2) — pure functions, no HTTP."""

import pytest

from cf_platform.workers.transcript_edit import (
    TranscriptEditError,
    WordEdit,
    apply_word_edits,
    describe_edits,
    edits_from_text,
    transcript_text,
)
from cf_platform.workers.voice_production import VoiceWordTimestamp


def words(*spoken: str, ms: int = 400) -> list[VoiceWordTimestamp]:
    """Back-to-back words of `ms` each, in the order given."""
    return [
        VoiceWordTimestamp(word=w, start_ms=i * ms, end_ms=(i + 1) * ms, confidence=0.9)
        for i, w in enumerate(spoken)
    ]


def slot(ws: list[VoiceWordTimestamp]) -> tuple[int, int]:
    """(start of first, end of last)."""
    return ws[0].start_ms, ws[-1].end_ms


def test_replace_one_word_keeps_its_slot():
    src = words("pedals", "are", "wheel")
    out = apply_word_edits(src, [WordEdit(start=1, end=1, text="or")])
    assert [w.word for w in out] == ["pedals", "or", "wheel"]
    assert [(w.start_ms, w.end_ms) for w in out] == [(w.start_ms, w.end_ms) for w in src]


def test_one_word_to_several_splits_the_slot_evenly_and_monotonically():
    src = words("a", "tomorrow", "b", ms=1000)
    out = apply_word_edits(src, [WordEdit(start=1, end=1, text="to morrow again")])
    mid = out[1:4]
    assert [w.word for w in mid] == ["to", "morrow", "again"]
    assert slot(mid) == (1000, 2000)                       # sums to the original slot
    assert all(a.end_ms == b.start_ms for a, b in zip(mid, mid[1:]))   # contiguous
    assert all(w.start_ms < w.end_ms for w in mid)         # strictly increasing
    assert [(w.start_ms, w.end_ms) for w in (out[0], out[4])] == [(0, 1000), (2000, 3000)]
    assert len(out) == 5


def test_uneven_split_still_sums_to_the_slot():
    src = words("x", ms=1000)
    out = apply_word_edits(src, [WordEdit(start=0, end=0, text="a b c")])
    assert slot(out) == (0, 1000) and [w.end_ms - w.start_ms for w in out] == [333, 333, 334]


def test_several_words_to_one_share_the_combined_slot():
    src = words("pedal", "s", "wheel", ms=500)
    out = apply_word_edits(src, [WordEdit(start=0, end=1, text="pedals")])
    assert [w.word for w in out] == ["pedals", "wheel"]
    assert (out[0].start_ms, out[0].end_ms) == (0, 1000)
    assert out[0].confidence == 0.9


def test_same_count_replacement_keeps_each_slot():
    src = words("a", "b", "c")
    out = apply_word_edits(src, [WordEdit(start=0, end=1, text="x y")])
    assert [(w.word, w.start_ms) for w in out[:2]] == [("x", 0), ("y", 400)]


def test_unequal_many_to_many_is_refused():
    with pytest.raises(TranscriptEditError, match="Cannot replace 3 words with 2"):
        apply_word_edits(words("a", "b", "c", "d"), [WordEdit(start=0, end=2, text="x y")])


def test_deleting_a_spoken_word_is_refused_with_advice():
    with pytest.raises(TranscriptEditError, match="delete the spoken word"):
        apply_word_edits(words("a", "b"), [WordEdit(start=1, end=1, text="  ")])
    with pytest.raises(TranscriptEditError, match="delete"):
        apply_word_edits(words("a", "b"), [WordEdit(start=1, end=1, text="--")])   # only punctuation


def test_the_whole_edit_is_rejected_as_a_unit():
    src = words("a", "b", "c")
    with pytest.raises(TranscriptEditError):
        apply_word_edits(src, [WordEdit(start=0, end=0, text="ok"), WordEdit(start=2, end=2, text="")])
    assert [w.word for w in src] == ["a", "b", "c"]            # input untouched


def test_range_and_overlap_are_validated():
    with pytest.raises(TranscriptEditError, match="outside the transcript"):
        apply_word_edits(words("a"), [WordEdit(start=0, end=3, text="x")])
    with pytest.raises(TranscriptEditError, match="overlap"):
        apply_word_edits(words("a", "b", "c"), [WordEdit(start=0, end=1, text="x"), WordEdit(start=1, end=2, text="y")])


def test_a_word_too_short_to_split_is_refused():
    src = [VoiceWordTimestamp(word="x", start_ms=0, end_ms=2)]
    with pytest.raises(TranscriptEditError, match="too quickly"):
        apply_word_edits(src, [WordEdit(start=0, end=0, text="a b c")])


def test_several_edits_apply_against_the_original_indices():
    src = words("a", "b", "c", "d", ms=100)
    out = apply_word_edits(src, [WordEdit(start=3, end=3, text="D"), WordEdit(start=0, end=0, text="x y")])
    assert [w.word for w in out] == ["x", "y", "b", "c", "D"]


def test_punctuation_is_stripped_from_typed_words():
    out = apply_word_edits(words("a"), [WordEdit(start=0, end=0, text="don't,")])
    assert out[0].word == "dont"


# ── Rebuild from text ────────────────────────────────────────────────────


def test_text_maps_punctuation_and_contractions_onto_existing_words():
    src = words("dont", "stop", "wheel")
    edits = edits_from_text(src, "Don't stop, wheels")
    assert [(e.start, e.end, e.text) for e in edits] == [(2, 2, "wheels")]
    assert describe_edits(src, edits) == ['word 3: "wheel" → "wheels"']


def test_text_one_to_many_and_many_to_one():
    split = words("see", "tomorrow", "ok")
    out = apply_word_edits(split, edits_from_text(split, "see to morrow ok"))
    assert transcript_text(out) == "see to morrow ok" and slot(out[1:3]) == slot(split[1:2])
    merged = words("pedal", "s", "wheel")
    out = apply_word_edits(merged, edits_from_text(merged, "pedals wheel"))
    assert transcript_text(out) == "pedals wheel" and slot(out[:1]) == slot(merged[:2])


def test_text_with_a_changed_word_beside_a_merge_is_refused_with_advice():
    # "pedal s are" → "pedals or" is one differing stretch of 3 words onto 2.
    with pytest.raises(TranscriptEditError, match="one word at a time"):
        edits_from_text(words("pedal", "s", "are", "wheel"), "pedals or wheel")


def test_text_that_drops_a_word_is_refused():
    with pytest.raises(TranscriptEditError, match="leaves out the spoken word"):
        edits_from_text(words("a", "b", "c"), "a c")


def test_text_that_adds_a_word_is_refused_and_points_to_on_screen_text():
    with pytest.raises(TranscriptEditError, match="on-screen text"):
        edits_from_text(words("a", "b"), "a very b")


def test_identical_or_empty_text_is_refused():
    with pytest.raises(TranscriptEditError, match="nothing to change"):
        edits_from_text(words("a", "b"), "A, b.")
    with pytest.raises(TranscriptEditError, match="empty"):
        edits_from_text(words("a"), "  ")


def test_text_edits_leave_untouched_words_exactly_as_they_were():
    src = words("one", "two", "three", "four")
    out = apply_word_edits(src, edits_from_text(src, "one 2 three four"))
    assert out[0] == src[0] and out[2:] == src[2:] and out[1].word == "2"
