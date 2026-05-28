"""Tests for src/acquisition.py and src/routes/assets.py."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.acquisition import MIN_ACQUIRED_FOR_COMPLETE, acquire_scene, run_acquisition
from src.config import Settings, get_settings
from src.exceptions import PexelsError, ReplicateError, StorageError
from typing import List, Optional

from src.main import app
from src.models import (
    AssetManifest,
    ManifestEntry,
    PexelsAcquireResult,
    ReplicateAcquireResult,
)

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


def _entry(scene_id: str = "01", status: str = "pending", clip_type: str = "hard_cut") -> ManifestEntry:
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


def _pexels_result(scene_id: str = "01", key: str = "runs/r/video/01.mp4") -> PexelsAcquireResult:
    return PexelsAcquireResult(scene_id=scene_id, source="pexels", file_key=key)


def _replicate_result(scene_id: str = "01", key: str = "runs/r/images/01.webp") -> ReplicateAcquireResult:
    return ReplicateAcquireResult(scene_id=scene_id, file_key=key)


# ── Unit: acquire_scene ───────────────────────────────────────────────────────


class TestAcquireScene:
    def test_pexels_success_updates_entry_and_returns_true(self):
        entry = _entry()
        pexels, replicate, storage = MagicMock(), MagicMock(), MagicMock()
        pexels.acquire_for_entry.return_value = _pexels_result()

        assert acquire_scene(entry, RUN_ID, pexels, replicate, storage) is True
        assert entry.source == "pexels"
        assert entry.file_key == "runs/r/video/01.mp4"
        assert entry.status == "acquired"
        replicate.acquire_for_entry.assert_not_called()

    def test_pexels_none_falls_through_to_replicate(self):
        entry = _entry()
        pexels, replicate, storage = MagicMock(), MagicMock(), MagicMock()
        pexels.acquire_for_entry.return_value = None
        replicate.acquire_for_entry.return_value = _replicate_result()

        assert acquire_scene(entry, RUN_ID, pexels, replicate, storage) is True
        assert entry.source == "replicate"
        assert entry.status == "acquired"

    def test_pexels_error_falls_through_to_replicate(self):
        entry = _entry()
        pexels, replicate, storage = MagicMock(), MagicMock(), MagicMock()
        pexels.acquire_for_entry.side_effect = PexelsError("network error")
        replicate.acquire_for_entry.return_value = _replicate_result()

        assert acquire_scene(entry, RUN_ID, pexels, replicate, storage) is True
        assert entry.source == "replicate"

    def test_both_fail_marks_entry_failed_and_returns_false(self):
        entry = _entry()
        pexels, replicate, storage = MagicMock(), MagicMock(), MagicMock()
        pexels.acquire_for_entry.return_value = None
        replicate.acquire_for_entry.side_effect = ReplicateError("api down")

        assert acquire_scene(entry, RUN_ID, pexels, replicate, storage) is False
        assert entry.status == "failed"

    def test_pexels_error_and_replicate_error_marks_failed(self):
        entry = _entry()
        pexels, replicate, storage = MagicMock(), MagicMock(), MagicMock()
        pexels.acquire_for_entry.side_effect = PexelsError("timeout")
        replicate.acquire_for_entry.side_effect = ReplicateError("timeout")

        assert acquire_scene(entry, RUN_ID, pexels, replicate, storage) is False
        assert entry.status == "failed"


# ── Unit: run_acquisition ─────────────────────────────────────────────────────


class TestRunAcquisition:
    def _clients(self):
        return MagicMock(), MagicMock(), MagicMock()

    def test_all_pending_all_pexels(self):
        entries = [_entry("01"), _entry("02")]
        manifest = _manifest(entries)
        pexels, replicate, storage = self._clients()
        pexels.acquire_for_entry.side_effect = [
            _pexels_result("01", "runs/r/video/01.mp4"),
            _pexels_result("02", "runs/r/video/02.mp4"),
        ]

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        assert summary["acquired"] == 2
        assert summary["failed"] == 0
        assert summary["sources"] == {"pexels": 2}

    def test_skips_already_acquired_entries(self):
        pre = _entry("01", status="acquired")
        pre.source = "pexels"
        pre.file_key = "runs/r/video/01.mp4"
        pending = _entry("02")
        manifest = _manifest([pre, pending])
        pexels, replicate, storage = self._clients()
        pexels.acquire_for_entry.return_value = _pexels_result("02", "runs/r/video/02.mp4")

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        assert pexels.acquire_for_entry.call_count == 1
        assert summary["acquired"] == 2  # both entries are acquired
        assert summary["sources"] == {"pexels": 2}

    def test_all_pre_acquired_returns_full_count(self):
        """Idempotent call where all entries were already acquired."""
        entries = [_entry("01", status="acquired"), _entry("02", status="acquired")]
        entries[0].source = "pexels"
        entries[0].file_key = "k1"
        entries[1].source = "replicate"
        entries[1].file_key = "k2"
        manifest = _manifest(entries)
        pexels, replicate, storage = self._clients()

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        pexels.acquire_for_entry.assert_not_called()
        assert summary["acquired"] == 2
        assert summary["failed"] == 0
        assert summary["sources"] == {"pexels": 1, "replicate": 1}

    def test_mixed_pexels_and_replicate(self):
        entries = [_entry("01"), _entry("02", clip_type="still_with_motion")]
        manifest = _manifest(entries)
        pexels, replicate, storage = self._clients()
        pexels.acquire_for_entry.side_effect = [_pexels_result("01"), None]
        replicate.acquire_for_entry.return_value = _replicate_result("02")

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        assert summary["acquired"] == 2
        assert summary["sources"] == {"pexels": 1, "replicate": 1}

    def test_all_fail_returns_zero_acquired(self):
        entries = [_entry("01"), _entry("02")]
        manifest = _manifest(entries)
        pexels, replicate, storage = self._clients()
        pexels.acquire_for_entry.return_value = None
        replicate.acquire_for_entry.side_effect = ReplicateError("fail")

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        assert summary["acquired"] == 0
        assert summary["failed"] == 2
        assert summary["sources"] == {}

    def test_partial_acquisition(self):
        entries = [_entry("01"), _entry("02")]
        manifest = _manifest(entries)
        pexels, replicate, storage = self._clients()
        pexels.acquire_for_entry.side_effect = [_pexels_result("01"), None]
        replicate.acquire_for_entry.side_effect = ReplicateError("fail")

        summary = run_acquisition(RUN_ID, manifest, pexels, replicate, storage)

        assert summary["acquired"] == 1
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
    def test_200_all_acquired_returns_complete(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition") as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {"pexels": 1}}

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert body["acquired"] == 1
        assert body["failed"] == 0
        assert body["sources"] == {"pexels": 1}
        assert body["manifest_key"] == MANIFEST_KEY
        mock_storage.upload_json.assert_called_once()
        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID, "asset_acquisition", "complete", output_url=MANIFEST_KEY
        )

    def test_200_zero_acquired_returns_failed_status(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition") as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 0, "failed": 1, "sources": {}}

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID, "asset_acquisition", "failed", output_url=MANIFEST_KEY
        )

    def test_404_when_manifest_not_found(self, client):
        with patch("src.routes.assets.R2Client") as mock_r2_cls:
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.side_effect = StorageError("not found")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 404

    def test_500_unexpected_acquisition_error_marks_run_log_failed(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition") as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.side_effect = Exception("unexpected crash")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 500
        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID, "asset_acquisition", "failed", error="unexpected crash"
        )

    def test_500_manifest_write_failure_marks_run_log_failed(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.run_acquisition") as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {"pexels": 1}}
            mock_storage.upload_json.side_effect = StorageError("write failed")

            resp = client.post(f"/runs/{RUN_ID}/assets")

        assert resp.status_code == 500
        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID, "asset_acquisition", "failed", error="write failed"
        )

    def test_clients_instantiated_with_correct_settings(self, client):
        with (
            patch("src.routes.assets.R2Client") as mock_r2_cls,
            patch("src.routes.assets.PexelsClient") as mock_pexels_cls,
            patch("src.routes.assets.ReplicateClient") as mock_rep_cls,
            patch("src.routes.assets.run_acquisition") as mock_acquire,
        ):
            mock_storage = MagicMock()
            mock_r2_cls.return_value = mock_storage
            mock_storage.get_json.return_value = SAMPLE_MANIFEST_DATA
            mock_acquire.return_value = {"acquired": 1, "failed": 0, "sources": {}}

            client.post(f"/runs/{RUN_ID}/assets")

        mock_pexels_cls.assert_called_once_with(api_key="pex", per_page=5)
        mock_rep_cls.assert_called_once_with(
            api_token="rep",
            model="black-forest-labs/flux-schnell",
            poll_interval_seconds=3,
            max_poll_attempts=60,
        )
