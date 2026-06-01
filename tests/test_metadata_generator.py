"""Tests for metadata generator — unit tests for parser and route integration tests."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import MetadataError, StorageError
from src.main import app
from src.metadata_generator import _build_user_message, _extract_json, generate_metadata
from src.models import (
    PublishingMetadata,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
)
from src.utils.model_router import ModelRouter

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

RUN_ID = "2026-06-01_housing-metadata-test"

SAMPLE_METADATA_DICT = {
    "title": "Why Americans Can't Afford Homes in 2024",
    "alt_titles": [
        "The Housing Crisis No One Is Talking About",
        "Home Prices vs. Your Salary: The Brutal Math",
    ],
    "youtube_description": (
        "The gap between home prices and wages has never been wider. "
        "We break down the numbers behind America's housing affordability crisis "
        "and what it means for first-time buyers. Follow for weekly housing data."
    ),
    "instagram_description": "Home prices have outpaced wages for 10 straight years. Here's why it matters. 🏠",
    "hashtags": ["realestate", "housingcrisis", "homebuying", "personalfinance"],
    "seo_tags": ["housing market 2024", "home prices", "mortgage rates", "real estate investing"],
}


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


def _make_storyboard() -> Storyboard:
    """Build a minimal Storyboard instance for testing."""
    scene = StoryboardScene(
        scene="1",
        clip_type="still_with_motion",
        duration_s=2.5,
        voiceover_line="Americans are being priced out of homes.",
        visual_prompts=VisualPrompts(
            primary_stk="house family neighborhood",
            fallback_stk="neighborhood",
            ai_generate="A suburban house at golden hour, cinematic 9:16",
        ),
        motion_effect="zoom_in",
        sfx="ambient suburban sounds",
        sfx_timing="on cut",
    )
    return Storyboard(
        global_=StoryboardGlobal(
            subtitle_style="Bold white lower third",
            bg_music="Tense ambient -18dB",
            visual_style="Cinematic",
        ),
        scenes=[scene],
        summary=StoryboardSummary(total_scenes=1, total_duration_s=2.5, rhythm="SM"),
    )


@pytest.fixture()
def client():
    """TestClient with settings dependency injected (no lifespan triggered)."""
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ── Unit tests: _extract_json ──────────────────────────────────────────────────


class TestExtractJson:
    def test_parses_clean_json(self):
        raw = json.dumps(SAMPLE_METADATA_DICT)
        result = _extract_json(raw)
        assert result["title"] == SAMPLE_METADATA_DICT["title"]

    def test_strips_json_markdown_fence(self):
        raw = f"```json\n{json.dumps(SAMPLE_METADATA_DICT)}\n```"
        result = _extract_json(raw)
        assert result["title"] == SAMPLE_METADATA_DICT["title"]

    def test_strips_plain_markdown_fence(self):
        raw = f"```\n{json.dumps(SAMPLE_METADATA_DICT)}\n```"
        result = _extract_json(raw)
        assert result["title"] == SAMPLE_METADATA_DICT["title"]

    def test_raises_metadata_error_on_invalid_json(self):
        with pytest.raises(MetadataError, match="Could not extract JSON"):
            _extract_json("This is not JSON at all.")

    def test_raises_metadata_error_on_empty_string(self):
        with pytest.raises(MetadataError):
            _extract_json("")


# ── Unit tests: _build_user_message ───────────────────────────────────────────


class TestBuildUserMessage:
    def test_includes_project_name(self):
        storyboard = _make_storyboard()
        msg = _build_user_message("Housing Crisis 2024", storyboard)
        assert "Housing Crisis 2024" in msg

    def test_includes_voiceover_lines(self):
        storyboard = _make_storyboard()
        msg = _build_user_message("Test Project", storyboard)
        assert "Americans are being priced out of homes." in msg

    def test_includes_visual_style(self):
        storyboard = _make_storyboard()
        msg = _build_user_message("Test Project", storyboard)
        assert "Cinematic" in msg

    def test_skips_empty_voiceover_lines(self):
        storyboard = _make_storyboard()
        storyboard.scenes[0].voiceover_line = ""
        msg = _build_user_message("Test Project", storyboard)
        # Scene with empty VO line should not appear in the script section
        assert "Scene 1:" not in msg


# ── Unit tests: generate_metadata ─────────────────────────────────────────────


class TestGenerateMetadata:
    @pytest.fixture()
    def settings(self):
        """Return a minimal Settings instance for unit tests."""
        return _make_settings()

    @pytest.fixture()
    def router_obj(self, settings):
        """Return a ModelRouter bound to test settings."""
        return ModelRouter(settings)

    @pytest.mark.asyncio
    async def test_happy_path_returns_metadata(self, settings, router_obj):
        storyboard = _make_storyboard()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(SAMPLE_METADATA_DICT))]
        mock_message.usage.input_tokens = 100
        mock_message.usage.output_tokens = 50

        with patch("src.metadata_generator.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            metadata, input_tokens, output_tokens, cost_usd = await generate_metadata(
                "Housing Crisis", storyboard, "test-key", router_obj
            )

        assert isinstance(metadata, PublishingMetadata)
        assert metadata.title == SAMPLE_METADATA_DICT["title"]
        assert len(metadata.alt_titles) == 2
        assert isinstance(metadata.hashtags, list)
        assert isinstance(metadata.seo_tags, list)
        assert input_tokens == 100
        assert output_tokens == 50
        assert cost_usd >= 0

    @pytest.mark.asyncio
    async def test_api_error_raises_metadata_error(self, settings, router_obj):
        import anthropic as anthropic_module

        storyboard = _make_storyboard()

        with patch("src.metadata_generator.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=anthropic_module.APIStatusError(
                    "rate limited",
                    response=MagicMock(status_code=429),
                    body={},
                )
            )

            with pytest.raises(MetadataError, match="Claude API error"):
                await generate_metadata("Test", storyboard, "test-key", router_obj)

    @pytest.mark.asyncio
    async def test_invalid_json_raises_metadata_error(self, settings, router_obj):
        storyboard = _make_storyboard()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="not valid json")]
        mock_message.usage.input_tokens = 10
        mock_message.usage.output_tokens = 5

        with patch("src.metadata_generator.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            with pytest.raises(MetadataError, match="Could not extract JSON"):
                await generate_metadata("Test", storyboard, "test-key", router_obj)

    @pytest.mark.asyncio
    async def test_schema_mismatch_raises_metadata_error(self, settings, router_obj):
        """Missing required fields in Claude JSON response raises MetadataError."""
        storyboard = _make_storyboard()
        bad_data = {"title": "Only a title, nothing else"}
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(bad_data))]
        mock_message.usage.input_tokens = 10
        mock_message.usage.output_tokens = 5

        with patch("src.metadata_generator.anthropic.AsyncAnthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            with pytest.raises(MetadataError, match="schema validation failed"):
                await generate_metadata("Test", storyboard, "test-key", router_obj)


# ── Route integration tests ───────────────────────────────────────────────────


SAMPLE_STORYBOARD_JSON = {
    "global": {
        "subtitle_style": "Bold white",
        "bg_music": "Ambient -18dB",
        "visual_style": "Cinematic",
    },
    "scenes": [
        {
            "scene": "1",
            "clip_type": "still_with_motion",
            "duration_s": 2.5,
            "voiceover_line": "Americans are being priced out.",
            "visual_prompts": {
                "primary_stk": "house neighborhood",
                "fallback_stk": "house",
                "ai_generate": "Suburban house, cinematic",
            },
            "motion_effect": "zoom_in",
            "sfx": "ambient",
            "sfx_timing": "on cut",
        }
    ],
    "summary": {"total_scenes": 1, "total_duration_s": 2.5, "rhythm": "SM"},
}

SAMPLE_RUN_LOG = {
    "run_id": RUN_ID,
    "created_at": "2026-06-01T12:00:00",
    "project_name": "Housing Crisis 2024",
    "steps": {step: {"status": "pending"} for step in ["alignment", "storyboard", "asset_manifest",
                                                         "asset_acquisition", "ffmpeg_script", "render",
                                                         "metadata"]},
}


class TestMetadataRoute:
    def _mock_storage(self, run_log=None, storyboard=None):
        """Return a mock R2Client with configurable get_json responses."""
        mock = MagicMock()
        mock.upload_json.return_value = None
        mock.update_run_log.return_value = None

        responses = {
            f"runs/{RUN_ID}/run_log.json": run_log or SAMPLE_RUN_LOG,
            f"runs/{RUN_ID}/storyboard.json": storyboard or SAMPLE_STORYBOARD_JSON,
        }

        def get_json_side_effect(key):
            if key in responses:
                return responses[key]
            raise StorageError(f"Key not found: {key}")

        mock.get_json.side_effect = get_json_side_effect
        return mock

    def test_success(self, client):
        metadata = PublishingMetadata(**SAMPLE_METADATA_DICT)

        with (
            patch("src.routes.metadata.generate_metadata", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.metadata.R2Client") as mock_r2,
            patch("src.routes.metadata.pipeline.summarize_step"),
        ):
            mock_gen.return_value = (metadata, 100, 50, 0.0001)
            mock_r2.return_value = self._mock_storage()

            response = client.post(f"/runs/{RUN_ID}/metadata")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["metadata_key"] == f"runs/{RUN_ID}/metadata.json"

    def test_success_uploads_and_updates_run_log(self, client):
        metadata = PublishingMetadata(**SAMPLE_METADATA_DICT)
        mock_storage = self._mock_storage()

        with (
            patch("src.routes.metadata.generate_metadata", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.metadata.R2Client") as mock_r2,
            patch("src.routes.metadata.pipeline.summarize_step"),
        ):
            mock_gen.return_value = (metadata, 100, 50, 0.0001)
            mock_r2.return_value = mock_storage

            client.post(f"/runs/{RUN_ID}/metadata")

        mock_storage.upload_json.assert_called_once_with(
            f"runs/{RUN_ID}/metadata.json", metadata.model_dump()
        )
        mock_storage.update_run_log.assert_called_once()
        call_kwargs = mock_storage.update_run_log.call_args
        assert call_kwargs.args[2] == "complete"

    def test_run_not_found_returns_404(self, client):
        with (
            patch("src.routes.metadata.R2Client") as mock_r2,
        ):
            mock = MagicMock()
            mock.get_json.side_effect = StorageError("not found")
            mock_r2.return_value = mock

            response = client.post(f"/runs/{RUN_ID}/metadata")

        assert response.status_code == 404

    def test_storyboard_not_found_returns_404(self, client):
        with (
            patch("src.routes.metadata.R2Client") as mock_r2,
        ):
            mock = MagicMock()

            def get_json(key):
                if "run_log" in key:
                    return SAMPLE_RUN_LOG
                raise StorageError("storyboard not found")

            mock.get_json.side_effect = get_json
            mock_r2.return_value = mock

            response = client.post(f"/runs/{RUN_ID}/metadata")

        assert response.status_code == 404

    def test_metadata_error_returns_500_and_marks_failed(self, client):
        mock_storage = self._mock_storage()

        with (
            patch("src.routes.metadata.generate_metadata", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.metadata.R2Client") as mock_r2,
            patch("src.routes.metadata.pipeline.summarize_step"),
        ):
            mock_gen.side_effect = MetadataError("Claude API timed out")
            mock_r2.return_value = mock_storage

            response = client.post(f"/runs/{RUN_ID}/metadata")

        assert response.status_code == 500
        mock_storage.update_run_log.assert_called_once()
        call_kwargs = mock_storage.update_run_log.call_args
        assert call_kwargs.args[2] == "failed"

    def test_storage_error_on_upload_returns_500(self, client):
        metadata = PublishingMetadata(**SAMPLE_METADATA_DICT)
        mock_storage = self._mock_storage()
        mock_storage.upload_json.side_effect = StorageError("R2 upload failed")

        with (
            patch("src.routes.metadata.generate_metadata", new_callable=AsyncMock) as mock_gen,
            patch("src.routes.metadata.R2Client") as mock_r2,
            patch("src.routes.metadata.pipeline.summarize_step"),
        ):
            mock_gen.return_value = (metadata, 100, 50, 0.0001)
            mock_r2.return_value = mock_storage

            response = client.post(f"/runs/{RUN_ID}/metadata")

        assert response.status_code == 500

    def test_project_name_falls_back_to_run_id(self, client):
        """When run_log has no project_name, run_id is used as fallback."""
        run_log_no_name = {**SAMPLE_RUN_LOG, "project_name": None}
        metadata = PublishingMetadata(**SAMPLE_METADATA_DICT)
        mock_storage = self._mock_storage(run_log=run_log_no_name)
        captured_args = {}

        async def capture_gen(project_name, storyboard, api_key, router):
            captured_args["project_name"] = project_name
            return metadata, 100, 50, 0.0001

        with (
            patch("src.routes.metadata.generate_metadata", side_effect=capture_gen),
            patch("src.routes.metadata.R2Client") as mock_r2,
            patch("src.routes.metadata.pipeline.summarize_step"),
        ):
            mock_r2.return_value = mock_storage
            client.post(f"/runs/{RUN_ID}/metadata")

        assert captured_args["project_name"] == RUN_ID
