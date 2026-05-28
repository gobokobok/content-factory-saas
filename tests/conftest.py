"""Shared pytest fixtures — applied globally to prevent real external API calls."""

from unittest.mock import MagicMock, patch

import pytest


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
