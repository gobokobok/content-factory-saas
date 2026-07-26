"""Tests for src/footage_qa.py — QAResult, qa_score, pick_best."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.footage_qa import (
    _CLIP_PASS_THRESHOLD,
    _MIN_PHOTO_WIDTH,
    _MIN_VIDEO_HEIGHT,
    _MIN_VIDEO_WIDTH,
    QAResult,
    pick_best,
    qa_score,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _candidate(
    width: int = 1920,
    height: int = 1080,
    duration_seconds: float | None = None,
    source: str = "pexels",
) -> SimpleNamespace:
    """Minimal candidate object matching the _Candidate interface."""
    return SimpleNamespace(
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        source=source,
    )


def _entry(
    clip_type: str = "hard_cut",
    duration_s: float = 5.0,
    primary_query: str = "housing market crisis",
) -> SimpleNamespace:
    """Minimal manifest entry object matching the ManifestEntry interface."""
    return SimpleNamespace(
        clip_type=clip_type,
        duration_s=duration_s,
        primary_query=primary_query,
    )


# ── qa_score — resolution checks ─────────────────────────────────────────────


class TestQaScoreResolution:
    def test_video_passes_minimum_dimensions(self):
        c = _candidate(width=_MIN_VIDEO_WIDTH, height=_MIN_VIDEO_HEIGHT)
        result = qa_score(c, _entry(clip_type="hard_cut"))
        assert result.resolution_ok is True

    def test_video_below_min_width_fails(self):
        c = _candidate(width=_MIN_VIDEO_WIDTH - 1, height=_MIN_VIDEO_HEIGHT)
        result = qa_score(c, _entry(clip_type="hard_cut"))
        assert result.resolution_ok is False
        assert result.passed is False

    def test_video_below_min_height_fails(self):
        c = _candidate(width=_MIN_VIDEO_WIDTH, height=_MIN_VIDEO_HEIGHT - 1)
        result = qa_score(c, _entry(clip_type="hard_cut"))
        assert result.resolution_ok is False

    def test_photo_passes_minimum_width(self):
        c = _candidate(width=_MIN_PHOTO_WIDTH, height=400)
        result = qa_score(c, _entry(clip_type="still_with_motion"))
        assert result.resolution_ok is True

    def test_photo_below_min_width_fails(self):
        c = _candidate(width=_MIN_PHOTO_WIDTH - 1, height=1080)
        result = qa_score(c, _entry(clip_type="still_with_motion"))
        assert result.resolution_ok is False

    def test_photo_height_not_checked(self):
        """Photo resolution gate only checks width, not height."""
        c = _candidate(width=_MIN_PHOTO_WIDTH, height=1)  # tiny height
        result = qa_score(c, _entry(clip_type="still_with_motion"))
        assert result.resolution_ok is True


# ── qa_score — duration checks ────────────────────────────────────────────────


class TestQaScoreDuration:
    def test_video_duration_fits(self):
        c = _candidate(duration_seconds=10.0)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=5.0))
        assert result.duration_ok is True

    def test_video_duration_exact_fit(self):
        c = _candidate(duration_seconds=5.0)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=5.0))
        assert result.duration_ok is True

    def test_video_duration_too_short_fails(self):
        c = _candidate(duration_seconds=3.0)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=5.0))
        assert result.duration_ok is False
        assert result.passed is False

    def test_video_duration_none_skipped(self):
        """No duration data on candidate → duration check treated as OK."""
        c = _candidate(duration_seconds=None)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=5.0))
        assert result.duration_ok is True

    def test_photo_duration_never_checked(self):
        """Photo entries: duration_ok always True regardless of data."""
        c = _candidate(width=_MIN_PHOTO_WIDTH, duration_seconds=0.5)
        result = qa_score(c, _entry(clip_type="still_with_motion", duration_s=10.0))
        assert result.duration_ok is True

    def test_entry_duration_zero_skips_duration_check(self):
        """entry.duration_s=0 → duration check skipped (treated as OK)."""
        c = _candidate(duration_seconds=0.1)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=0.0))
        assert result.duration_ok is True


# ── qa_score — CLIP disabled ──────────────────────────────────────────────────


class TestQaScoreClipDisabled:
    def test_clip_score_is_none_when_no_reranker(self):
        c = _candidate()
        result = qa_score(c, _entry(), image_data=b"imgdata", clip_reranker=None)
        assert result.clip_score is None
        assert result.clip_enabled is False

    def test_clip_score_is_none_when_no_image_data(self):
        reranker = MagicMock()
        c = _candidate()
        result = qa_score(c, _entry(), image_data=None, clip_reranker=reranker)
        assert result.clip_score is None

    def test_passed_when_clip_disabled_and_resolution_ok(self):
        c = _candidate(width=1920, height=1080, duration_seconds=10.0)
        result = qa_score(c, _entry(clip_type="hard_cut", duration_s=5.0))
        assert result.passed is True


# ── qa_score — CLIP enabled ───────────────────────────────────────────────────


class TestQaScoreClipEnabled:
    def _make_clip_reranker(self, score: float) -> MagicMock:
        """Mock reranker whose score_image always returns the given value."""
        reranker = MagicMock()
        reranker.score_image.return_value = score
        return reranker

    def test_clip_score_above_threshold_passes(self):
        reranker = self._make_clip_reranker(_CLIP_PASS_THRESHOLD + 0.01)
        c = _candidate()
        with patch("src.footage_qa.Image") as mock_pil:
            mock_pil.open.return_value.convert.return_value = MagicMock()
            result = qa_score(c, _entry(), image_data=b"fake_img", clip_reranker=reranker)
        assert result.clip_score == pytest.approx(_CLIP_PASS_THRESHOLD + 0.01)
        assert result.passed is True

    def test_clip_score_below_threshold_fails(self):
        reranker = self._make_clip_reranker(_CLIP_PASS_THRESHOLD - 0.01)
        c = _candidate()
        with patch("src.footage_qa.Image") as mock_pil:
            mock_pil.open.return_value.convert.return_value = MagicMock()
            result = qa_score(c, _entry(), image_data=b"fake_img", clip_reranker=reranker)
        assert result.passed is False

    def test_clip_encoding_failure_does_not_reject(self):
        """If CLIP encoding throws, the gate treats the candidate as passing."""
        reranker = MagicMock()
        reranker.score_image.side_effect = RuntimeError("GPU OOM")
        c = _candidate()
        with patch("src.footage_qa.Image") as mock_pil:
            mock_pil.open.return_value.convert.return_value = MagicMock()
            result = qa_score(c, _entry(), image_data=b"fake_img", clip_reranker=reranker)
        assert result.clip_score is None
        assert result.passed is True  # encoding failure → accept


# ── pick_best ─────────────────────────────────────────────────────────────────


class TestPickBest:
    def _make_pair(
        self,
        width: int = 1920,
        height: int = 1080,
        passed: bool = True,
        clip_score: float | None = None,
        source: str = "pexels",
    ) -> tuple:
        c = _candidate(width=width, height=height, source=source)
        r = QAResult(
            passed=passed,
            resolution_ok=passed,
            duration_ok=True,
            clip_score=clip_score,
            clip_enabled=clip_score is not None,
        )
        return c, r

    def test_raises_on_empty_list(self):
        with pytest.raises(ValueError):
            pick_best([])

    def test_single_candidate_returned(self):
        pair = self._make_pair()
        result = pick_best([pair])
        assert result is pair[0]

    def test_passed_candidate_wins_over_failed(self):
        good = self._make_pair(width=800, height=600, passed=True)
        bad = self._make_pair(width=3840, height=2160, passed=False)
        assert pick_best([bad, good]) is good[0]

    def test_higher_resolution_wins_when_no_clip(self):
        small = self._make_pair(width=1280, height=720)
        large = self._make_pair(width=1920, height=1080)
        assert pick_best([small, large]) is large[0]

    def test_higher_clip_score_wins(self):
        low_score = self._make_pair(clip_score=0.25)
        high_score = self._make_pair(clip_score=0.80)
        assert pick_best([low_score, high_score]) is high_score[0]

    def test_last_resort_uses_resolution_when_all_failed(self):
        """When all candidates failed QA, pick highest resolution as last resort."""
        low = self._make_pair(width=800, height=600, passed=False)
        high = self._make_pair(width=1920, height=1080, passed=False)
        assert pick_best([low, high]) is high[0]
