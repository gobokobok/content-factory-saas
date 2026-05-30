"""Tests for ModelRouter — src/utils/model_router.py."""

from unittest.mock import MagicMock, patch

import pytest

from src.utils.model_router import (
    DEFAULT_MODELS,
    GENERATE,
    PRICING,
    REASON,
    SUMMARIZE,
    TRANSFORM,
    VALIDATE,
    ModelRouter,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "PEXELS_API_KEY": "test-pexels",
    "REPLICATE_API_TOKEN": "test-replicate",
    "FREESOUND_API_KEY": "test-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}


def _make_settings(**overrides):
    """Return a Settings instance with optional model overrides."""
    from src.config import Settings

    return Settings.model_validate({**VALID_ENV, **overrides})


def _make_router(**overrides) -> ModelRouter:
    """Return a ModelRouter built from default settings with optional overrides."""
    return ModelRouter(_make_settings(**overrides))


# ── DEFAULT_MODELS ────────────────────────────────────────────────────────────


class TestDefaultModels:
    def test_generate_default_is_sonnet(self):
        assert DEFAULT_MODELS[GENERATE] == "claude-sonnet-4-6"

    def test_validate_default_is_haiku(self):
        assert DEFAULT_MODELS[VALIDATE] == "claude-haiku-4-5-20251001"

    def test_summarize_default_is_haiku(self):
        assert DEFAULT_MODELS[SUMMARIZE] == "claude-haiku-4-5-20251001"

    def test_transform_default_is_haiku(self):
        assert DEFAULT_MODELS[TRANSFORM] == "claude-haiku-4-5-20251001"

    def test_reason_default_is_sonnet(self):
        assert DEFAULT_MODELS[REASON] == "claude-sonnet-4-6"

    def test_all_five_task_types_present(self):
        assert set(DEFAULT_MODELS.keys()) == {GENERATE, VALIDATE, SUMMARIZE, TRANSFORM, REASON}


# ── ModelRouter.model_for ─────────────────────────────────────────────────────


class TestModelFor:
    def test_generate_returns_claude_model_setting(self):
        """GENERATE task uses CLAUDE_MODEL from Settings."""
        router = _make_router(CLAUDE_MODEL="claude-opus-4-7")
        assert router.model_for(GENERATE) == "claude-opus-4-7"

    def test_validate_returns_model_validate_setting(self):
        """VALIDATE task uses MODEL_VALIDATE from Settings."""
        router = _make_router(MODEL_VALIDATE="claude-sonnet-4-6")
        assert router.model_for(VALIDATE) == "claude-sonnet-4-6"

    def test_summarize_returns_model_summarize_setting(self):
        """SUMMARIZE task uses MODEL_SUMMARIZE from Settings."""
        router = _make_router(MODEL_SUMMARIZE="claude-sonnet-4-6")
        assert router.model_for(SUMMARIZE) == "claude-sonnet-4-6"

    def test_transform_returns_model_transform_setting(self):
        """TRANSFORM task uses MODEL_TRANSFORM from Settings."""
        router = _make_router(MODEL_TRANSFORM="claude-sonnet-4-6")
        assert router.model_for(TRANSFORM) == "claude-sonnet-4-6"

    def test_reason_returns_model_reason_setting(self):
        """REASON task uses MODEL_REASON from Settings."""
        router = _make_router(MODEL_REASON="claude-haiku-4-5-20251001")
        assert router.model_for(REASON) == "claude-haiku-4-5-20251001"

    def test_unknown_task_falls_back_to_generate(self):
        """Unknown task type logs a warning and returns the GENERATE model."""
        router = _make_router()
        result = router.model_for("unknown_task_type")
        assert result == router.model_for(GENERATE)

    def test_default_generate_is_sonnet(self):
        """Default GENERATE model is claude-sonnet-4-6."""
        assert _make_router().model_for(GENERATE) == "claude-sonnet-4-6"

    def test_default_validate_is_haiku(self):
        """Default VALIDATE model is claude-haiku-4-5-20251001."""
        assert _make_router().model_for(VALIDATE) == "claude-haiku-4-5-20251001"

    def test_default_summarize_is_haiku(self):
        """Default SUMMARIZE model is claude-haiku-4-5-20251001."""
        assert _make_router().model_for(SUMMARIZE) == "claude-haiku-4-5-20251001"


# ── ModelRouter.log_cost ──────────────────────────────────────────────────────


class TestLogCost:
    def test_returns_cost_for_haiku(self):
        """Cost for Haiku is input*0.80/M + output*4.00/M USD."""
        router = _make_router()
        cost = router.log_cost(VALIDATE, "claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == round(0.80 + 4.00, 8)

    def test_returns_cost_for_sonnet(self):
        """Cost for Sonnet is input*3.00/M + output*15.00/M USD."""
        router = _make_router()
        cost = router.log_cost(GENERATE, "claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == round(3.00 + 15.00, 8)

    def test_unknown_model_returns_zero_cost(self):
        """Unknown model returns 0.0 cost and logs a warning."""
        router = _make_router()
        cost = router.log_cost(GENERATE, "unknown-model-xyz", 100, 50)
        assert cost == 0.0

    def test_cost_rounded_to_8_decimal_places(self):
        """Returned cost is rounded to 8 decimal places."""
        router = _make_router()
        cost = router.log_cost(VALIDATE, "claude-haiku-4-5-20251001", 100, 30)
        expected = round(100 * 0.80 / 1_000_000 + 30 * 4.00 / 1_000_000, 8)
        assert cost == expected

    def test_zero_tokens_returns_zero_cost(self):
        """Zero tokens produces zero cost."""
        router = _make_router()
        assert router.log_cost(VALIDATE, "claude-haiku-4-5-20251001", 0, 0) == 0.0

    def test_log_cost_emits_info_log(self, caplog):
        """log_cost writes an INFO log line containing task, model, and cost."""
        import logging

        router = _make_router()
        with caplog.at_level(logging.INFO, logger="src.utils.model_router"):
            router.log_cost(VALIDATE, "claude-haiku-4-5-20251001", 200, 50)
        assert any("task=validate" in r.message for r in caplog.records)
        assert any("claude-haiku-4-5-20251001" in r.message for r in caplog.records)


# ── PRICING table ─────────────────────────────────────────────────────────────


class TestPricingTable:
    def test_sonnet_pricing_present(self):
        assert "claude-sonnet-4-6" in PRICING

    def test_haiku_pricing_present(self):
        assert "claude-haiku-4-5-20251001" in PRICING

    def test_haiku_input_rate(self):
        in_rate, _ = PRICING["claude-haiku-4-5-20251001"]
        assert in_rate == pytest.approx(0.80 / 1_000_000)

    def test_haiku_output_rate(self):
        _, out_rate = PRICING["claude-haiku-4-5-20251001"]
        assert out_rate == pytest.approx(4.00 / 1_000_000)

    def test_sonnet_input_rate(self):
        in_rate, _ = PRICING["claude-sonnet-4-6"]
        assert in_rate == pytest.approx(3.00 / 1_000_000)

    def test_sonnet_output_rate(self):
        _, out_rate = PRICING["claude-sonnet-4-6"]
        assert out_rate == pytest.approx(15.00 / 1_000_000)
