"""Tests for storyboard generation — parser unit tests and route integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import StoryboardAPIError, StoryboardParseError, StoryboardValidationError, StorageError
from src.main import app
from src.models import ValidationResult, WordTimestamp
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
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
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

    def test_missing_subtitle_style_defaults_to_empty_string(self):
        """subtitle_style is optional — missing yields empty string."""
        block = "GLOBAL\nbg_music: lo-fi beats 80bpm\nvisual_style: dark cinematic"
        result = _parse_global(block)
        assert result.subtitle_style == ""
        assert result.bg_music == "lo-fi beats 80bpm"

    def test_null_subtitle_style_defaults_to_empty_string(self):
        """subtitle_style: null is treated as empty string."""
        block = "GLOBAL\nsubtitle_style: null\nbg_music: lo-fi\nvisual_style: cinematic"
        result = _parse_global(block)
        assert result.subtitle_style == ""

    def test_missing_bg_music_defaults_to_empty_string(self):
        """bg_music is optional metadata — missing yields empty string."""
        block = "GLOBAL\nsubtitle_style: foo\nvisual_style: cinematic"
        result = _parse_global(block)
        assert result.bg_music == ""

    def test_missing_visual_style_defaults_to_empty_string(self):
        """visual_style is optional metadata — missing yields empty string."""
        block = "GLOBAL\nsubtitle_style: foo\nbg_music: lo-fi"
        result = _parse_global(block)
        assert result.visual_style == ""

    def test_completely_empty_global_block_uses_all_defaults(self):
        """Totally absent global fields all default to empty strings."""
        result = _parse_global("GLOBAL")
        assert result.subtitle_style == ""
        assert result.bg_music == ""
        assert result.visual_style == ""

    def test_markdown_bold_field_name_parsed(self):
        """Claude markdown bold (**field:**) formatting is stripped and parsed."""
        block = "GLOBAL\n**subtitle_style:** Poppins Bold\n**bg_music:** lo-fi\n**visual_style:** dark"
        result = _parse_global(block)
        assert result.subtitle_style == "Poppins Bold"
        assert result.bg_music == "lo-fi"


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
        """No SCENE keyword at all → raises StoryboardParseError."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("SCENE 1", "")
        with pytest.raises(StoryboardParseError, match="SCENE header"):
            _parse_scene(bad_block)

    def test_scene_without_numeric_id_uses_block_index(self):
        """SCENE keyword with no number falls back to 1-based block index."""
        block = SAMPLE_SCENE_BLOCK.replace("SCENE 1\n", "SCENE\n")
        scene = _parse_scene(block, index=2)  # 3rd block → id "3"
        assert scene.scene == "3"

    def test_scene_without_numeric_id_does_not_capture_field_name(self):
        """'SCENE\\nvisual_style: ...' must not set scene_id to 'visual_style:'."""
        block = SAMPLE_SCENE_BLOCK.replace("SCENE 1\n", "SCENE\n")
        scene = _parse_scene(block, index=0)
        assert ":" not in scene.scene
        assert "visual_style" not in scene.scene

    def test_missing_clip_type_defaults_to_still_with_motion(self):
        """Missing clip_type falls back to still_with_motion."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("clip_type: still_with_motion\n", "")
        scene = _parse_scene(bad_block)
        assert scene.clip_type == "still_with_motion"

    def test_invalid_clip_type_defaults_to_still_with_motion(self):
        """Unrecognised clip_type value falls back to still_with_motion."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("clip_type: still_with_motion", "clip_type: warp_speed")
        scene = _parse_scene(bad_block)
        assert scene.clip_type == "still_with_motion"

    def test_invalid_duration_defaults_to_2_seconds(self):
        """Unparseable duration_s falls back to 2.0 instead of crashing."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("duration_s: 2.0", "duration_s: not-a-number")
        scene = _parse_scene(bad_block)
        assert scene.duration_s == 2.0

    def test_missing_duration_defaults_to_2_seconds(self):
        """Missing duration_s falls back to 2.0."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("duration_s: 2.0\n", "")
        scene = _parse_scene(bad_block)
        assert scene.duration_s == 2.0

    def test_missing_voiceover_line_defaults_to_empty(self):
        """Missing voiceover_line falls back to empty string."""
        bad_block = SAMPLE_SCENE_BLOCK.replace('voiceover_line: "The American dream is slipping away."\n', "")
        scene = _parse_scene(bad_block)
        assert scene.voiceover_line == ""

    def test_missing_sfx_defaults_to_silence(self):
        """Missing sfx falls back to 'silence' — never null."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("sfx: soft ambient neighborhood sounds\n", "")
        scene = _parse_scene(bad_block)
        assert scene.sfx == "silence"

    def test_missing_sfx_timing_defaults_to_scene_start(self):
        """Missing sfx_timing falls back to 'scene_start'."""
        bad_block = SAMPLE_SCENE_BLOCK.replace("sfx_timing: on cut", "")
        scene = _parse_scene(bad_block)
        assert scene.sfx_timing == "scene_start"

    def test_missing_primary_prompt_defaults_to_empty(self):
        """Missing PRIMARY visual prompt yields empty string instead of crash."""
        bad_block = SAMPLE_SCENE_BLOCK.replace(
            "  PRIMARY: STK `family home suburban street daytime`\n", ""
        )
        scene = _parse_scene(bad_block)
        assert scene.visual_prompts.primary_stk == ""

    def test_still_with_motion_defaults_motion_effect_to_zoom_in(self):
        """still_with_motion scene with no motion_effect defaults to zoom_in."""
        block = SAMPLE_SCENE_BLOCK.replace("motion_effect: zoom-in\n", "")
        scene = _parse_scene(block)
        assert scene.clip_type == "still_with_motion"
        assert scene.motion_effect == "zoom_in"

    def test_hard_cut_allows_null_motion_effect(self):
        """hard_cut scene does not get a default motion_effect."""
        scene = _parse_scene(SAMPLE_SCENE_BLOCK_HARD_CUT)
        assert scene.clip_type == "hard_cut"
        assert scene.motion_effect is None

    def test_visual_prompt_without_backticks_parsed(self):
        """Visual prompts without backtick delimiters are accepted."""
        block = SAMPLE_SCENE_BLOCK.replace(
            "  PRIMARY: STK `family home suburban street daytime`",
            "  PRIMARY: STK family home suburban street daytime",
        )
        scene = _parse_scene(block)
        assert scene.visual_prompts.primary_stk == "family home suburban street daytime"

    def test_visual_prompt_without_stk_keyword(self):
        """Visual prompts formatted without 'STK' keyword are accepted."""
        block = SAMPLE_SCENE_BLOCK.replace(
            "  PRIMARY: STK `family home suburban street daytime`",
            "  PRIMARY: `family home suburban street daytime`",
        )
        scene = _parse_scene(block)
        assert scene.visual_prompts.primary_stk == "family home suburban street daytime"

    def test_visual_prompt_yaml_style_field_name(self):
        """YAML-style 'primary_stk: value' format is accepted."""
        block = SAMPLE_SCENE_BLOCK.replace(
            "  PRIMARY: STK `family home suburban street daytime`",
            "primary_stk: family home suburban street daytime",
        )
        scene = _parse_scene(block)
        assert scene.visual_prompts.primary_stk == "family home suburban street daytime"


class TestParseSummary:
    def test_happy_path(self):
        summary = _parse_summary(SAMPLE_SUMMARY_BLOCK)
        assert summary.total_scenes == 2
        assert summary.total_duration_s == 38.5
        assert summary.rhythm == "SM / HC"

    def test_missing_total_scenes_falls_back_to_scene_count(self):
        """Missing total_scenes is computed from the passed scenes list."""
        from src.storyboard import _parse_scene
        from tests.test_storyboard import SAMPLE_SCENE_BLOCK
        scene = _parse_scene(SAMPLE_SCENE_BLOCK)
        bad = "SUMMARY\nTotal duration: 10s\nRhythm: SM"
        summary = _parse_summary(bad, scenes=[scene, scene])
        assert summary.total_scenes == 2

    def test_missing_total_duration_computed_from_scenes(self):
        """Missing total_duration_s is summed from scene duration_s values."""
        from src.storyboard import _parse_scene
        scene = _parse_scene(SAMPLE_SCENE_BLOCK)  # duration_s == 2.0
        bad = "SUMMARY\nTotal scenes: 1\nRhythm: SM"
        summary = _parse_summary(bad, scenes=[scene])
        assert summary.total_duration_s == pytest.approx(2.0)

    def test_missing_rhythm_defaults_to_empty(self):
        """Missing Rhythm defaults to empty string."""
        bad = "SUMMARY\nTotal scenes: 2\nTotal duration: 38.5s"
        summary = _parse_summary(bad)
        assert summary.rhythm == ""


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

_MOCK_VALIDATION = ValidationResult(
    valid=True,
    errors=[],
    input_tokens=50,
    output_tokens=20,
    cost_usd=round(50 * 0.80 / 1_000_000 + 20 * 4.00 / 1_000_000, 8),
)


class TestStoryboardRoute:
    def _mock_storage(self):
        """Build a mock storage that raises StorageError for alignment.json (default: no alignment)."""
        mock = MagicMock()
        mock.upload_json.return_value = None
        mock.update_run_log.return_value = None
        mock.get_json.side_effect = StorageError("alignment.json not found")
        return mock

    def test_success(self, client):
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
            mock_r2.return_value = self._mock_storage()

            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test voiceover script."},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["storyboard_key"] == f"runs/{RUN_ID}/storyboard.json"

    def test_success_uploads_and_updates_run_log_with_cost(self, client):
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
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
            input_tokens=_MOCK_VALIDATION.input_tokens,
            output_tokens=_MOCK_VALIDATION.output_tokens,
            cost_usd=_MOCK_VALIDATION.cost_usd,
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

    def test_validation_error_returns_500(self, client):
        with (
            patch(
                "src.routes.storyboard.generate_storyboard",
                new_callable=AsyncMock,
                side_effect=StoryboardValidationError(
                    "Storyboard validation failed: scene 2: sfx is null"
                ),
            ),
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_r2.return_value = self._mock_storage()
            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        assert response.status_code == 500
        assert "validation failed" in response.json()["detail"]

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

    def test_validation_failure_updates_run_log_as_failed(self, client):
        mock_storage = self._mock_storage()
        error_msg = "Storyboard validation failed: scene 1: sfx is null"

        with (
            patch(
                "src.routes.storyboard.generate_storyboard",
                new_callable=AsyncMock,
                side_effect=StoryboardValidationError(error_msg),
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
            error=error_msg,
        )

    def test_storage_error_on_upload_returns_500(self, client):
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()
        mock_storage.upload_json.side_effect = StorageError("R2 write failed")

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
            mock_r2.return_value = mock_storage

            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "Test script."},
            )

        assert response.status_code == 500
        assert "R2 write failed" in response.json()["detail"]

    def test_alignment_timestamps_passed_to_generate_storyboard(self, client):
        """When alignment.json is in R2, word_timestamps are passed to generate_storyboard."""
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()
        mock_storage.get_json.side_effect = None  # clear StorageError default
        mock_storage.get_json.return_value = {
            "run_id": RUN_ID,
            "word_count": 3,
            "used_fallback": False,
            "words": [
                {"word": "housing", "start_ms": 0, "end_ms": 500, "confidence": 0.99},
                {"word": "market", "start_ms": 500, "end_ms": 900, "confidence": 0.98},
                {"word": "crisis", "start_ms": 900, "end_ms": 1400, "confidence": 0.97},
            ],
        }

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
            mock_r2.return_value = mock_storage

            response = client.post(
                f"/runs/{RUN_ID}/storyboard",
                json={"script": "housing market crisis"},
            )

        assert response.status_code == 200
        _, call_kwargs = mock_gen.call_args
        timestamps = call_kwargs.get("word_timestamps") or mock_gen.call_args[0][2]
        assert timestamps is not None
        assert len(timestamps) == 3
        assert timestamps[0].word == "housing"
        assert timestamps[0].start_ms == 0

    def test_no_alignment_passes_none_to_generate_storyboard(self, client):
        """When alignment.json is absent, word_timestamps=None is passed to generate_storyboard."""
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()  # defaults to StorageError for get_json

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
            mock_r2.return_value = mock_storage

            client.post(f"/runs/{RUN_ID}/storyboard", json={"script": "Test script."})

        _, call_kwargs = mock_gen.call_args
        timestamps = call_kwargs.get("word_timestamps") or (mock_gen.call_args[0][2] if len(mock_gen.call_args[0]) > 2 else None)
        assert timestamps is None

    def test_empty_body_script_falls_back_to_script_txt(self, client):
        """When body.script is empty, the route reads script.txt from R2 and uses it."""
        storyboard_data = _parse_storyboard_response(SAMPLE_FULL_RESPONSE)
        mock_storage = self._mock_storage()
        saved_script = "Houses are too expensive. Nobody can afford them."
        mock_storage.get_bytes.return_value = saved_script.encode("utf-8")

        with (
            patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.storyboard.R2Client") as mock_r2,
        ):
            mock_gen.return_value = (storyboard_data, _MOCK_VALIDATION)
            mock_r2.return_value = mock_storage

            response = client.post(f"/runs/{RUN_ID}/storyboard", json={"script": ""})

        assert response.status_code == 200
        used_script = mock_gen.call_args[0][0]
        assert used_script == saved_script

    def test_missing_script_and_no_draft_returns_422(self, client):
        """When body.script is empty and script.txt is absent, HTTP 422 is returned."""
        mock_storage = self._mock_storage()
        mock_storage.get_bytes.side_effect = StorageError("NoSuchKey")

        with patch("src.routes.storyboard.R2Client") as mock_r2:
            mock_r2.return_value = mock_storage
            response = client.post(f"/runs/{RUN_ID}/storyboard", json={"script": ""})

        assert response.status_code == 422
        assert "script is required" in response.json()["detail"]
