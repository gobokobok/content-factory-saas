"""Tests for src/acquisition.py and src/routes/assets.py."""

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.acquisition import (
    MIN_ACQUIRED_FOR_COMPLETE,
    _Candidate,
    _gather_candidates,
    _pexels_photo_candidates,
    _pexels_video_candidates,
    acquire_scene,
    run_acquisition,
)
from src.config import Settings, get_settings
from src.exceptions import PexelsError, StorageError
from src.main import app
from src.models import AssetManifest, ManifestEntry
from src.pixabay_client import PixabayClient, PixabayPhoto, PixabayVideo

# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET_NAME": "bucket",
    "ANTHROPIC_API_KEY": "ant",
    "PEXELS_API_KEY": "pex",
    "REPLICATE_API_TOKEN": "rep",
    "FREESOUND_API_KEY": "fs",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}

RUN_ID = "2026-05-22_test-run"
MANIFEST_KEY = f"runs/{RUN_ID}/asset_manifest.json"


def _entry(
    scene_id: str = "01",
    status: str = "pending",
    clip_type: str = "hard_cut",
) -> ManifestEntry:
    """Build a ManifestEntry with sensible defaults."""
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        primary_query="primary query",
        fallback_query="fallback query",
        ai_generate_prompt="ai prompt",
        status=status,
    )


def _manifest(entries: Optional[List[ManifestEntry]] = None) -> AssetManifest:
    """Build an AssetManifest with one default entry if none supplied."""
    return AssetManifest(run_id=RUN_ID, entries=entries or [_entry()])


def _pexels_video_result() -> dict:
    """Minimal Pexels video API hit with a usable video file."""
    return {
        "video_files": [
            {"link": "https://cdn.pexels.com/v/01.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"},
        ]
    }


def _pexels_photo_result(w: int = 1920, h: int = 1080) -> dict:
    """Minimal Pexels photo API hit."""
    return {
        "width": w,
        "height": h,
        "src": {"original": f"https://images.pexels.com/photos/1/photo.jpg"},
    }


def _pixabay_video(url: str = "https://cdn.pixabay.com/v/01.mp4", w: int = 1280, h: int = 720) -> PixabayVideo:
    return PixabayVideo(url=url, width=w, height=h, duration_seconds=20, page_url="")


def _pixabay_photo(url: str = "https://cdn.pixabay.com/p/01.jpg", w: int = 1920, h: int = 1080) -> PixabayPhoto:
    return PixabayPhoto(url=url, width=w, height=h, page_url="")


# ── Unit: _pexels_video_candidates ────────────────────────────────────────────


class TestPexelsVideoCandidates:
    def test_returns_candidate_for_each_valid_video(self):
        pexels = MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        result = _pexels_video_candidates(pexels, "housing")

        assert len(result) == 1
        assert result[0].source == "pexels"
        assert result[0].width == 1920
        assert result[0].url == "https://cdn.pexels.com/v/01.mp4"

    def test_pexels_error_returns_empty(self):
        pexels = MagicMock()
        pexels.search_videos.side_effect = PexelsError("rate limit")

        result = _pexels_video_candidates(pexels, "housing")

        assert result == []

    def test_no_acceptable_video_file_skipped(self):
        """Video hit with no files → no candidate."""
        pexels = MagicMock()
        pexels.search_videos.return_value = [{"video_files": []}]

        result = _pexels_video_candidates(pexels, "housing")

        assert result == []


class TestPexelsPhotoCandidates:
    def test_returns_candidate_for_qualifying_photo(self):
        pexels = MagicMock()
        pexels.search_photos.return_value = [_pexels_photo_result(3840, 2160)]

        result = _pexels_photo_candidates(pexels, "house")

        assert len(result) == 1
        assert result[0].source == "pexels"
        assert result[0].width == 3840

    def test_photo_below_minimum_excluded(self):
        pexels = MagicMock()
        pexels.search_photos.return_value = [_pexels_photo_result(1280, 720)]

        result = _pexels_photo_candidates(pexels, "house")

        assert result == []

    def test_pexels_error_returns_empty(self):
        pexels = MagicMock()
        pexels.search_photos.side_effect = PexelsError("rate limit")

        result = _pexels_photo_candidates(pexels, "house")

        assert result == []


# ── Unit: acquire_scene ───────────────────────────────────────────────────────


