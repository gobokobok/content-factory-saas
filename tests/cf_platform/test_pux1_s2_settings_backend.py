"""Tests for P-UX1-S2: Settings stage backend — format_track/captions threading,
music upload endpoint, and the async music-library fallback copy.

Covers:
- StoryboardWorkerRequest.format_track flows into the worker's state.inputs
- RenderWorkerRequest.captions flows into the worker's state.inputs
- _build_render_script: captions=False forces subtitles="none"
- POST /studio/runs/{run_id}/music — success, invalid MIME, oversized
- _copy_music_to_run — has-music skip, library-empty warning, happy-path copy
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.interfaces.api import get_artifact_storage
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
    """StoryboardWorkerRequest.format_track reaches build_storyboard_worker via state.inputs.

    The endpoint is async (202 + background task) — the queued BackgroundTasks
    must be executed for the worker to run.
    """
    from fastapi import BackgroundTasks

    from cf_platform.core.artifact_manager import InMemoryArtifactStorage
    from cf_platform.interfaces.api import StoryboardWorkerRequest, storyboard_worker_endpoint

    storage = InMemoryArtifactStorage()
    settings = MagicMock(ANTHROPIC_API_KEY="sk-ant-fake")
    body = StoryboardWorkerRequest(run_id="run1", script="A short script.", format_track="landscape")

    from pydantic import BaseModel

    captured_states = []

    class _FakeArtifact(BaseModel):
        scene_count: int = 1
        prompt_version: str = "v0.17"

    async def _fake_worker(state):
        captured_states.append(state)
        from cf_platform.core.schemas import WorkerOutput
        return WorkerOutput(artifact=_FakeArtifact())

    background_tasks = BackgroundTasks()
    with patch("cf_platform.interfaces.routes.workers.build_storyboard_worker", return_value=_fake_worker), \
         patch("cf_platform.interfaces.routes.workers.VerifiedStoryboardArtifact", _FakeArtifact), \
         patch("cf_platform.interfaces.routes.workers._latest_artifact_key", new_callable=AsyncMock, return_value=None):
        response = await storyboard_worker_endpoint(
            body, background_tasks, storage=storage, settings=settings
        )
        await background_tasks()  # execute the queued background task

    assert response.status == "accepted"
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
    from fastapi import BackgroundTasks

    from cf_platform.core.artifact_manager import InMemoryArtifactStorage
    from cf_platform.interfaces.api import RenderWorkerRequest, render_worker_endpoint

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

    with patch("cf_platform.interfaces.routes.workers.build_render_worker", return_value=AsyncMock()):
        await render_worker_endpoint(body, background_tasks, storage=storage, settings=settings)

    # The background task was scheduled with a StageState carrying captions=False.
    assert background_tasks.tasks
    scheduled_state = background_tasks.tasks[0].kwargs.get("state") or background_tasks.tasks[0].args[2]
    assert scheduled_state.inputs["captions"] is False


def test_build_render_script_captions_false_forces_no_subtitles():
    """captions=False overrides VideoSettings default and disables burned-in subtitles."""
    from cf_platform.workers.render_worker import _build_render_script
    from src.models import (
        AssetManifest,
        ManifestEntry,
        Storyboard,
        StoryboardGlobal,
        StoryboardScene,
        StoryboardSummary,
    )

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


# ── D076: curated SFX library ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_copy_sfx_skips_when_run_already_has_it():
    from cf_platform.workers.render_worker import _copy_sfx_to_run

    storage = MagicMock()
    storage.list_keys = AsyncMock(return_value=["runs/run1/sfx/cash_register.mp3"])
    storage.get_bytes = AsyncMock()
    storage.put_bytes = AsyncMock()

    await _copy_sfx_to_run("run1", storage, "cash_register")

    storage.get_bytes.assert_not_called()
    storage.put_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_copy_sfx_warns_when_library_file_missing():
    from cf_platform.workers.render_worker import _copy_sfx_to_run

    storage = MagicMock()
    storage.list_keys = AsyncMock(return_value=[])
    storage.get_bytes = AsyncMock(side_effect=Exception("not found"))
    storage.put_bytes = AsyncMock()

    await _copy_sfx_to_run("run1", storage, "cash_register")

    storage.put_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_copy_sfx_happy_path_copies_file():
    from cf_platform.workers.render_worker import _copy_sfx_to_run

    storage = MagicMock()
    storage.list_keys = AsyncMock(return_value=[])
    storage.get_bytes = AsyncMock(return_value=b"sfx bytes")
    storage.put_bytes = AsyncMock()

    await _copy_sfx_to_run("run1", storage, "cash_register")

    storage.get_bytes.assert_awaited_once_with("sfx-library/cash_register.mp3")
    storage.put_bytes.assert_awaited_once_with(
        "runs/run1/sfx/cash_register.mp3", b"sfx bytes", content_type="audio/mpeg"
    )


@pytest.mark.asyncio
async def test_list_available_sfx_intersects_manifest_and_r2():
    from cf_platform.workers.render_worker import list_available_sfx

    storage = MagicMock()
    # Only 2 of the 8 manifest keys actually have a file in sfx-library/.
    storage.list_keys = AsyncMock(
        return_value=["sfx-library/cash_register.mp3", "sfx-library/whoosh.mp3", "sfx-library/readme.txt"]
    )

    result = await list_available_sfx(storage)

    assert {o["key"] for o in result} == {"cash_register", "whoosh"}
    assert {"key": "cash_register", "display_name": "Cash register"} in result


@pytest.mark.asyncio
async def test_copy_all_scene_sfx_to_run_copies_only_distinct_library_present_keys():
    from cf_platform.workers.render_worker import _copy_all_scene_sfx_to_run
    from src.models import (
        Storyboard,
        StoryboardGlobal,
        StoryboardScene,
        StoryboardSummary,
        VisualPrompts,
    )

    def _scene(scene_id: str, sfx: str) -> StoryboardScene:
        return StoryboardScene(
            scene=scene_id, clip_type="hard_cut", duration_s=3.0,
            voiceover_line="line", sfx=sfx,
            visual_prompts=VisualPrompts(primary_stk="a", fallback_stk="b", ai_generate=""),
        )

    storyboard = Storyboard(**{
        "global": StoryboardGlobal(subtitle_style="x", bg_music="none", visual_style="x"),
        "scenes": [
            _scene("1", "cash_register"),
            _scene("2", "cash_register"),  # duplicate — must only be copied once
            _scene("3", "silence"),  # skipped
            _scene("4", "unrecognised_free_text"),  # not in library — skipped
        ],
        "summary": StoryboardSummary(total_scenes=4, total_duration_s=12.0, rhythm="x"),
    })

    storage = MagicMock()
    storage.list_keys = AsyncMock(
        side_effect=lambda prefix: ["sfx-library/cash_register.mp3"] if prefix == "sfx-library/" else []
    )
    storage.get_bytes = AsyncMock(return_value=b"sfx bytes")
    storage.put_bytes = AsyncMock()

    await _copy_all_scene_sfx_to_run("run1", storyboard, storage)

    storage.put_bytes.assert_awaited_once_with(
        "runs/run1/sfx/cash_register.mp3", b"sfx bytes", content_type="audio/mpeg"
    )


@pytest.mark.asyncio
async def test_copy_all_scene_sfx_to_run_noop_when_every_scene_silent():
    from cf_platform.workers.render_worker import _copy_all_scene_sfx_to_run
    from src.models import (
        Storyboard,
        StoryboardGlobal,
        StoryboardScene,
        StoryboardSummary,
        VisualPrompts,
    )

    scene = StoryboardScene(
        scene="1", clip_type="hard_cut", duration_s=3.0, voiceover_line="line", sfx="silence",
        visual_prompts=VisualPrompts(primary_stk="a", fallback_stk="b", ai_generate=""),
    )
    storyboard = Storyboard(**{
        "global": StoryboardGlobal(subtitle_style="x", bg_music="none", visual_style="x"),
        "scenes": [scene],
        "summary": StoryboardSummary(total_scenes=1, total_duration_s=3.0, rhythm="x"),
    })

    storage = MagicMock()
    storage.list_keys = AsyncMock()
    storage.get_bytes = AsyncMock()

    await _copy_all_scene_sfx_to_run("run1", storyboard, storage)

    storage.list_keys.assert_not_called()  # short-circuits before any R2 call


class TestSfxLibraryEndpoint:
    """GET /studio/sfx-library"""

    @pytest.fixture
    def client(self):
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)

    def test_returns_only_present_keys(self, client):
        mock_storage = MagicMock()
        mock_storage.list_keys = AsyncMock(
            return_value=["sfx-library/checkmark.mp3", "sfx-library/error.mp3"]
        )
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage

        r = client.get("/platform/studio/sfx-library")

        assert r.status_code == 200
        assert {o["key"] for o in r.json()} == {"checkmark", "error"}

    def test_empty_library_returns_empty_list(self, client):
        mock_storage = MagicMock()
        mock_storage.list_keys = AsyncMock(return_value=[])
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage

        r = client.get("/platform/studio/sfx-library")

        assert r.status_code == 200
        assert r.json() == []


class TestScenePatchSfx:
    """PATCH /studio/runs/{run_id}/storyboard/scenes/{scene_id} — sfx field (D076)."""

    async def _seed_storyboard(self, storage) -> None:
        from cf_platform.core.artifact_manager import write_artifact
        from cf_platform.core.schemas import LineageEnvelope
        from cf_platform.interfaces.dependencies import PLATFORM_USER_ID
        from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
        from src.models import (
            Storyboard,
            StoryboardGlobal,
            StoryboardScene,
            StoryboardSummary,
            VisualPrompts,
        )

        scene = StoryboardScene(
            scene="1", clip_type="hard_cut", duration_s=3.0, voiceover_line="line", sfx="silence",
            visual_prompts=VisualPrompts(primary_stk="a", fallback_stk="b", ai_generate=""),
        )
        storyboard = Storyboard(**{
            "global": StoryboardGlobal(subtitle_style="x", bg_music="none", visual_style="x"),
            "scenes": [scene],
            "summary": StoryboardSummary(total_scenes=1, total_duration_s=3.0, rhythm="x"),
        })
        artifact = VerifiedStoryboardArtifact(
            prompt_version="test",
            scene_count=1,
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(),
        )
        await write_artifact(
            storage, artifact,
            name="verified_storyboard", stage="storyboard",
            run_id="run1", user_id=PLATFORM_USER_ID,
            lineage=LineageEnvelope(
                run_id="run1", worker="test", worker_version="1.0.0",
                prompt_version="test", model="none", created_at=datetime.now(),
            ),
        )

    @pytest.fixture
    def client(self):
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)

    def test_patching_sfx_lands_in_new_storyboard_version(self, client):
        import asyncio

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage

        storage = InMemoryArtifactStorage()
        asyncio.run(self._seed_storyboard(storage))
        app.dependency_overrides[get_artifact_storage] = lambda: storage

        r = client.patch(
            "/platform/studio/runs/run1/storyboard/scenes/1", json={"sfx": "cash_register"}
        )

        assert r.status_code == 200
        key = r.json()["artifact_key"]
        body = storage._objects[key]["body"]
        assert body["storyboard"]["scenes"][0]["sfx"] == "cash_register"

    def test_patching_empty_sfx_normalises_to_silence(self, client):
        import asyncio

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage

        storage = InMemoryArtifactStorage()
        asyncio.run(self._seed_storyboard(storage))
        app.dependency_overrides[get_artifact_storage] = lambda: storage

        r = client.patch("/platform/studio/runs/run1/storyboard/scenes/1", json={"sfx": ""})

        assert r.status_code == 200
        key = r.json()["artifact_key"]
        body = storage._objects[key]["body"]
        assert body["storyboard"]["scenes"][0]["sfx"] == "silence"
