"""Tests for Haiku-based storyboard schema validator."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import StoryboardValidationError
from src.models import Storyboard, ValidationResult
from src.storyboard import _parse_storyboard_response
from src.validators.storyboard_validator import (
    VALIDATOR_MODEL,
    _INPUT_COST_PER_TOKEN,
    _OUTPUT_COST_PER_TOKEN,
    validate_storyboard,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_STORYBOARD_TEXT = """\
GLOBAL
subtitle_style: Bold white, lower third
bg_music: Tense ambient, 80 BPM, -18dB
visual_style: Dark cinematic, high contrast

---

SCENE 1
clip_type: still_with_motion
duration_s: 2.0
voiceover_line: "Housing costs keep rising."
visual_prompts:
  PRIMARY: STK `housing market prices graph`
  FALLBACK: STK `house`
  AI_GENERATE if no stock: `A house with a price tag, golden hour, cinematic 9:16`
motion_effect: zoom-in
on_screen_text: null
sfx: soft ambient sounds
sfx_timing: on cut

---

SUMMARY
Total scenes: 1
Total duration: 2.0s
Rhythm: SM"""


def _make_storyboard() -> Storyboard:
    """Return a minimal valid parsed Storyboard for use in tests."""
    return _parse_storyboard_response(SAMPLE_STORYBOARD_TEXT)


def _make_message(response_json: dict, input_tokens: int = 100, output_tokens: int = 30) -> MagicMock:
    """Build a mock Anthropic message with content[0].text and usage."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(response_json))]
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    return msg


# ── Unit tests: validate_storyboard ──────────────────────────────────────────


class TestValidateStoryboard:
    @pytest.mark.asyncio
    async def test_valid_storyboard_returns_valid_true(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_invalid_storyboard_returns_valid_false_with_errors(self):
        storyboard = _make_storyboard()
        errors = ["scene 1: sfx is null", "scene 2: still_with_motion scene has null motion_effect"]
        mock_message = _make_message({"valid": False, "errors": errors})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is False
        assert result.errors == errors

    @pytest.mark.asyncio
    async def test_tokens_recorded_on_result(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []}, input_tokens=150, output_tokens=40)

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.input_tokens == 150
        assert result.output_tokens == 40

    @pytest.mark.asyncio
    async def test_cost_usd_calculated_correctly(self):
        storyboard = _make_storyboard()
        input_tokens = 200
        output_tokens = 50
        mock_message = _make_message(
            {"valid": True, "errors": []},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        expected_cost = round(
            input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN, 8
        )
        assert result.cost_usd == expected_cost

    @pytest.mark.asyncio
    async def test_api_error_raises_validation_error(self):
        import anthropic as anthropic_lib

        storyboard = _make_storyboard()

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=anthropic_lib.APIConnectionError(request=MagicMock())
            )

            with pytest.raises(StoryboardValidationError, match="Haiku validation API error"):
                await validate_storyboard(storyboard, "test-key")

    @pytest.mark.asyncio
    async def test_unparseable_json_response_raises_validation_error(self):
        storyboard = _make_storyboard()
        msg = MagicMock()
        msg.content = [MagicMock(text="not valid json at all")]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 10

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=msg)

            with pytest.raises(StoryboardValidationError, match="invalid validation JSON"):
                await validate_storyboard(storyboard, "test-key")

    @pytest.mark.asyncio
    async def test_missing_valid_key_raises_validation_error(self):
        storyboard = _make_storyboard()
        msg = MagicMock()
        msg.content = [MagicMock(text='{"errors": []}')]  # no "valid" key
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 10

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=msg)

            with pytest.raises(StoryboardValidationError, match="invalid validation JSON"):
                await validate_storyboard(storyboard, "test-key")

    @pytest.mark.asyncio
    async def test_uses_haiku_model(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            await validate_storyboard(storyboard, "test-key")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == VALIDATOR_MODEL

    @pytest.mark.asyncio
    async def test_storyboard_serialised_as_json_in_user_message(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            await validate_storyboard(storyboard, "test-key")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        parsed = json.loads(user_content)
        assert "global" in parsed
        assert "scenes" in parsed
        assert "summary" in parsed

    @pytest.mark.asyncio
    async def test_empty_errors_list_when_valid(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert isinstance(result.errors, list)
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_returns_validation_result_type(self):
        storyboard = _make_storyboard()
        mock_message = _make_message({"valid": True, "errors": []})

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_fenced_json_response_parsed_correctly(self):
        """Haiku sometimes wraps its JSON reply in ```json ... ``` fences."""
        storyboard = _make_storyboard()
        fenced = '```json\n{"valid": true, "errors": []}\n```'
        msg = MagicMock()
        msg.content = [MagicMock(text=fenced)]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 10

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=msg)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_plain_fenced_response_parsed_correctly(self):
        """Haiku sometimes uses ``` without a language tag."""
        storyboard = _make_storyboard()
        fenced = '```\n{"valid": false, "errors": ["scene 1: sfx is null"]}\n```'
        msg = MagicMock()
        msg.content = [MagicMock(text=fenced)]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 10

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=msg)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is False
        assert result.errors == ["scene 1: sfx is null"]

    @pytest.mark.asyncio
    async def test_fenced_response_with_extra_whitespace_parsed_correctly(self):
        """Fence stripping handles trailing newlines and spaces around the JSON."""
        storyboard = _make_storyboard()
        fenced = '```json\n  {"valid": true, "errors": []}  \n```'
        msg = MagicMock()
        msg.content = [MagicMock(text=fenced)]
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 10

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=msg)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is True

    @pytest.mark.asyncio
    async def test_duration_errors_are_filtered(self):
        """Haiku may hallucinate duration limits — they must be filtered out."""
        storyboard = _make_storyboard()
        mock_message = _make_message(
            {"valid": False, "errors": ["scene 3: duration_s=1.5 exceeds hard_cut ceiling"]}
        )

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_duration_errors_filtered_preserves_real_errors(self):
        """Real schema errors are kept when duration hallucination is also present."""
        storyboard = _make_storyboard()
        mock_message = _make_message(
            {
                "valid": False,
                "errors": [
                    "scene 3: duration_s=1.5 exceeds hard_cut ceiling",
                    "scene 2: sfx is null",
                ],
            }
        )

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is False
        assert result.errors == ["scene 2: sfx is null"]

    @pytest.mark.asyncio
    async def test_subtitle_style_errors_are_filtered(self):
        """subtitle_style is optional metadata — Haiku errors about it must be filtered."""
        storyboard = _make_storyboard()
        mock_message = _make_message(
            {"valid": False, "errors": ["global: missing required field subtitle_style"]}
        )

        with patch("src.validators.storyboard_validator.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_message)

            result = await validate_storyboard(storyboard, "test-key")

        assert result.valid is True
        assert result.errors == []
