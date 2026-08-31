"""Tests for P-UX2-S4: narration pace + emotional register (D083).

Covers:
- _build_tts_input composes style clause + wpm target + the D073 pause instruction
- _estimate_duration tracks the selected pace
- VideoSettings carries the two new fields
- The voice worker reads them out of state.inputs and defaults when absent
"""

import pytest

from cf_platform.workers.voice_production import (
    _DEFAULT_PACE,
    _DEFAULT_STYLE,
    _PACE_WPM,
    _PAUSE_INSTRUCTION,
    _STYLE_CLAUSE,
    _build_tts_input,
    _estimate_duration,
)

_SCRIPT = "Housing costs rose. Wages did not."
_PACES = list(_PACE_WPM)
_STYLES = list(_STYLE_CLAUSE)


# ── _build_tts_input ──────────────────────────────────────────────────────────


class TestBuildTtsInput:
    @pytest.mark.parametrize("pace", _PACES)
    @pytest.mark.parametrize("style", _STYLES)
    def test_pause_instruction_survives_every_combination(self, pace: str, style: str) -> None:
        # D073's pause wording is load-bearing — it is what stopped Gemini running
        # sentences together. No pace/style combination may drop it.
        assert _PAUSE_INSTRUCTION in _build_tts_input(_SCRIPT, pace, style)

    @pytest.mark.parametrize("pace", _PACES)
    @pytest.mark.parametrize("style", _STYLES)
    def test_script_is_always_appended_last(self, pace: str, style: str) -> None:
        assert _build_tts_input(_SCRIPT, pace, style).endswith(_SCRIPT)

    @pytest.mark.parametrize("pace", _PACES)
    def test_wpm_target_matches_the_pace_table(self, pace: str) -> None:
        assert f"roughly {_PACE_WPM[pace]} words per minute" in _build_tts_input(
            _SCRIPT, pace, "educational"
        )

    @pytest.mark.parametrize("style", _STYLES)
    def test_style_clause_leads(self, style: str) -> None:
        assert _build_tts_input(_SCRIPT, "normal", style).startswith(_STYLE_CLAUSE[style])

    def test_paces_produce_distinct_instructions(self) -> None:
        rendered = {_build_tts_input(_SCRIPT, p, "educational") for p in _PACES}
        assert len(rendered) == len(_PACES)

    def test_styles_produce_distinct_instructions(self) -> None:
        rendered = {_build_tts_input(_SCRIPT, "normal", s) for s in _STYLES}
        assert len(rendered) == len(_STYLES)

    def test_unknown_values_fall_back_to_defaults(self) -> None:
        # A stale settings.json must never break voice generation (D048).
        assert _build_tts_input(_SCRIPT, "warp_speed", "sarcastic") == _build_tts_input(
            _SCRIPT, _DEFAULT_PACE, _DEFAULT_STYLE
        )

    def test_instruction_applied_regardless_of_aspect_ratio(self) -> None:
        # Pre-D083 only 9:16 received an instruction; aspect ratio is no longer a
        # parameter at all, so landscape gets one too.
        import inspect

        assert "aspect_ratio" not in inspect.signature(_build_tts_input).parameters


# ── _estimate_duration ────────────────────────────────────────────────────────


class TestEstimateDuration:
    def test_slower_pace_gives_longer_estimate(self) -> None:
        script = " ".join(["word"] * 300)
        assert (
            _estimate_duration(script, "slow")
            > _estimate_duration(script, "normal")
            > _estimate_duration(script, "fast")
        )

    def test_proportional_to_word_count(self) -> None:
        assert _estimate_duration(" ".join(["w"] * 100)) > _estimate_duration("w w w")

    def test_minimum_one_second(self) -> None:
        assert _estimate_duration("") >= 1.0
        assert _estimate_duration("hello") >= 1.0

    def test_matches_the_wpm_given_to_the_tts(self) -> None:
        script = " ".join(["word"] * 160)
        assert _estimate_duration(script, "normal") == pytest.approx(60.0, rel=0.01)

    def test_unknown_pace_falls_back(self) -> None:
        assert _estimate_duration(_SCRIPT, "warp_speed") == _estimate_duration(
            _SCRIPT, _DEFAULT_PACE
        )


# ── Settings plumbing ─────────────────────────────────────────────────────────


class TestNarrationSettings:
    def test_video_settings_defaults(self) -> None:
        from src.models import VideoSettings

        s = VideoSettings()
        assert s.narration_pace == _DEFAULT_PACE
        assert s.narration_style == _DEFAULT_STYLE

    def test_video_settings_accepts_all_vocabulary(self) -> None:
        from src.models import VideoSettings

        for pace in _PACES:
            assert VideoSettings(narration_pace=pace).narration_pace == pace
        for style in _STYLES:
            assert VideoSettings(narration_style=style).narration_style == style

    def test_video_settings_rejects_unknown_values(self) -> None:
        from pydantic import ValidationError

        from src.models import VideoSettings

        with pytest.raises(ValidationError):
            VideoSettings(narration_pace="warp_speed")
        with pytest.raises(ValidationError):
            VideoSettings(narration_style="sarcastic")

    def test_fast_matches_the_pre_d083_shorts_rate(self) -> None:
        # 9:16 previously ran at ~170-175 wpm (D073); "fast" is how the operator
        # reproduces that pace now that the default is "normal".
        assert _PACE_WPM["fast"] == 172


