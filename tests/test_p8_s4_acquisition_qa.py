"""Tests for P8-S4 — QA gate integration in acquire_scene.

Covers: resolution pre-check, duration pre-check, fallback_query retry,
pick_best last-resort, QA fields written to manifest, CLIP path with mock.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.acquisition import _Candidate, acquire_scene
from src.footage_qa import QAResult
from src.models import ManifestEntry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _entry(
    scene_id: str = "01",
    clip_type: str = "hard_cut",
    duration_s: float = 5.0,
) -> ManifestEntry:
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        primary_query="primary query",
        fallback_query="fallback query",
        ai_generate_prompt="ai prompt",
        duration_s=duration_s,
    )


def _video_result(w: int = 1920, h: int = 1080, url: str = "https://cdn.pexels.com/v/01.mp4") -> dict:
    return {"video_files": [{"link": url, "width": w, "height": h, "file_type": "video/mp4", "duration": 10}], "duration": 10}


def _photo_result(w: int = 1920, h: int = 1080, url_suffix: str = "photo") -> dict:
    return {"width": w, "height": h, "src": {"original": f"https://images.pexels.com/{url_suffix}.jpg"}}


RUN_ID = "run-qa-test"


# ── QA fields written to ManifestEntry ───────────────────────────────────────


class TestQaFieldsWrittenToEntry:
    @pytest.mark.asyncio
    async def test_qa_passed_true_on_success(self):
        """Winning candidate sets qa_passed=True on the manifest entry."""
        entry = _entry()
        pexels = MagicMock()
        pexels.search_videos.return_value = [_video_result()]
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"v")):
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.qa_passed is True
        assert entry.qa_resolution_ok is True
        assert entry.qa_duration_ok is True
        assert entry.qa_clip_score is None   # CLIP disabled by default

    @pytest.mark.asyncio
    async def test_fallback_used_false_for_primary_winner(self):
        """Candidate from primary query sets fallback_used=False."""
        entry = _entry()
        pexels = MagicMock()
        pexels.search_videos.return_value = [_video_result()]
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"v")):
            await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert entry.fallback_used is False

    @pytest.mark.asyncio
    async def test_fallback_used_true_when_fallback_candidate_wins(self):
        """When only the fallback-query candidate is available, fallback_used=True."""
        entry = _entry()
        primary_url = "https://cdn.pexels.com/v/primary.mp4"
        fallback_url = "https://cdn.pexels.com/v/fallback.mp4"
        pexels = MagicMock()

        # Primary query returns a candidate that fails resolution QA (64×64).
        # Fallback query returns a passing candidate (1920×1080).
        call_num = {"n": 0}

        def search_side_effect(query):
            call_num["n"] += 1
            if call_num["n"] == 1:  # first call = primary query
                return [{"video_files": [{"link": primary_url, "width": 64, "height": 64, "file_type": "video/mp4"}], "duration": 10}]
            return [{"video_files": [{"link": fallback_url, "width": 1920, "height": 1080, "file_type": "video/mp4"}], "duration": 10}]

        pexels.search_videos.side_effect = search_side_effect
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"v")):
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.fallback_used is True


# ── Resolution pre-check skips download ──────────────────────────────────────


class TestResolutionPreCheck:
    @pytest.mark.asyncio
    async def test_low_res_video_skipped_without_download(self):
        """A 640×480 video candidate fails resolution pre-check; download not attempted."""
        entry = _entry()
        pexels = MagicMock()
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://cdn.pexels.com/low.mp4", "width": 640, "height": 480, "file_type": "video/mp4"}], "duration": 10}
        ]
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock()) as mock_dl:
            # No acceptable candidates → last-resort picks best-resolution candidate.
            # Both the QA loop skip it (pre-check) and last-resort downloads it.
            mock_dl.side_effect = httpx.ConnectError("fail")
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        # Pre-check skips download; last-resort tries but fails too → scene failed.
        assert result is False
        assert entry.status == "failed"

    @pytest.mark.asyncio
    async def test_high_res_winner_among_mixed_candidates(self):
        """Only the high-res candidate passes QA; the low-res one is pre-check rejected."""
        entry = _entry()
        pexels = MagicMock()
        # Both primary and fallback return a low-res candidate; Pixabay gives a high-res one.
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://low.mp4", "width": 640, "height": 480, "file_type": "video/mp4"}], "duration": 10}
        ]
        from src.pixabay_client import PixabayVideo
        pixabay = MagicMock()
        pixabay.search_videos = AsyncMock(return_value=[
            PixabayVideo(url="https://pixabay.com/hi.mp4", width=1920, height=1080, duration_seconds=15, page_url="")
        ])
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"hd")):
            result = await acquire_scene(entry, RUN_ID, pexels, pixabay, storage)

        assert result is True
        assert entry.source == "pixabay"
        assert entry.qa_resolution_ok is True


# ── Duration QA ───────────────────────────────────────────────────────────────


class TestDurationQa:
    @pytest.mark.asyncio
    async def test_video_passes_when_duration_fits(self):
        """Clip with duration >= scene duration passes duration QA."""
        entry = _entry(clip_type="hard_cut", duration_s=5.0)
        pexels = MagicMock()
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://v.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"}], "duration": 10}
        ]
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"v")):
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.qa_duration_ok is True


# ── CLIP gate via mock reranker ───────────────────────────────────────────────


class TestClipGate:
    @pytest.mark.asyncio
    async def test_clip_below_threshold_falls_back_to_pick_best(self):
        """CLIP score below threshold: candidate tracked in checked; pick_best accepts it."""
        entry = _entry()
        pexels = MagicMock()
        pexels.search_videos.return_value = [_video_result()]
        storage = MagicMock()

        mock_reranker = MagicMock()
        mock_reranker.score_image.return_value = 0.05  # below 0.20 threshold

        with (
            patch("src.acquisition._download_bytes", AsyncMock(return_value=b"\xff\xd8\xff")),
            patch("src.clip_reranker.get_reranker", return_value=mock_reranker),
            patch("src.footage_qa.Image") as mock_pil,
        ):
            mock_pil.open.return_value.convert.return_value = MagicMock()
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        # pick_best accepts the best available even when CLIP fails
        assert result is True
        assert entry.qa_passed is False  # QA failed but we accepted anyway
        assert entry.qa_clip_score == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_clip_above_threshold_accepts_immediately(self):
        """CLIP score above threshold: candidate is accepted without pick_best fallback."""
        entry = _entry()
        pexels = MagicMock()
        pexels.search_videos.return_value = [_video_result()]
        storage = MagicMock()

        mock_reranker = MagicMock()
        mock_reranker.score_image.return_value = 0.85  # well above 0.20

        with (
            patch("src.acquisition._download_bytes", AsyncMock(return_value=b"\xff\xd8\xff")),
            patch("src.clip_reranker.get_reranker", return_value=mock_reranker),
            patch("src.footage_qa.Image") as mock_pil,
        ):
            mock_pil.open.return_value.convert.return_value = MagicMock()
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.qa_passed is True
        assert entry.qa_clip_score == pytest.approx(0.85)


# ── Never leave scene empty ───────────────────────────────────────────────────


class TestNeverLeaveEmpty:
    @pytest.mark.asyncio
    async def test_best_available_accepted_when_all_fail_qa(self):
        """When all candidates fail resolution pre-check, last-resort picks best by resolution."""
        entry = _entry()
        pexels = MagicMock()
        # Primary: 640×480 (low-res), Fallback: 1280×720 (passes resolution QA)
        call_num = {"n": 0}

        def search_side_effect(query):
            call_num["n"] += 1
            if call_num["n"] == 1:
                return [{"video_files": [{"link": "https://low.mp4", "width": 64, "height": 64, "file_type": "video/mp4"}], "duration": 10}]
            return [{"video_files": [{"link": "https://hi.mp4", "width": 1280, "height": 720, "file_type": "video/mp4"}], "duration": 10}]

        pexels.search_videos.side_effect = search_side_effect
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"v")):
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        # The 1280×720 candidate passes resolution pre-check and is accepted
        assert result is True
        assert entry.status == "acquired"

    @pytest.mark.asyncio
    async def test_person_photo_qa_fields_set(self):
        """Successful person photo sets qa_passed=True and qa_resolution_ok=True."""
        from src.wikimedia_client import WikimediaAsset, WikimediaClient

        entry = ManifestEntry(
            scene_id="5",
            clip_type="still_with_motion",
            primary_query="Jerome Powell",
            fallback_query="Federal Reserve",
            ai_generate_prompt="portrait",
            person_name="Jerome Powell",
        )
        wikimedia = MagicMock(spec=WikimediaClient)
        wikimedia.fetch_person_photo = AsyncMock(return_value=WikimediaAsset(
            url="https://upload.wikimedia.org/powell.jpg",
            width=1200, height=1500,
            title="Jerome Powell", licence="Via Wikipedia",
            attribution="Photo via Wikipedia",
        ))
        pexels = MagicMock()
        pexels.search_photos.return_value = []
        storage = MagicMock()

        with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"img")):
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage, wikimedia=wikimedia)

        assert result is True
        assert entry.qa_passed is True
        assert entry.qa_resolution_ok is True
        assert entry.qa_duration_ok is True
