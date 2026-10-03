"""Tests for P12-S2: Studio project landing + server-side run list.

Covers:
- GET / serves the project list page (not Studio)
- GET /project serves the project page, with empty states for no ideas and no runs
- GET /studio still serves the Studio pipeline (bookmarked links keep working)
- The project and shortlist views are separate static files, not parts of studio-v2.html (D092)
- Studio no longer reads its run list from localStorage.studio_runs
- An unauthenticated browser request to the new pages is redirected to /login
"""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"

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


def test_root_serves_project_list():
    r = _client().get("/")
    assert r.status_code == 200
    assert "<title>Projects — Content Factory</title>" in r.text
    assert "+ New project" in r.text
    assert "No projects yet" in r.text  # empty state is in the page


def test_project_page_serves_with_empty_states():
    r = _client().get("/project", params={"id": "default"})
    assert r.status_code == 200
    assert "Shortlist" in r.text and "Runs" in r.text
    assert "No runs yet" in r.text
    assert "No ideas yet" in r.text
    assert "Create video" in r.text


def test_studio_route_still_serves_pipeline():
    r = _client().get("/studio")
    assert r.status_code == 200
    assert "Content Factory Studio" in r.text
    assert 'id="ws-project-link"' in r.text  # header link back to the project


def test_pages_are_not_cached():
    for path in ("/", "/project", "/studio"):
        assert "no-store" in _client().get(path).headers["cache-control"]


def test_project_views_are_separate_static_files():
    """D092: project + shortlist UI lives in its own pages, not inside studio-v2.html."""
    studio = (_STATIC / "studio-v2.html").read_text()
    assert (_STATIC / "projects.html").exists() and (_STATIC / "project.html").exists()
    assert "add-idea-form" not in studio
    assert "new-project-form" not in studio


def test_studio_run_list_no_longer_reads_local_storage():
    """The run list comes from the server; localStorage.studio_runs is not read or written by Studio."""
    studio = (_STATIC / "studio-v2.html").read_text()
    assert "getItem('studio_runs')" not in studio
    assert "setItem('studio_runs'" not in studio
    assert "/platform/projects/" in studio and "/runs`" in studio


def test_project_page_reads_runs_from_the_server():
    page = (_STATIC / "project.html").read_text()
    assert "${BASE}/runs" in page
    assert "localStorage" not in page


def test_local_history_is_imported_not_dropped():
    """The project list imports this browser's old run history instead of discarding it."""
    page = (_STATIC / "projects.html").read_text()
    assert "/runs/import" in page
    assert "removeItem('studio_runs')" not in page


def test_old_root_run_bookmark_is_forwarded_to_studio():
    """A pre-P12 `/#run/<id>` bookmark is forwarded to /studio by the project list page."""
    page = (_STATIC / "projects.html").read_text()
    assert "location.replace('/studio' + location.hash)" in page
    assert "addEventListener('hashchange', forwardRunBookmark)" in page


def test_new_pages_require_login():
    with patch("src.main.verify_cookie", return_value=False):
        for path in ("/", "/project?id=default"):
            r = _client().get(path, headers={"accept": "text/html"}, follow_redirects=False)
            assert r.status_code == 302 and r.headers["location"] == "/login"
