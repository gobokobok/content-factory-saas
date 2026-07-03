"""Tests for P-UX1-S2: Settings stage backend — format_track/captions threading,
music upload endpoint, and the async music-library fallback copy.

Covers:
- StoryboardWorkerRequest.format_track flows into the worker's state.inputs
- RenderWorkerRequest.captions flows into the worker's state.inputs
- _build_render_script: captions=False forces subtitles="none"
- POST /studio/runs/{run_id}/music — success, invalid MIME, oversized
- _copy_music_to_run — has-music skip, library-empty warning, happy-path copy
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.interfaces.api import get_artifact_storage, get_platform_settings
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


# ── format_track threading into the storyboard endpoint ──────────────────────


@pytest.mark.asyncio
async def test_storyboard_endpoint_forwards_format_track():
    """StoryboardWorkerRequest.format_track reaches build_storyboard_worker via state.inputs."""
    from cf_platform.core.artifact_manager import InMemoryArtifactStorage
    from cf_platform.interfaces.api import StoryboardWorkerRequest, storyboard_worker_endpoint

    storage = InMemoryArtifactStorage()
    settings = MagicMock(ANTHROPIC_API_KEY="sk-ant-fake")
    body = StoryboardWorkerRequest(run_id="run1", script="A short script.", format_track="landscape")

    from pydantic import BaseModel

    captured_states = []

    class _FakeArtifact(BaseModel):
        scene_count: int = 1
        prompt_version: str = "v0.15"

    async def _fake_worker(state):
        captured_states.append(state)
        from cf_platform.core.schemas import WorkerOutput
        return WorkerOutput(artifact=_FakeArtifact())

    with patch("cf_platform.interfaces.api.build_storyboard_worker", return_value=_fake_worker), \
         patch("cf_platform.interfaces.api.VerifiedStoryboardArtifact", _FakeArtifact), \
         patch("cf_platform.interfaces.api._latest_artifact_key", new_callable=AsyncMock, return_value=None):
        await storyboard_worker_endpoint(body, storage=storage, settings=settings)

    assert captured_states[0].inputs["format_track"] == "landscape"


def test_storyboard_worker_request_defaults_portrait():
    from cf_platform.interfaces.api import StoryboardWorkerRequest

    body = StoryboardWorkerRequest(run_id="run1", script="text")
    assert body.format_track == "portrait"


# ── captions threading into the render endpoint ───────────────────────────────


def test_render_worker_request_captions_default_true():
    from cf_platform.interfaces.api import RenderWorkerRequest

    body = RenderWorkerRequest(run_id="run1")
    assert body.captions is True


@pytest.mark.asyncio
async def test_render_endpoint_forwards_captions_false():
    """RenderWorkerRequest.captions=False reaches the worker via state.inputs."""
    from cf_platform.core.artifact_manager import InMemoryArtifactStorage
    from cf_platform.interfaces.api import RenderWorkerRequest, render_worker_endpoint
    from fastapi import BackgroundTasks

    storage = InMemoryArtifactStorage()
    await storage.put_json(
        "users/operator/runs/run1/storyboard/verified_storyboard@v1.json", {"storyboard": {}}
    )
    await storage.put_json(
        "users/operator/runs/run1/acquisition/asset_manifest@v1.json", {"manifest": {}}
    )
    settings = MagicMock(
        COLOR_GRADE_PRESET="neutral", BLUR_FILL_ENABLED=True, FFMPEG_TIMEOUT_SECONDS=1800
    )
    body = RenderWorkerRequest(run_id="run1", format_track="portrait", captions=False)
    background_tasks = BackgroundTasks()

    with patch("cf_platform.interfaces.api.build_render_worker", return_value=AsyncMock()):
        await render_worker_endpoint(body, background_tasks, storage=storage, settings=settings)

    # The background task was scheduled with a StageState carrying captions=False.
    assert background_tasks.tasks
    scheduled_state = background_tasks.tasks[0].kwargs.get("state") or background_tasks.tasks[0].args[2]
    assert scheduled_state.inputs["captions"] is False


def test_build_render_script_captions_false_forces_no_subtitles():
    """captions=False overrides VideoSettings default and disables burned-in subtitles."""
    from cf_platform.workers.render_worker import _build_render_script
    from src.models import AssetManifest, ManifestEntry, Storyboard, StoryboardGlobal, StoryboardScene, StoryboardSummary

    scene = StoryboardScene(
        scene="1", clip_type="still_with_motion", duration_s=3.0,
        voiceover_line="Test line.", segment_type="B-roll",
        primary_stk="a", context_stk="b", concept_stk="c",
        sfx="silence", sfx_timing="on cut",
    )
    sb = Storyboard(**{
        "global": StoryboardGlobal(subtitle_style="TikTok", bg_music="upbeat", visual_style="Documentary"),
        "scenes": [scene],
        "summary": StoryboardSummary(total_scenes=1, total_duration_s=3.0, rhythm="SM"),
    })
    mf = AssetManifest(run_id="run-cap", entries=[
        ManifestEntry(scene_id="1", clip_type="still_with_motion", segment_type="B-roll",
                      file_key="runs/run-cap/images/1.jpg", source="pexels", qa_passed=True, fallback_used=False)
    ])

    script_captions_on = _build_render_script("run-cap", sb, mf, None, "neutral", True, "portrait", True)
    script_captions_off = _build_render_script("run-cap", sb, mf, None, "neutral", True, "portrait", False)

    assert "ass=$WORK/voiceover_captions.ass" in script_captions_on
    assert "ass=$WORK/voiceover_captions.ass" not in script_captions_off


# ── Music upload endpoint ─────────────────────────────────────────────────────


class TestMusicUploadEndpoint:
    """POST /studio/runs/{run_id}/music"""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock()
        storage.put_bytes = AsyncMock(return_value=None)
        return storage

    @pytest.fixture
    def client(self, mock_storage):
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)

    def test_upload_mp3_success(self, client, mock_storage):
        r = client.post(
            "/platform/studio/runs/run1/music",
            files={"file": ("track.mp3", b"fake mp3 bytes", "audio/mpeg")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["file_key"] == "runs/run1/music/track.mp3"
        mock_storage.put_bytes.assert_awaited_once()

    def test_upload_invalid_mime_returns_422(self, client):
        r = client.post(
            "/platform/studio/runs/run1/music",
            files={"file": ("track.ogg", b"data", "audio/ogg")},
        )
        assert r.status_code == 422
        assert "Unsupported" in r.json()["detail"]

    def test_upload_oversized_returns_422(self, client):
        big_data = b"x" * (51 * 1024 * 1024)
        r = client.post(
            "/platform/studio/runs/run1/music",
            files={"file": ("big.mp3", big_data, "audio/mpeg")},
        )
        assert r.status_code == 422
        assert "large" in r.json()["detail"].lower()

    def test_second_upload_same_format_overwrites_key(self, client, mock_storage):
        r1 = client.post(
            "/platform/studio/runs/run1/music",
            files={"file": ("first.mp3", b"one", "audio/mpeg")},
        )
        r2 = client.post(
            "/platform/studio/runs/run1/music",
            files={"file": ("second.mp3", b"two", "audio/mpeg")},
        )
        assert r1.json()["file_key"] == r2.json()["file_key"]


# ── _copy_music_to_run (async fallback) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_copy_music_skips_when_run_already_has_music():
    from cf_platform.workers.render_worker import _copy_music_to_run

    storage = MagicMock()
    storage.list_keys = AsyncMock(return_value=["runs/run1/music/track.mp3"])
    storage.get_bytes = AsyncMock()
    storage.put_bytes = AsyncMock()

    await _copy_music_to_run("run1", storage)

    storage.get_bytes.assert_not_called()
    storage.put_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_copy_music_warns_when_library_empty():
    from cf_platform.workers.render_worker import _copy_music_to_run

    async def _list_keys(prefix):
        return []

    storage = MagicMock()
    storage.list_keys = AsyncMock(side_effect=_list_keys)
    storage.get_bytes = AsyncMock()
    storage.put_bytes = AsyncMock()

    await _copy_music_to_run("run1", storage)

    storage.get_bytes.assert_not_called()
    storage.put_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_copy_music_happy_path_copies_first_eligible_track():
    from cf_platform.workers.render_worker import _copy_music_to_run

    async def _list_keys(prefix):
        if prefix == "runs/run1/music/":
            return []
        return ["music-library/readme.txt", "music-library/ambient-1.mp3"]

    storage = MagicMock()
    storage.list_keys = AsyncMock(side_effect=_list_keys)
    storage.get_bytes = AsyncMock(return_value=b"music bytes")
    storage.put_bytes = AsyncMock()

    await _copy_music_to_run("run1", storage)

    storage.get_bytes.assert_awaited_once_with("music-library/ambient-1.mp3")
    storage.put_bytes.assert_awaited_once_with(
        "runs/run1/music/ambient-1.mp3", b"music bytes", content_type="audio/mpeg"
    )
