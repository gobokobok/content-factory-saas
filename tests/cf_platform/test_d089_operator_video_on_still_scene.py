"""D089 — an operator-supplied video on a still-tier scene must render as video.

Regression cover for the PROD render failure where a scene whose storyboard said
`still_with_motion` (tier derived from a 3-6s duration) held an operator-uploaded
MP4.  `_render_scene` routed it to the still path, whose `-loop 1` is an
image2-demuxer option that FFmpeg 7 rejects on mov/mp4 — "Option loop not found",
"Error opening input files" — failing the entire render script with exit 1.

Two independent guards, tested separately because either alone leaves a hole:
  * `_render_scene` routes on file extension only, so a stale clip_type can never
    put `-loop 1` in front of a video again;
  * the upload endpoint re-derives asset_tier/clip_type/motion_effect from the
    uploaded media kind, so the storyboard (and the Studio table built from it)
    stops claiming a video scene is a still.
"""

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
from cf_platform.workers.storyboard_worker import rederive_scene_visual_contract
from src.config import Settings, get_settings
from src.ffmpeg_builder import _render_scene
from src.main import app
from src.models import ManifestEntry, StoryboardScene
from tests.cf_platform.test_p10_s2_asset_override import (
    _VALID_ENV,
    _artifact_stubs,
    _entry,
    _scene,
)


def _sb_scene(**kwargs) -> StoryboardScene:
    defaults = {
        "scene": "5",
        "clip_type": "still_with_motion",
        "duration_s": 4.0,
        "voiceover_line": "some words",
        "segment_type": "B-roll",
        "primary_stk": "housing",
        "motion_effect": "ken_burns",
        "asset_tier": "still_motion",
    }
    defaults.update(kwargs)
    return StoryboardScene.model_validate(defaults)


def _mf_entry(file_key: str, **kwargs) -> ManifestEntry:
    defaults = {
        "scene_id": "5",
        "clip_type": "still_with_motion",
        "segment_type": "B-roll",
        "primary_stk": "housing",
        "file_key": file_key,
        "source": "operator_upload",
        "status": "acquired",
    }
    defaults.update(kwargs)
    return ManifestEntry.model_validate(defaults)


class TestRenderSceneRoutesOnExtension:
    """_render_scene must trust the file on disk, not the storyboard's clip_type."""

    def test_operator_mp4_on_still_scene_takes_the_video_path(self):
        cmd = _render_scene(
            _sb_scene(),
            _mf_entry("runs/r1/video/scene_05_op.mp4"),
            run_id="r1",
            num=5,
        )
        # The exact failure mode from PROD: -loop 1 in front of an mp4.
        assert "-loop" not in cmd
        assert "zoompan" not in cmd
        assert "scene_05_op.mp4" in cmd

    @pytest.mark.parametrize("ext", [".mp4", ".webm", ".mov"])
    def test_no_video_extension_ever_reaches_the_loop_flag(self, ext):
        cmd = _render_scene(
            _sb_scene(motion_effect="zoom_in"),
            _mf_entry(f"runs/r1/video/scene_05_op{ext}"),
            run_id="r1",
            num=5,
        )
        assert "-loop" not in cmd

    def test_motion_effect_is_ignored_rather_than_honoured_for_video(self):
        """A stored effect on a video scene must not change the command at all."""
        entry = _mf_entry("runs/r1/video/scene_05_op.mp4")
        without = _render_scene(_sb_scene(motion_effect=None), entry, run_id="r1", num=5)
        for effect in ("ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right"):
            assert _render_scene(_sb_scene(motion_effect=effect), entry, run_id="r1", num=5) == without

    def test_image_on_hard_cut_scene_still_takes_the_still_path(self):
        """The pre-existing guard in the other direction must survive the inversion."""
        cmd = _render_scene(
            _sb_scene(clip_type="hard_cut", asset_tier="video", motion_effect=None),
            _mf_entry("runs/r1/images/5.jpeg", clip_type="hard_cut"),
            run_id="r1",
            num=5,
        )
        assert "-loop 1" in cmd

    def test_unknown_extension_is_treated_as_footage(self):
        """Better to hand FFmpeg an unadorned input than to add -loop 1 blindly."""
        cmd = _render_scene(
            _sb_scene(),
            _mf_entry("runs/r1/video/scene_05_op"),
            run_id="r1",
            num=5,
        )
        assert "-loop" not in cmd


