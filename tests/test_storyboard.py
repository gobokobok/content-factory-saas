"""Tests for storyboard generation — parser unit tests and route integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import StoryboardAPIError, StoryboardParseError
from src.main import app
from src.storyboard import (
    _parse_global,
    _parse_scene,
    _parse_storyboard_response,
    _parse_summary,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "PEXELS_API_KEY": "test-pexels",
    "REPLICATE_API_TOKEN": "test-replicate",
    "FREESOUND_API_KEY": "test-freesound",
}

SAMPLE_SCENE_BLOCK = """\
SCENE 1
clip_type: still_with_motion
duration_s: 2.0
voiceover_line: "The American dream is slipping away."
visual_prompts:
  PRIMARY: STK `family home suburban street daytime`
  FALLBACK: STK `american neighborhood houses`
  AI_GENERATE if no stock: `Aerial view of a quiet American suburban street at golden hour, cinematic`
motion_effect: zoom-in
on_screen_text: null
sfx: soft ambient neighborhood sounds
sfx_timing: on cut"""

SAMPLE_SCENE_BLOCK_HARD_CUT = """\
SCENE 3a
clip_type: hard_cut
duration_s: 0.5
voiceover_line: "Rising rents,"
visual_prompts:
  PRIMARY: STK `rent increase eviction notice`
  FALLBACK: STK `rent payment lease document`
  AI_GENERATE if no stock: `Close-up of an eviction notice, dramatic lighting, dark tones`
motion_effect: null
on_screen_text: Rising rents
sfx: paper rustling
sfx_timing: on cut"""

SAMPLE_GLOBAL_BLOCK = """\
GLOBAL
subtitle_style: Bold white with drop shadow, centered lower third, fade-in
bg_music: Tense ambient electronic, 80 BPM, minor key, -18dB under VO
visual_style: Dark cinematic aesthetic, high contrast, 2.35:1 crop with vignette"""

SAMPLE_SUMMARY_BLOCK = """\
SUMMARY
Total scenes: 2
Total duration: 38.5s
Rhythm: SM / HC"""

SAMPLE_FULL_RESPONSE = f"""{SAMPLE_GLOBAL_BLOCK}

---

{SAMPLE_SCENE_BLOCK}

---

{SAMPLE_SCENE_BLOCK_HARD_CUT}

---

