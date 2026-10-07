"""Tests for P-UX3-S3: the clickable redesign prototype is served at /prototype.

Covers:
- GET /prototype/ serves the prototype page and its three static files
- The prototype is plain HTML/CSS/JS with no backend calls
- An unauthenticated browser request is redirected to /login
"""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app

_PROTOTYPE = Path(__file__).resolve().parent.parent / "docs" / "ux" / "prototype"

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


def _client() -> TestClient:
    """Return a TestClient with valid settings (auth is bypassed by conftest)."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
    return TestClient(app, raise_server_exceptions=False)


def test_prototype_page_is_served():
    r = _client().get("/prototype/")
    assert r.status_code == 200
    assert "<title>Prototype — Content Factory</title>" in r.text


def test_prototype_static_files_are_served():
    for name in ("styles.css", "data.js", "app.js"):
        r = _client().get(f"/prototype/{name}")
        assert r.status_code == 200, name
        assert r.text == (_PROTOTYPE / name).read_text(encoding="utf-8")


def test_prototype_missing_file_is_404():
    assert _client().get("/prototype/nope.js").status_code == 404


def test_prototype_makes_no_backend_calls():
    for name in ("app.js", "data.js", "index.html"):
        source = (_PROTOTYPE / name).read_text(encoding="utf-8")
        assert "fetch(" not in source and "XMLHttpRequest" not in source, name
        assert "/platform/" not in source, name


def test_prototype_requires_login():
    with patch("src.main.verify_cookie", return_value=False):
        r = _client().get("/prototype/", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/login"
