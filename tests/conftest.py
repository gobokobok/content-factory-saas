"""Shared pytest fixtures — applied globally to prevent real external API calls."""

import os
from unittest.mock import MagicMock, patch

import pytest

# Routes are mounted when src.main is imported, so this must be set at import time.
# Production leaves it off (F3, F10); the suite keeps exercising the legacy routes.
os.environ.setdefault("LEGACY_ROUTES_ENABLED", "true")
# The Telegram webhook is unmounted by default (S6, D093); its tests mount it.
os.environ.setdefault("TELEGRAM_ROUTES_ENABLED", "true")

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
    # The default is off (Google only); the suite signs in with the password.
    "PASSWORD_LOGIN_ENABLED": "true",
    # The billing tests were written at double the provider cost; the shipped default is 1.0
    # (one credit = one cent) and has its own tests.
    "CREDIT_MARKUP": "2.0",
    "SESSION_SECRET_KEY": "test-secret-key",
    # Existing tests use short secrets; the validator's own tests set this explicitly.
    "AUTH_SECRET_MIN_LENGTH": "1",
    # The test client talks plain http; a Secure cookie would never be sent back.
    "COOKIE_ALLOW_INSECURE": "true",
    # The suite runs on the process-memory repositories (S6: refused outside local otherwise).
    "ALLOW_IN_MEMORY_STORE": "true",
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
def default_owner_principal(request, monkeypatch):
    """Give code that runs outside the auth middleware the owner as its principal.

    Production fails closed with no principal (every route needs the middleware's). Most
    tests mount a router on a bare app or call a route function directly and only care
    about route logic, so they act as the owner. Tests about accounts and isolation
    (test_auth*.py, test_p_auth*.py) keep the real, fail-closed behaviour.
    """
    name = request.fspath.basename
    if name.startswith("test_auth") or name.startswith("test_p_auth"):
        yield
        return
    from contextvars import ContextVar

    from cf_platform.core import accounts

    monkeypatch.setattr(accounts, "_principal_var", ContextVar("cf_principal", default=accounts.owner_principal()))
    yield


@pytest.fixture(autouse=True)
def bypass_auth_middleware(request):
    """Bypass the auth middleware for all tests except test_auth.py.

    test_auth.py tests the middleware and cookie behaviour directly.
    All other test files only care about route logic, not auth gating.
    """
    if "test_auth" in request.fspath.basename or request.fspath.basename.startswith("test_p_auth"):
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
