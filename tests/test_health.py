"""Tests for GET /health and startup ENV validation."""


import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.config import Settings
from src.main import app

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


def _client_with_settings(settings: Settings) -> TestClient:
    """Return a TestClient that injects the given settings via Depends override."""
    from src.config import get_settings
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app, raise_server_exceptions=False)
    return client


class TestHealthEndpoint:
    def test_returns_200_with_dev_environment(self):
        """Health check returns 200 and correct environment for dev."""
        settings = _make_settings(ENVIRONMENT="dev")
        client = _client_with_settings(settings)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "environment": "dev"}

    def test_returns_200_with_prod_environment(self):
        """Health check returns 200 and correct environment for prod."""
        settings = _make_settings(ENVIRONMENT="prod")
        client = _client_with_settings(settings)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "environment": "prod"}


class TestENVValidation:
    def test_valid_env_builds_settings(self):
        """All required vars present — Settings instantiates without error."""
        settings = _make_settings()
        assert settings.ENVIRONMENT == "dev"

    @pytest.mark.parametrize("missing_var", [
        "ENVIRONMENT",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "ANTHROPIC_API_KEY",
        "PEXELS_API_KEY",
        "REPLICATE_API_TOKEN",
        "FREESOUND_API_KEY",
        "OPERATOR_PASSWORD",
        "SESSION_SECRET_KEY",
    ])
    def test_missing_required_var_raises(self, missing_var: str, monkeypatch):
        """Each required ENV var, when absent, causes a ValidationError.

        Uses monkeypatch to clear the real environment so shell vars don't mask the missing key.
        """
        for key in VALID_ENV:
            monkeypatch.delenv(key, raising=False)

        env = {k: v for k, v in VALID_ENV.items() if k != missing_var}
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **env)

    def test_invalid_environment_value_raises(self):
        """ENVIRONMENT must be 'dev' or 'prod' — other values raise ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(ENVIRONMENT="staging")

    def test_invalid_log_level_raises(self):
        """LOG_LEVEL must be a valid Python logging level."""
        with pytest.raises(ValidationError):
            _make_settings(LOG_LEVEL="VERBOSE")

    def test_defaults_applied(self):
        """Optional vars default correctly when not provided."""
        settings = _make_settings()
        assert settings.LOG_LEVEL == "INFO"
        assert settings.CLAUDE_MODEL == "claude-sonnet-4-6"
        assert settings.PEXELS_PER_PAGE == 5
        assert settings.REPLICATE_FLUX_MODEL == "black-forest-labs/flux-schnell"
        assert settings.REPLICATE_POLL_INTERVAL_SECONDS == 3
        assert settings.REPLICATE_MAX_POLL_ATTEMPTS == 60