class TestAcquireScene:
    @pytest.mark.asyncio
    async def test_pexels_only_success(self):
        """Pexels returns best candidate; it wins and is uploaded."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"video_bytes"
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.status == "acquired"
        assert entry.source == "pexels"
        storage.upload_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_pixabay_wins_when_higher_resolution(self):
        """Pixabay candidate has higher resolution → it wins over Pexels."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        # Pexels: 1280×720
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://pexels.com/low.mp4", "width": 1280, "height": 720, "file_type": "video/mp4"}]}
        ]
        # Pixabay: 1920×1080 (higher area)
        pixabay = MagicMock()
        pixabay.search_videos = AsyncMock(return_value=[_pixabay_video(w=1920, h=1080)])

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            result = await acquire_scene(entry, RUN_ID, pexels, pixabay, storage)

        assert result is True
        assert entry.source == "pixabay"

    @pytest.mark.asyncio
    async def test_pexels_wins_when_higher_resolution(self):
        """Pexels has higher resolution → it wins over Pixabay."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        # Pexels: 1920×1080 (max usable — _pick_best_video_file filters height > 1080)
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://pexels.com/hd.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"}]}
        ]
        # Pixabay: 1280×720 (lower area → loses)
        pixabay = MagicMock()
        pixabay.search_videos = AsyncMock(return_value=[_pixabay_video(w=1280, h=720)])

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            result = await acquire_scene(entry, RUN_ID, pexels, pixabay, storage)

        assert result is True
        assert entry.source == "pexels"

    @pytest.mark.asyncio
    async def test_pixabay_skipped_when_key_absent(self):
        """pixabay=None (key absent) → only Pexels searched."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is True
        assert entry.source == "pexels"

    @pytest.mark.asyncio
    async def test_falls_back_to_next_candidate_on_download_failure(self):
        """First candidate download fails; second succeeds."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        # Pexels: high-res candidate (wins sort order)
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://pexels.com/hi.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"}]}
        ]
        pixabay = MagicMock()
        pixabay.search_videos = AsyncMock(return_value=[_pixabay_video(w=1280, h=720)])

        download_calls = [httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock()), b"bytes"]
        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = download_calls
            result = await acquire_scene(entry, RUN_ID, pexels, pixabay, storage)

        assert result is True
        assert entry.source == "pixabay"

    @pytest.mark.asyncio
    async def test_all_candidates_fail_marks_failed(self):
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = httpx.ConnectError("timeout")
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is False
        assert entry.status == "failed"

    @pytest.mark.asyncio
    async def test_no_candidates_marks_failed(self):
        """Pexels returns no results and no Pixabay key → failed."""
        entry = _entry()
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = []

        result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        assert result is False
        assert entry.status == "failed"

    @pytest.mark.asyncio
    async def test_photo_entry_routes_to_images_folder(self):
        """still_with_motion clip → asset stored under runs/run_id/images/."""
        entry = _entry(clip_type="still_with_motion")
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_photos.return_value = [_pexels_photo_result(1920, 1080)]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            await acquire_scene(entry, RUN_ID, pexels, None, storage)

        key = storage.upload_bytes.call_args[0][0]
        assert "/images/" in key

    @pytest.mark.asyncio
    async def test_deduplication_across_primary_and_fallback_queries(self):
        """Same URL returned for both primary and fallback queries → stored once."""
        entry = _entry()
        entry.primary_query = "housing"
        entry.fallback_query = "housing"  # same query → same URL
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            result = await acquire_scene(entry, RUN_ID, pexels, None, storage)

        # Only one upload despite two searches returning the same URL
        assert result is True
        assert storage.upload_bytes.call_count == 1


# ── Unit: run_acquisition ─────────────────────────────────────────────────────


class TestRunAcquisition:
    @pytest.mark.asyncio
    async def test_all_scenes_acquired(self):
        entries = [_entry("01"), _entry("02")]
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage)

        assert summary["acquired"] == 2
        assert summary["failed"] == 0
        assert summary["sources"] == {"pexels": 2}

    @pytest.mark.asyncio
    async def test_skips_already_acquired_entries(self):
        pre = _entry("01", status="acquired")
        pre.source = "pexels"
        pre.file_key = "runs/r/video/01.mp4"
        pending = _entry("02")
        manifest = _manifest([pre, pending])
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage)

        assert summary["acquired"] == 2
        # search_videos only called for the pending scene (2 queries × 1 pending = 2 calls)
        assert pexels.search_videos.call_count == 2

    @pytest.mark.asyncio
    async def test_all_pre_acquired_returns_full_count(self):
        entries = [_entry("01", status="acquired"), _entry("02", status="acquired")]
        entries[0].source = "pexels"
        entries[1].source = "pixabay"
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()

        summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage)

        pexels.search_videos.assert_not_called()
        assert summary["acquired"] == 2
        assert summary["sources"] == {"pexels": 1, "pixabay": 1}

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        entries = [_entry("01"), _entry("02")]
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()

        call_count = {"n": 0}

        async def selective_download(url: str) -> bytes:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return b"bytes"
            raise httpx.ConnectError("fail")

        pexels.search_videos.return_value = [_pexels_video_result()]
        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = selective_download
            summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage)

        assert summary["acquired"] == 1
        assert summary["failed"] == 1

    @pytest.mark.asyncio
    async def test_sources_counts_both_pexels_and_pixabay(self):
        entries = [_entry("01"), _entry("02", clip_type="still_with_motion")]
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()
        # Video scene: pexels wins (1920×1080 > pixabay 1280×720); photo scene: pixabay wins (3840×2160 > pexels 1920×1080)
        pexels.search_videos.return_value = [
            {"video_files": [{"link": "https://pexels.com/hd.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"}]}
        ]
        pexels.search_photos.return_value = [_pexels_photo_result(1920, 1080)]
        pixabay = MagicMock()
        pixabay.search_videos = AsyncMock(return_value=[_pixabay_video(w=1280, h=720)])
        pixabay.search_photos = AsyncMock(return_value=[_pixabay_photo(w=3840, h=2160)])

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            summary = await run_acquisition(RUN_ID, manifest, pexels, pixabay, storage)

        assert summary["acquired"] == 2
        assert summary["sources"]["pexels"] == 1    # video scene
        assert summary["sources"]["pixabay"] == 1   # photo scene


# ── Unit: run_acquisition — batch behaviour ────────────────────────────────────


class TestRunAcquisitionBatching:
    @pytest.mark.asyncio
    async def test_batch_grouping_all_scenes_processed(self):
        entries = [_entry(f"0{i}") for i in range(1, 5)]
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()
        pexels.search_videos.return_value = [_pexels_video_result()]

        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = b"bytes"
            summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage, batch_size=2)

        assert summary["acquired"] == 4
        assert summary["failed"] == 0

    @pytest.mark.asyncio
    async def test_partial_failure_in_batch_does_not_cancel_others(self):
        entries = [_entry("01"), _entry("02"), _entry("03")]
        manifest = _manifest(entries)
        pexels, storage = MagicMock(), MagicMock()

        call_n = {"n": 0}

        async def selective_download(url: str) -> bytes:
            call_n["n"] += 1
            # Second download attempt fails (scene 02)
            if call_n["n"] == 2:
                raise httpx.ConnectError("fail")
            return b"bytes"

        pexels.search_videos.return_value = [_pexels_video_result()]
        with patch("src.acquisition._download_bytes", new_callable=AsyncMock) as mock_dl:
            mock_dl.side_effect = selective_download
            summary = await run_acquisition(RUN_ID, manifest, pexels, None, storage, batch_size=3)

        assert summary["acquired"] == 2
        assert summary["failed"] == 1


# ── Constant ──────────────────────────────────────────────────────────────────


def test_min_acquired_for_complete_is_one():
    assert MIN_ACQUIRED_FOR_COMPLETE == 1


# ── Route integration tests ───────────────────────────────────────────────────

SAMPLE_MANIFEST_DATA = {
    "run_id": RUN_ID,
    "entries": [
        {
            "scene_id": "01",
            "clip_type": "hard_cut",
            "primary_query": "q1",
            "fallback_query": "q2",
            "ai_generate_prompt": "p",
            "status": "pending",
            "source": None,
            "file_key": None,
        }
    ],
}


@pytest.fixture()
def client(monkeypatch):
    settings = Settings(**VALID_ENV)
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


class TestAssetsRoute:
    def test_202_returns_running_with_poll_url(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {"pexels": 1}}

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert body["poll_url"] == f"/runs/{RUN_ID}/assets/status"

    def test_background_task_updates_run_log_on_success(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {"pexels": 1}}

            client.post(f"/runs/{RUN_ID}/assets")

        mock_storage.upload_json.assert_called_once()
        mock_storage.update_run_log.assert_any_call(RUN_ID, "asset_acquisition", "running")
        mock_storage.update_run_log.assert_any_call(
            RUN_ID, "asset_acquisition", "complete", output_url=MANIFEST_KEY
        )

    def test_background_task_updates_run_log_on_zero_acquired(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 0, "failed": 1, "sources": {}}

            client.post(f"/runs/{RUN_ID}/assets")

        mock_storage.update_run_log.assert_any_call(
            RUN_ID, "asset_acquisition", "failed", output_url=MANIFEST_KEY
        )

    def test_404_when_manifest_not_found(self, client):
        with patch("src.routes.assets.R2Client") as mock_r2_cls:
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.side_effect = StorageError("not found")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 404

    def test_acquisition_error_handled_by_background_task(self, client):
        import src.routes.assets as assets_module

        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.side_effect = Exception("unexpected crash")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 202
        assert assets_module._ACQUISITION_STATE.get(RUN_ID, {}).get("status") == "failed"
        mock_storage.update_run_log.assert_any_call(
            RUN_ID, "asset_acquisition", "failed", error="unexpected crash"
        )

    def test_pexels_client_instantiated_with_correct_settings(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.PexelsClient") as mock_pexels_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {}}

            client.post(f"/runs/{RUN_ID}/assets")

        mock_pexels_cls.assert_called_once_with(api_key="pex", per_page=5)

    def test_pixabay_skipped_when_key_absent(self, client):
        """PIXABAY_API_KEY defaults to '' → PixabayClient not instantiated."""
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.PixabayClient") as mock_pixabay_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {}}

            client.post(f"/runs/{RUN_ID}/assets")

        mock_pixabay_cls.assert_not_called()
        # run_acquisition called with pixabay=None
        _, kwargs = mock_acquire.call_args
        positional_args = mock_acquire.call_args[0]
        # pixabay is the 4th positional arg (index 3): run_id, manifest, pexels, pixabay, storage
        assert positional_args[3] is None

    def test_manifest_write_failure_handled_by_background_task(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition", new_callable=AsyncMock) as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {"pexels": 1}}
            mock_storage.upload_json.side_effect = StorageError("write failed")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 202
        mock_storage.update_run_log.assert_any_call(
            RUN_ID, "asset_acquisition", "failed", error="write failed"
        )


# ── assets/status endpoint ────────────────────────────────────────────────────


class TestAcquisitionStatusRoute:
    def test_returns_running_while_task_in_progress(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE[RUN_ID] = {
            "status": "running", "acquired": 0, "failed": 0,
            "sources": {}, "manifest_key": None, "error": None,
        }
        resp = client.get(f"/runs/{RUN_ID}/assets/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_returns_complete_after_success(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE[RUN_ID] = {
            "status": "complete", "acquired": 5, "failed": 0,
            "sources": {"pexels": 3, "pixabay": 2}, "manifest_key": MANIFEST_KEY, "error": None,
        }
        resp = client.get(f"/runs/{RUN_ID}/assets/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert body["acquired"] == 5
        assert body["manifest_key"] == MANIFEST_KEY

    def test_returns_failed_with_error(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE[RUN_ID] = {
            "status": "failed", "acquired": 0, "failed": 1,
            "sources": {}, "manifest_key": None, "error": "All candidates exhausted",
        }
        resp = client.get(f"/runs/{RUN_ID}/assets/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error"] == "All candidates exhausted"

    def test_404_when_no_acquisition_started(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE.pop("nonexistent-run", None)
        resp = client.get("/runs/nonexistent-run/assets/status")
        assert resp.status_code == 404

    def test_fallback_returns_failed_when_run_log_shows_running(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE.pop(RUN_ID, None)
        run_log = {"steps": {"asset_acquisition": {"status": "running", "error": None}}}
        with patch("src.routes.assets.R2Client") as mock_r2_cls:
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = run_log
            resp = client.get(f"/runs/{RUN_ID}/assets/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "interrupted" in resp.json()["error"].lower()

    def test_fallback_returns_complete_from_run_log(self, client):
        import src.routes.assets as assets_module
        assets_module._ACQUISITION_STATE.pop(RUN_ID, None)
        run_log = {"steps": {"asset_acquisition": {"status": "complete", "error": None}}}
        with patch("src.routes.assets.R2Client") as mock_r2_cls:
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = run_log
            resp = client.get(f"/runs/{RUN_ID}/assets/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "complete"
