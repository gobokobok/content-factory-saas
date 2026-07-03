"""Tests for P-UX1-S4: Studio becomes the default UI; legacy pipeline moves to /legacy.

Covers:
- GET / serves studio.html (not pipeline.html)
- GET /legacy serves pipeline.html unchanged
- GET /studio still serves studio.html (alias for bookmarked links)
"""

from fastapi.testclient import TestClient

from src.auth import AUTH_COOKIE_NAME
from src.config import Settings, get_settings
from src.main import app

_VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "correct-horse-battery",
    "SESSION_SECRET_KEY": "test-hmac-secret",
}


def _authenticated_client() -> tuple[TestClient, dict]:
    """Return a TestClient plus an auth cookie dict for gated routes."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
    client = TestClient(app, raise_server_exceptions=False)
    login_res = client.post("/auth/login", json={"password": "correct-horse-battery"})
    token = login_res.cookies[AUTH_COOKIE_NAME]
    return client, {AUTH_COOKIE_NAME: token}


def test_root_serves_studio_html():
    client, cookies = _authenticated_client()
    r = client.get("/", cookies=cookies)
    assert r.status_code == 200
    assert "Content Factory Studio" in r.text


def test_legacy_serves_pipeline_html():
    client, cookies = _authenticated_client()
    r = client.get("/legacy", cookies=cookies)
    assert r.status_code == 200
    assert "Content Factory Studio" not in r.text


def test_studio_alias_serves_studio_html():
    client, cookies = _authenticated_client()
    r = client.get("/studio", cookies=cookies)
    assert r.status_code == 200
    assert "Content Factory Studio" in r.text
