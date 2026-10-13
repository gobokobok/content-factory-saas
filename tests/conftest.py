"""Shared pytest fixtures — applied globally to prevent real external API calls."""

import os
from unittest.mock import MagicMock, patch

import pytest

# The settings every app instance needs. CI provides only some of them as environment
# variables and has no .env.local, so a test that builds the app passed on a developer's
# machine (which has .env.local) and failed in CI (P-INT1 close). These are filled in
# for every test when missing, so the suite does not depend on where it runs.
_TEST_ENV_DEFAULTS = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key-id",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "ANTHROPIC_API_KEY": "test-key",
    "PEXELS_API_KEY": "test-key",
    "REPLICATE_API_TOKEN": "test-token",
    "FREESOUND_API_KEY": "test-key",
    "OPERATOR_PASSWORD": "test-password",
    "SESSION_SECRET_KEY": "test-secret-key",
}


@pytest.fixture(autouse=True)
def hermetic_settings_env(monkeypatch):
    """Give every test the settings the app requires, without overriding what the environment already sets."""
    for key, value in _TEST_ENV_DEFAULTS.items():
        if key not in os.environ:
            monkeypatch.setenv(key, value)
    yield


@pytest.fixture(autouse=True)
def reset_login_rate_limiter():
    """Clear the login rate limiter so failed attempts never leak between tests."""
    from src.routes.auth import _RATE_LIMITER

    _RATE_LIMITER.clear()
    yield


@pytest.fixture(autouse=True)
def bypass_auth_middleware(request):
    """Bypass the auth middleware for all tests except test_auth.py.

    test_auth.py tests the middleware and cookie behaviour directly.
    All other test files only care about route logic, not auth gating.
    """
    if "test_auth" in request.fspath.basename:
        yield
        return
    with patch("src.main.verify_cookie", return_value=True):
        yield


@pytest.fixture(autouse=True)
def mock_anthropic_for_summarizer():
    """Intercept Anthropic client instantiation in log_summarizer for all tests.

    Prevents real HTTP calls to api.anthropic.com from unit/integration tests.
    Per-test patches of src.log_summarizer.Anthropic take precedence over this fixture.
    """
    mock_content = MagicMock()
    mock_content.text = "✓ Storyboard: Complete\n○ Asset Manifest: Pending"
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_instance = MagicMock()
    mock_instance.messages.create.return_value = mock_response

    with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
        yield mock_instance
