"""Tests for P-UX2-S3: motion effect vocabulary + per-scene Motion patching (D081).

Covers:
- src.models.normalize_motion_effect — aliases, unknown values, clip_type defaults
- PATCH /studio/runs/{id}/storyboard/scenes/{n} — motion_effect accepted, validated
- _PATCHABLE_FIELDS actually includes motion_effect (the pre-D081 gap)
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from cf_platform.interfaces.api import get_artifact_storage
from src.config import Settings, get_settings
from src.main import app
from src.models import MOTION_EFFECTS, normalize_motion_effect

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


# ── normalize_motion_effect ───────────────────────────────────────────────────


class TestNormalizeMotionEffect:
    def test_vocabulary_members_pass_through(self) -> None:
        for effect in MOTION_EFFECTS:
            assert normalize_motion_effect(effect) == effect

    def test_legacy_ken_burns_names_collapse(self) -> None:
        assert normalize_motion_effect("ken_burns_in") == "ken_burns"
        assert normalize_motion_effect("ken_burns_out") == "ken_burns"

    def test_legacy_scale_preserves_observed_behaviour(self) -> None:
        # "scale" NAMED a static hold but RENDERED as the gentle push, because
        # _zoompan_filter short-circuited on clip_type before reading the field.
        # The alias preserves what was rendered, not what the name promised —
        # otherwise re-rendering an old run would freeze its short scenes.
        assert normalize_motion_effect("scale") == "ken_burns"

    def test_hyphens_and_case_are_normalised(self) -> None:
        assert normalize_motion_effect("Ken-Burns-In") == "ken_burns"
        assert normalize_motion_effect("  ZOOM_OUT  ") == "zoom_out"

    def test_empty_defaults_by_clip_type(self) -> None:
        # This is what keeps pre-D081 runs rendering identically: an unset
        # motion_effect on a still still means "the gentle centre push".
        assert normalize_motion_effect(None, "still_with_motion") == "ken_burns"
        assert normalize_motion_effect("", "still_with_motion") == "ken_burns"
        assert normalize_motion_effect(None, "hard_cut") == "static"
        assert normalize_motion_effect(None) == "static"

    def test_unknown_value_falls_back_rather_than_raising(self) -> None:
        # Stored storyboards are free-form strings; an unrecognised one must degrade,
        # not crash a render.
        assert normalize_motion_effect("spin_around", "still_with_motion") == "ken_burns"
        assert normalize_motion_effect("spin_around", "animated") == "static"

    def test_always_returns_a_vocabulary_member(self) -> None:
        for value in (None, "", "scale", "ken_burns_in", "nonsense", "PAN-LEFT"):
            assert normalize_motion_effect(value, "still_with_motion") in MOTION_EFFECTS


# ── PATCH endpoint ────────────────────────────────────────────────────────────


class TestScenePatchMotionEffect:
    """PATCH /studio/runs/{run_id}/storyboard/scenes/{scene_id} — motion_effect (D081)."""

    async def _seed_storyboard(self, storage) -> None:
        """Write a one-scene verified_storyboard artifact for run1."""
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
            scene="1",
            clip_type="still_with_motion",
            duration_s=3.0,
            voiceover_line="line",
            motion_effect="ken_burns",
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

    def _seeded_storage(self):
        """Return an InMemoryArtifactStorage already holding run1's storyboard."""
        import asyncio

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage

        storage = InMemoryArtifactStorage()
        asyncio.run(self._seed_storyboard(storage))
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        return storage

    def test_patching_motion_effect_lands_in_new_version(self, client):
        storage = self._seeded_storage()

        r = client.patch(
            "/platform/studio/runs/run1/storyboard/scenes/1", json={"motion_effect": "pan_right"}
        )

        assert r.status_code == 200
        key = r.json()["artifact_key"]
        body = storage._objects[key]["body"]
        assert body["storyboard"]["scenes"][0]["motion_effect"] == "pan_right"

    def test_every_vocabulary_member_is_accepted(self, client):
        for effect in MOTION_EFFECTS:
            storage = self._seeded_storage()
            r = client.patch(
                "/platform/studio/runs/run1/storyboard/scenes/1", json={"motion_effect": effect}
            )
            assert r.status_code == 200, effect
            body = storage._objects[r.json()["artifact_key"]]["body"]
            assert body["storyboard"]["scenes"][0]["motion_effect"] == effect

    def test_unknown_motion_effect_is_rejected(self, client):
        self._seeded_storage()

        r = client.patch(
            "/platform/studio/runs/run1/storyboard/scenes/1", json={"motion_effect": "spin_around"}
        )

        # 422 rather than a silent no-op: _PATCHABLE_FIELDS would otherwise drop it
        # and the operator would see the dropdown snap back with no explanation.
        assert r.status_code == 422
        assert "spin_around" in r.json()["detail"]

    def test_legacy_alias_is_rejected_at_the_boundary(self, client):
        # Aliases are tolerated when READING stored artifacts, but the UI must only
        # ever write canonical values.
        self._seeded_storage()
        r = client.patch(
            "/platform/studio/runs/run1/storyboard/scenes/1", json={"motion_effect": "ken_burns_in"}
        )
        assert r.status_code == 422

    def test_motion_effect_is_in_patchable_fields(self):
        # Regression guard for the pre-D081 gap: the endpoint accepted the field but
        # _apply_patches_and_render_options silently discarded it.
        import inspect

        from cf_platform.workers.storyboard_worker import _apply_patches_and_render_options

        assert '"motion_effect"' in inspect.getsource(_apply_patches_and_render_options)
