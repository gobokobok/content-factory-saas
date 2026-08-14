"""Tests for P10-S2: per-scene asset override endpoints + _acquire_single_scene extraction.

Covers:
- _acquire_single_scene is importable and routes correctly (Character/Event/B-roll)
- POST /studio/runs/{id}/scenes/{n}/reacquire — success, scene-not-found, empty query
- POST /studio/runs/{id}/scenes/{n}/upload — success, invalid MIME, oversized file, scene-not-found
- Existing AcquisitionWorker batch loop still passes (smoke via import)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.interfaces.api import (
    get_artifact_storage,
    get_platform_settings,
    get_trace_event_repository,
)
from src.config import Settings, get_settings
from src.main import app

_VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "fake-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels",
    "REPLICATE_API_TOKEN": "fake-replicate",
    "FREESOUND_API_KEY": "fake-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret",
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_storyboard_artifact(scenes: list[dict]) -> dict:
    """Return a minimal VerifiedStoryboardArtifact dict."""
    return {
        "scene_count": len(scenes),
        "prompt_version": "v0.13",
        "worker_version": "1.1.0",
        "storyboard": {
            "run_id": "test-run",
            "scenes": scenes,
            "global": {
                "subtitle_style": "default",
                "bg_music": "none",
                "visual_style": "documentary",
            },
            "summary": {
                "total_duration_s": 10.0,
                "total_scenes": len(scenes),
                "rhythm": "steady",
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _make_manifest_artifact(entries: list[dict]) -> dict:
    """Return a minimal AssetManifestArtifact dict."""
    return {
        "scene_count": len(entries),
        "acquired": sum(1 for e in entries if e.get("status") == "acquired"),
        "failed": sum(1 for e in entries if e.get("status") != "acquired"),
        "footage_summary": {},
        "manifest": {"run_id": "test-run", "entries": entries},
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _scene(scene_id: str, segment_type: str = "B-roll", **kwargs) -> dict:
    defaults = {
        "scene": scene_id,
        "voiceover_line": "some words",
        "duration_s": 4.0,
        "clip_type": "still_with_motion",
        "segment_type": segment_type,
        "primary_stk": "housing market",
        "context_stk": "real estate",
        "concept_stk": "property",
        "asset_tier": "still_motion",
        "on_screen_text": None,
        "on_screen_text_type": None,
        "person_name": None,
        "person_title": None,
        "historic": False,
        "render_options": None,
        "motion_effect": "ken_burns_in",
    }
    defaults.update(kwargs)
    return defaults


def _entry(scene_id: str, status: str = "acquired", **kwargs) -> dict:
    defaults = {
        "scene_id": scene_id,
        "clip_type": "still_with_motion",
        "segment_type": "B-roll",
        "primary_stk": "housing market",
        "context_stk": "real estate",
        "concept_stk": "property",
        "file_key": f"runs/test-run/images/scene_{scene_id}.jpg",
        "source": "pexels",
        "status": status,
        "qa_passed": True,
        "qa_resolution_ok": True,
        "qa_duration_ok": True,
        "qa_clip_score": None,
        "fallback_used": False,
        "duplicate_avoided": False,
        "asset_tier": "still_motion",
        "person_name": None,
        "person_title": None,
        "duration_s": 4.0,
        "historic": False,
        "attribution": None,
    }
    defaults.update(kwargs)
    return defaults


# ── _acquire_single_scene extraction tests ────────────────────────────────────


class TestAcquireSingleScene:
    """_acquire_single_scene is importable and dispatches by segment_type."""

    def test_importable(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene  # noqa: F401

    @pytest.mark.asyncio
    async def test_broll_dispatches_to_acquire_broll(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene
        from src.models import ManifestEntry

        entry = ManifestEntry(**{k: v for k, v in _entry("1").items() if k != "scene_id"}, scene_id="1")

        with patch("cf_platform.workers.acquisition_worker._acquire_broll", new_callable=AsyncMock, return_value=True) as mock_broll, \
             patch("cf_platform.workers.acquisition_worker._acquire_character", new_callable=AsyncMock) as mock_char, \
             patch("cf_platform.workers.acquisition_worker._acquire_event", new_callable=AsyncMock) as mock_event:
            await _acquire_single_scene(
                scene=MagicMock(),
                entry=entry,
                pexels=MagicMock(),
                pixabay=MagicMock(),
                wikimedia=MagicMock(),
                storage=MagicMock(),
                run_id="test-run",
            )
            mock_broll.assert_called_once()
            mock_char.assert_not_called()
            mock_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_character_dispatches_to_acquire_character(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene
        from src.models import ManifestEntry

        raw = _entry("2", segment_type="Character")
        raw["person_name"] = "Jerome Powell"
        entry = ManifestEntry(**{k: v for k, v in raw.items() if k != "scene_id"}, scene_id="2")

        with patch("cf_platform.workers.acquisition_worker._acquire_character", new_callable=AsyncMock, return_value=True) as mock_char, \
             patch("cf_platform.workers.acquisition_worker._acquire_broll", new_callable=AsyncMock) as mock_broll:
            await _acquire_single_scene(
                scene=MagicMock(),
                entry=entry,
                pexels=MagicMock(),
                pixabay=MagicMock(),
                wikimedia=MagicMock(),
                storage=MagicMock(),
                run_id="test-run",
            )
            mock_char.assert_called_once()
            mock_broll.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_dispatches_to_acquire_event(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene
        from src.models import ManifestEntry

        raw = _entry("3", segment_type="Event")
        entry = ManifestEntry(**{k: v for k, v in raw.items() if k != "scene_id"}, scene_id="3")

        with patch("cf_platform.workers.acquisition_worker._acquire_event", new_callable=AsyncMock, return_value=True) as mock_event, \
             patch("cf_platform.workers.acquisition_worker._acquire_broll", new_callable=AsyncMock) as mock_broll:
            await _acquire_single_scene(
                scene=MagicMock(),
                entry=entry,
                pexels=MagicMock(),
                pixabay=MagicMock(),
                wikimedia=MagicMock(),
                storage=MagicMock(),
                run_id="test-run",
            )
            mock_event.assert_called_once()
            mock_broll.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_acquisition_sets_status_failed(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene
        from src.models import ManifestEntry

        entry = ManifestEntry(**{k: v for k, v in _entry("4").items() if k != "scene_id"}, scene_id="4")
        entry.status = "pending"

        with patch("cf_platform.workers.acquisition_worker._acquire_broll", new_callable=AsyncMock, return_value=False):
            result = await _acquire_single_scene(
                scene=MagicMock(),
                entry=entry,
                pexels=MagicMock(),
                pixabay=MagicMock(),
                wikimedia=MagicMock(),
                storage=MagicMock(),
                run_id="test-run",
            )
            assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_returns_entry(self):
        from cf_platform.workers.acquisition_worker import _acquire_single_scene
        from src.models import ManifestEntry

        entry = ManifestEntry(**{k: v for k, v in _entry("5").items() if k != "scene_id"}, scene_id="5")

        with patch("cf_platform.workers.acquisition_worker._acquire_broll", new_callable=AsyncMock, return_value=True):
            result = await _acquire_single_scene(
                scene=MagicMock(),
                entry=entry,
                pexels=MagicMock(),
                pixabay=MagicMock(),
                wikimedia=MagicMock(),
                storage=MagicMock(),
                run_id="test-run",
            )
            assert result is entry


# ── Reacquire endpoint tests ──────────────────────────────────────────────────


class TestReacquireEndpoint:
    """POST /studio/runs/{run_id}/scenes/{scene_n}/reacquire"""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock(spec=InMemoryArtifactStorage)
        storage.list_keys = AsyncMock(return_value=[])
        storage.get_json = AsyncMock(return_value=None)
        storage.put_json = AsyncMock(return_value=None)
        storage.put_bytes = AsyncMock(return_value=None)
        storage.generate_presigned_url = AsyncMock(return_value="https://cdn.example.com/scene1.jpg")
        return storage

    @pytest.fixture
    def client(self, mock_storage):
        trace_repo = InMemoryTraceEventRepository()
        platform_settings = MagicMock()
        platform_settings.PEXELS_API_KEY = "fake-pexels"
        platform_settings.PIXABAY_API_KEY = ""
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        app.dependency_overrides[get_platform_settings] = lambda: platform_settings
        app.dependency_overrides[get_trace_event_repository] = lambda: trace_repo
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)
        app.dependency_overrides.pop(get_platform_settings, None)
        app.dependency_overrides.pop(get_trace_event_repository, None)

    def test_reacquire_success(self, client, mock_storage):
        record = MagicMock()
        record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock) as mock_latest, \
             patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock) as mock_read, \
             patch("cf_platform.core.artifact_manager.write_artifact", new_callable=AsyncMock, return_value=record), \
             patch("cf_platform.workers.acquisition_worker._acquire_single_scene", new_callable=AsyncMock) as mock_acq:

            mock_latest.side_effect = [
                "users/platform/runs/run1/storyboard/verified_storyboard@v1",
                "users/platform/runs/run1/acquisition/asset_manifest@v1",
            ]
            sb_data = _make_storyboard_artifact([_scene("1")])
            mf_data = _make_manifest_artifact([_entry("1")])
            mock_read.side_effect = [
                ("sb_key", sb_data),
                ("mf_key", mf_data),
            ]

            async def acq_side_effect(scene, entry, *args, **kwargs):
                entry.status = "acquired"
                entry.file_key = "runs/run1/images/scene_01_new.jpg"
                entry.source = "pixabay"
                return entry

            mock_acq.side_effect = acq_side_effect

            r = client.post(
                "/platform/studio/runs/run1/scenes/1/reacquire",
                json={"query": "neurons synapse"},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["scene_n"] == "1"
            assert data["source"] == "pixabay"

    def test_reacquire_empty_query_returns_422(self, client):
        r = client.post("/platform/studio/runs/run1/scenes/1/reacquire", json={"query": "  "})
        assert r.status_code == 422

    def test_reacquire_scene_not_found_returns_404(self, client):
        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value="sb_key"), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock, return_value=("sb_key", _make_storyboard_artifact([_scene("2")]))):
            r = client.post("/platform/studio/runs/run1/scenes/99/reacquire", json={"query": "query"})
            assert r.status_code == 404

    def test_reacquire_no_storyboard_returns_404(self, client):
        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value=None):
            r = client.post("/platform/studio/runs/run1/scenes/1/reacquire", json={"query": "query"})
            assert r.status_code == 404

    def test_reacquire_survives_trace_event_failure(self, mock_storage):
        """Regression: a trace_events.record() failure (e.g. Postgres FK violation because
        Studio run_ids are never inserted into `runs`) must not turn an already-successful
        manifest update into a 500 for the operator.
        """
        failing_trace_repo = MagicMock()
        failing_trace_repo.record = AsyncMock(side_effect=RuntimeError("FK violation on trace_events.run_id"))
        platform_settings = MagicMock()
        platform_settings.PEXELS_API_KEY = "fake-pexels"
        platform_settings.PIXABAY_API_KEY = ""
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        app.dependency_overrides[get_platform_settings] = lambda: platform_settings
        app.dependency_overrides[get_trace_event_repository] = lambda: failing_trace_repo
        try:
            client = TestClient(app, raise_server_exceptions=True)
            record = MagicMock()
            record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"

            with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock) as mock_latest, \
                 patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock) as mock_read, \
                 patch("cf_platform.core.artifact_manager.write_artifact", new_callable=AsyncMock, return_value=record), \
                 patch("cf_platform.workers.acquisition_worker._acquire_single_scene", new_callable=AsyncMock) as mock_acq:

                mock_latest.side_effect = [
                    "users/platform/runs/run1/storyboard/verified_storyboard@v1",
                    "users/platform/runs/run1/acquisition/asset_manifest@v1",
                ]
                mock_read.side_effect = [
                    ("sb_key", _make_storyboard_artifact([_scene("1")])),
                    ("mf_key", _make_manifest_artifact([_entry("1")])),
                ]

                async def acq_side_effect(scene, entry, *args, **kwargs):
                    entry.status = "acquired"
                    entry.file_key = "runs/run1/images/scene_01_new.jpg"
                    entry.source = "pixabay"
                    return entry

                mock_acq.side_effect = acq_side_effect

                r = client.post(
                    "/platform/studio/runs/run1/scenes/1/reacquire",
                    json={"query": "neurons synapse"},
                )
                assert r.status_code == 200
                assert r.json()["source"] == "pixabay"
                failing_trace_repo.record.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_settings, None)
            app.dependency_overrides.pop(get_artifact_storage, None)
            app.dependency_overrides.pop(get_platform_settings, None)
            app.dependency_overrides.pop(get_trace_event_repository, None)


# ── Upload endpoint tests ─────────────────────────────────────────────────────


class TestUploadEndpoint:
    """POST /studio/runs/{run_id}/scenes/{scene_n}/upload"""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock(spec=InMemoryArtifactStorage)
        storage.put_bytes = AsyncMock(return_value=None)
        storage.put_json = AsyncMock(return_value=None)
        storage.generate_presigned_url = AsyncMock(return_value="https://cdn.example.com/scene1_op.jpg")
        return storage

    @pytest.fixture
    def client(self, mock_storage):
        trace_repo = InMemoryTraceEventRepository()
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        app.dependency_overrides[get_platform_settings] = lambda: MagicMock(PEXELS_API_KEY="k", PIXABAY_API_KEY="")
        app.dependency_overrides[get_trace_event_repository] = lambda: trace_repo
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)
        app.dependency_overrides.pop(get_platform_settings, None)
        app.dependency_overrides.pop(get_trace_event_repository, None)

    def test_upload_success_jpeg(self, client, mock_storage):
        record = MagicMock()
        record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value="mf_key"), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock, return_value=("mf_key", _make_manifest_artifact([_entry("1")]))), \
             patch("cf_platform.core.artifact_manager.write_artifact", new_callable=AsyncMock, return_value=record):

            r = client.post(
                "/platform/studio/runs/run1/scenes/1/upload",
                files={"file": ("test.jpg", b"fake jpeg data", "image/jpeg")},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["scene_n"] == "1"
            assert data["file_key"].endswith(".jpg")
            assert "preview_url" in data

    def test_upload_invalid_mime_returns_422(self, client):
        r = client.post(
            "/platform/studio/runs/run1/scenes/1/upload",
            files={"file": ("test.gif", b"GIF89a", "image/gif")},
        )
        assert r.status_code == 422
        assert "Unsupported" in r.json()["detail"]

    def test_upload_oversized_returns_422(self, client):
        big_data = b"x" * (201 * 1024 * 1024)
        r = client.post(
            "/platform/studio/runs/run1/scenes/1/upload",
            files={"file": ("big.jpg", big_data, "image/jpeg")},
        )
        assert r.status_code == 422
        assert "large" in r.json()["detail"].lower()

    def test_upload_scene_not_in_manifest_returns_404(self, client):
        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value="mf_key"), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock, return_value=("mf_key", _make_manifest_artifact([_entry("1")]))):
            r = client.post(
                "/platform/studio/runs/run1/scenes/99/upload",
                files={"file": ("test.jpg", b"data", "image/jpeg")},
            )
            assert r.status_code == 404

    def test_upload_no_manifest_returns_404(self, client):
        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value=None):
            r = client.post(
                "/platform/studio/runs/run1/scenes/1/upload",
                files={"file": ("test.jpg", b"data", "image/jpeg")},
            )
            assert r.status_code == 404

    def test_upload_survives_trace_event_failure(self, mock_storage):
        """Regression: a trace_events.record() failure (e.g. Postgres FK violation because
        Studio run_ids are never inserted into `runs`) must not turn an already-successful
        upload + manifest update into a 500 for the operator.
        """
        failing_trace_repo = MagicMock()
        failing_trace_repo.record = AsyncMock(side_effect=RuntimeError("FK violation on trace_events.run_id"))
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        app.dependency_overrides[get_platform_settings] = lambda: MagicMock(PEXELS_API_KEY="k", PIXABAY_API_KEY="")
        app.dependency_overrides[get_trace_event_repository] = lambda: failing_trace_repo
        try:
            client = TestClient(app, raise_server_exceptions=True)
            record = MagicMock()
            record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"

            with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value="mf_key"), \
                 patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock, return_value=("mf_key", _make_manifest_artifact([_entry("1")]))), \
                 patch("cf_platform.core.artifact_manager.write_artifact", new_callable=AsyncMock, return_value=record):

                r = client.post(
                    "/platform/studio/runs/run1/scenes/1/upload",
                    files={"file": ("clip.mp4", b"fake video data", "video/mp4")},
                )
                assert r.status_code == 200
                data = r.json()
                assert data["file_key"].endswith(".mp4")
                failing_trace_repo.record.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_settings, None)
            app.dependency_overrides.pop(get_artifact_storage, None)
            app.dependency_overrides.pop(get_platform_settings, None)
            app.dependency_overrides.pop(get_trace_event_repository, None)

    def test_upload_mp4_uses_video_folder(self, client, mock_storage):
        record = MagicMock()
        record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"
        captured_key = []

        async def capture_put(key, data, content_type):
            captured_key.append(key)

        mock_storage.put_bytes.side_effect = capture_put

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", new_callable=AsyncMock, return_value="mf_key"), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", new_callable=AsyncMock, return_value=("mf_key", _make_manifest_artifact([_entry("3")]))), \
             patch("cf_platform.core.artifact_manager.write_artifact", new_callable=AsyncMock, return_value=record):

            r = client.post(
                "/platform/studio/runs/run1/scenes/3/upload",
                files={"file": ("clip.mp4", b"video data", "video/mp4")},
            )
            assert r.status_code == 200
            assert captured_key and "/video/" in captured_key[0]
            assert captured_key[0].endswith(".mp4")