# ── settings.json -> state.inputs (the only UI -> TTS channel) ────────────────


class TestVoiceEndpointReadsSettings:
    """POST /platform/workers/voice threads narration settings into StageState."""

    _ENV = {
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

    def _post(self, settings_json: dict | None):
        """POST to the voice endpoint and return the StageState the worker got."""
        import asyncio
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.interfaces.api import get_artifact_storage
        from src.config import Settings, get_settings
        from src.main import app

        storage = InMemoryArtifactStorage()
        if settings_json is not None:
            asyncio.run(storage.put_json("runs/run1/settings.json", settings_json))

        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(self._ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        captured: dict = {}

        async def _capture(run_id, job_id, state, worker, stg):
            captured["state"] = state

        try:
            with patch("cf_platform.interfaces.routes.workers._run_voice_background", _capture):
                client = TestClient(app, raise_server_exceptions=True)
                r = client.post(
                    "/platform/workers/voice", json={"run_id": "run1", "script": "hello world"}
                )
            assert r.status_code == 202
        finally:
            app.dependency_overrides.pop(get_settings, None)
            app.dependency_overrides.pop(get_artifact_storage, None)
        return captured["state"]

    def test_settings_reach_the_worker_state(self) -> None:
        state = self._post({"narration_pace": "slow", "narration_style": "emotional"})
        assert state.inputs["narration_pace"] == "slow"
        assert state.inputs["narration_style"] == "emotional"

    def test_missing_settings_blob_leaves_inputs_empty(self) -> None:
        # The worker then falls back to its own defaults rather than erroring.
        state = self._post(None)
        assert not state.inputs.get("narration_pace")
        assert not state.inputs.get("narration_style")


# ── settings.json round-trip (regression for the reset-clobber bug) ───────────


class TestSettingsRoundTrip:
    """POST then GET /runs/{id}/settings must preserve the D082/D083 fields.

    The operator hit this as "my dropdowns reset when I reload". The cause was in
    the front-end (resetSettingsPane fired saveRunSettings on every run load and
    POSTed the DEFAULTS, racing the GET meant to restore them), so this test would
    not have caught it. It guards the other half of the contract: that the fields
    survive the model -> R2 -> model trip at all, which is what makes the
    front-end fix observable.
    """

    _ENV = {
        "ENVIRONMENT": "dev",
        "R2_ACCOUNT_ID": "f",
        "R2_ACCESS_KEY_ID": "f",
        "R2_SECRET_ACCESS_KEY": "f",
        "R2_BUCKET_NAME": "b",
        "ANTHROPIC_API_KEY": "sk-ant-f",
        "PEXELS_API_KEY": "f",
        "REPLICATE_API_TOKEN": "f",
        "FREESOUND_API_KEY": "f",
        "OPERATOR_PASSWORD": "correct-horse-battery",
        "SESSION_SECRET_KEY": "s",
    }

    def _client(self, store: dict):
        """Return a logged-in TestClient whose settings routes use an in-memory R2."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from src.config import Settings, get_settings
        from src.exceptions import StorageError
        from src.main import app

        class FakeR2:
            def upload_json(self, key, obj):
                store[key] = dict(obj)

            def get_json(self, key):
                if key not in store:
                    raise StorageError("not found")
                return store[key]

        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(self._ENV)
        ctx = patch("src.routes.runs._make_r2_client", lambda s: FakeR2())
        ctx.start()
        client = TestClient(app)
        client.post("/auth/login", json={"password": "correct-horse-battery"})
        return client, ctx

    def test_non_default_settings_survive_the_round_trip(self) -> None:
        store: dict = {}
        client, ctx = self._client(store)
        try:
            body = {
                "aspect_ratio": "9:16",
                "visual_style": "Realistic",
                "subtitles": "TikTok",
                "subject": "",
                "caption_style": "punch",
                "narration_pace": "slow",
                "narration_style": "emotional",
            }
            assert client.post("/runs/run-x/settings", json=body).status_code == 200

            got = client.get("/runs/run-x/settings").json()["settings"]
            assert got["caption_style"] == "punch"
            assert got["narration_pace"] == "slow"
            assert got["narration_style"] == "emotional"

            # And they are actually written to the stored object, not just echoed.
            stored = store["runs/run-x/settings.json"]
            assert stored["narration_pace"] == "slow"
            assert stored["narration_style"] == "emotional"
            assert stored["caption_style"] == "punch"
        finally:
            ctx.stop()
            app_overrides = __import__("src.main", fromlist=["app"]).app.dependency_overrides
            app_overrides.clear()

    def test_absent_settings_fall_back_to_defaults(self) -> None:
        store: dict = {}
        client, ctx = self._client(store)
        try:
            got = client.get("/runs/never-saved/settings").json()["settings"]
            assert got["narration_pace"] == _DEFAULT_PACE
            assert got["narration_style"] == _DEFAULT_STYLE
            assert got["caption_style"] == "standard"
        finally:
            ctx.stop()
            __import__("src.main", fromlist=["app"]).app.dependency_overrides.clear()