{SAMPLE_SUMMARY_BLOCK}"""


# ── Parser unit tests ─────────────────────────────────────────────────────────


class TestParseGlobal:
    def test_happy_path(self):
        result = _parse_global(SAMPLE_GLOBAL_BLOCK)
        assert result.subtitle_style == "Bold white with drop shadow, centered lower third, fade-in"
        assert "80 BPM" in result.bg_music
        assert "Dark cinematic" in result.visual_style

    def test_missing_field_raises(self):
        bad_block = "GLOBAL\nsubtitle_style: foo\nbg_music: bar"
        with pytest.raises(StoryboardParseError, match="visual_style"):
            _parse_global(bad_block)


class TestParseScene:
    def test_still_with_motion(self):
        scene = _parse_scene(SAMPLE_SCENE_BLOCK)
        assert scene.scene == "1"
        assert scene.clip_type == "still_with_motion"
        assert scene.duration_s == 2.0
        assert scene.voiceover_line == "The American dream is slipping away."
        assert scene.visual_prompts.primary_stk == "family home suburban street daytime"
        assert scene.visual_prompts.fallback_stk == "american neighborhood houses"
        assert "Aerial view" in scene.visual_prompts.ai_generate
        assert scene.motion_effect == "zoom-in"
        assert scene.on_screen_text is None
        assert scene.sfx == "soft ambient neighborhood sounds"
        assert scene.sfx_timing == "on cut"

    def test_hard_cut_sub_scene(self):
        scene = _parse_scene(SAMPLE_SCENE_BLOCK_HARD_CUT)
        assert scene.scene == "3a"
        assert scene.clip_type == "hard_cut"
        assert scene.duration_s == 0.5
        assert scene.motion_effect is None
        assert scene.on_screen_text == "Rising rents"

    def test_duration_with_trailing_s(self):
        block = SAMPLE_SCENE_BLOCK.replace("duration_s: 2.0", "duration_s: 2.0s")
        scene = _parse_scene(block)
        assert scene.duration_s == 2.0

    def test_missing_scene_header_raises(self):
        bad_block = SAMPLE_SCENE_BLOCK.replace("SCENE 1", "")
        with pytest.raises(StoryboardParseError, match="SCENE header"):
            _parse_scene(bad_block)

    def test_missing_primary_prompt_raises(self):
        bad_block = SAMPLE_SCENE_BLOCK.replace(
            "  PRIMARY: STK `family home suburban street daytime`", ""
        )
        with pytest.raises(StoryboardParseError, match="PRIMARY"):
            _parse_scene(bad_block)

    def test_invalid_duration_raises(self):
        bad_block = SAMPLE_SCENE_BLOCK.replace("duration_s: 2.0", "duration_s: not-a-number")
        with pytest.raises(StoryboardParseError, match="duration_s"):
            _parse_scene(bad_block)

    def test_invalid_clip_type_raises(self):
        bad_block = SAMPLE_SCENE_BLOCK.replace("clip_type: still_with_motion", "clip_type: warp_speed")
        with pytest.raises(Exception):
            _parse_scene(bad_block)


class TestParseSummary:
    def test_happy_path(self):
        summary = _parse_summary(SAMPLE_SUMMARY_BLOCK)
        assert summary.total_scenes == 2
        assert summary.total_duration_s == 38.5
        assert summary.rhythm == "SM / HC"

    def test_missing_total_scenes_raises(self):
        bad = "SUMMARY\nTotal duration: 10s\nRhythm: SM"
        with pytest.raises(StoryboardParseError, match="Total scenes"):
            _parse_summary(bad)

    def test_missing_rhythm_raises(self):
        bad = "SUMMARY\nTotal scenes: 2\nTotal duration: 38.5s"
        with pytest.raises(StoryboardParseError, match="Rhythm"):
            _parse_summary(bad)


class TestParseStoryboardResponse:
    def test_full_response(self):
        storyboard = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        assert len(storyboard.scenes) == 2
        assert storyboard.global_.visual_style.startswith("Dark cinematic")
        assert storyboard.summary.total_scenes == 2

    def test_too_few_sections_raises(self):
        with pytest.raises(StoryboardParseError, match="sections"):
            _parse_storyboard_response("GLOBAL\nfoo: bar\n---\nSUMMARY\nTotal scenes: 0")

    def test_serializes_with_global_alias(self):
        storyboard = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        data = storyboard.model_dump(by_alias=True, mode="json")
        assert "global" in data
        assert "global_" not in data
        assert "scenes" in data
        assert "summary" in data


# ── Route integration tests ───────────────────────────────────────────────────


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


@pytest.fixture()
def client():
    """TestClient with settings dependency injected (no lifespan triggered)."""
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


RUN_ID = "2026-05-22_test-affordability"


class TestStoryboardRoute:
    def _mock_storage(self):
        mock = MagicMock()
        mock.upload_json.return_value = None
        mock.update_run_log.return_value = None
        return mock

    def test_success(self, client):
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = storyboard_data
            mock_r2.return_value = self._mock_storage()

            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test voiceover script."},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["storyboard_key"] == f"runs/{RUN_ID}/storyboard.json"

    def test_success_uploads_and_updates_run_log(self, client):
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = storyboard_data
            mock_r2.return_value = mock_storage

            client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        mock_storage.upload_json.assert_called_once()
        call_key = mock_storage.upload_json.call_args[0][0]
        assert call_key == f"runs/{RUN_ID}/storyboard.json"

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "storyboard",
            "complete",
            output_url=f"runs/{RUN_ID}/storyboard.json",
        )

    def test_api_error_returns_500(self, client):
        with (
            patch(
                "src.routes.storyboard.generate_storyboard",
                new_callable=AsyncMock,
                side_effect=StoryboardAPIError("Claude API unavailable"),
            ),
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_r2.return_value = self._mock_storage()
            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        assert response.status_code == 500
        assert "Claude API unavailable" in response.json()["detail"]

    def test_parse_error_returns_500(self, client):
        with (
            patch(
                "src.routes.storyboard.generate_storyboard",
                new_callable=AsyncMock,
                side_effect=StoryboardParseError("Missing PRIMARY prompt"),
            ),
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_r2.return_value = self._mock_storage()
            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        assert response.status_code == 500
        assert "Missing PRIMARY prompt" in response.json()["detail"]

    def test_failure_updates_run_log_as_failed(self, client):
        mock_storage = self._mock_storage()

        with (
            patch(
                "src.routes.storyboard.generate_storyboard",
                new_callable=AsyncMock,
                side_effect=StoryboardAPIError("timeout"),
            ),
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_r2.return_value = mock_storage
            client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "storyboard",
            "failed",
            error="timeout",
        )

    def test_storage_error_on_upload_returns_500(self, client):
        from src.exceptions import StorageError

        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()
        mock_storage.upload_json.side_effect = StorageError("R2 write failed")

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = storyboard_data
            mock_r2.return_value = mock_storage

            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        assert response.status_code == 500
        assert "R2 write failed" in response.json()["detail"]