class TestRederiveSceneVisualContract:
    """The asset the operator supplies overrules the duration-derived tier."""

    def test_video_clears_motion_and_switches_to_hard_cut(self):
        assert rederive_scene_visual_contract(2.0, True, "ken_burns") == ("video", "hard_cut", None)

    @pytest.mark.parametrize(
        "duration,expected_tier",
        [(1.0, "still"), (4.0, "still_motion"), (9.0, "still_motion")],
    )
    def test_image_gets_a_still_tier_even_when_duration_asks_for_video(self, duration, expected_tier):
        tier, clip_type, effect = rederive_scene_visual_contract(duration, False, None)
        assert (tier, clip_type) == (expected_tier, "still_with_motion")
        assert effect == "ken_burns"

    def test_an_operator_chosen_effect_survives_an_image_swap(self):
        assert rederive_scene_visual_contract(4.0, False, "pan_left")[2] == "pan_left"


class TestUploadRederivesStoryboard:
    """POST .../scenes/{n}/upload must leave the storyboard describing the real asset."""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock(spec=InMemoryArtifactStorage)
        storage.put_bytes = AsyncMock(return_value=None)
        storage.put_json = AsyncMock(return_value=None)
        storage.generate_presigned_url = AsyncMock(return_value="https://cdn.example.com/x")
        return storage

    @pytest.fixture
    def client(self, mock_storage):
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: mock_storage
        app.dependency_overrides[get_platform_settings] = lambda: MagicMock(PEXELS_API_KEY="k", PIXABAY_API_KEY="")
        app.dependency_overrides[get_trace_event_repository] = lambda: InMemoryTraceEventRepository()
        yield TestClient(app, raise_server_exceptions=True)
        for dep in (get_settings, get_artifact_storage, get_platform_settings, get_trace_event_repository):
            app.dependency_overrides.pop(dep, None)

    def test_mp4_upload_rewrites_the_scene_as_video(self, client):
        record = MagicMock()
        record.r2_key = "users/platform/runs/run1/storyboard/verified_storyboard@v2"
        key_stub, read_stub = _artifact_stubs([_scene("5")], [_entry("5")])
        write_mock = AsyncMock(return_value=record)

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", key_stub), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", read_stub), \
             patch("cf_platform.core.artifact_manager.write_artifact", write_mock):
            r = client.post(
                "/platform/studio/runs/run1/scenes/5/upload",
                files={"file": ("clip.mp4", b"video data", "video/mp4")},
            )

        assert r.status_code == 200
        sb_calls = [c for c in write_mock.call_args_list if c.kwargs.get("name") == "verified_storyboard"]
        assert len(sb_calls) == 1, "an mp4 on a still scene must write a new storyboard version"
        scenes = sb_calls[0].args[1].storyboard["scenes"]
        scene5 = next(s for s in scenes if s["scene"] == "5")
        assert scene5["asset_tier"] == "video"
        assert scene5["clip_type"] == "hard_cut"
        assert scene5["motion_effect"] is None

    def test_matching_image_upload_writes_no_storyboard_version(self, client):
        """An unchanged contract must not burn an artifact version."""
        record = MagicMock()
        record.r2_key = "users/platform/runs/run1/acquisition/asset_manifest@v2"
        key_stub, read_stub = _artifact_stubs(
            [_scene("5", motion_effect="ken_burns")], [_entry("5")]
        )
        write_mock = AsyncMock(return_value=record)

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", key_stub), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", read_stub), \
             patch("cf_platform.core.artifact_manager.write_artifact", write_mock):
            r = client.post(
                "/platform/studio/runs/run1/scenes/5/upload",
                files={"file": ("still.jpg", b"jpeg data", "image/jpeg")},
            )

        assert r.status_code == 200
        assert not [c for c in write_mock.call_args_list if c.kwargs.get("name") == "verified_storyboard"]

    def test_missing_storyboard_surfaces_as_404(self, client):
        """Not best-effort: a manifest pointing at an asset no storyboard describes is a fault."""
        async def latest_key(storage, run_id, stage, name):
            return None if stage == "storyboard" else "mf_key"

        async def read(storage, key):
            from tests.cf_platform.test_p10_s2_asset_override import _make_manifest_artifact
            return ("mf_key", _make_manifest_artifact([_entry("5")]))

        with patch("cf_platform.interfaces.routes.studio._latest_artifact_key", AsyncMock(side_effect=latest_key)), \
             patch("cf_platform.interfaces.routes.studio.read_artifact", AsyncMock(side_effect=read)), \
             patch("cf_platform.core.artifact_manager.write_artifact", AsyncMock(return_value=MagicMock())):
            r = client.post(
                "/platform/studio/runs/run1/scenes/5/upload",
                files={"file": ("clip.mp4", b"video data", "video/mp4")},
            )
        assert r.status_code == 404
