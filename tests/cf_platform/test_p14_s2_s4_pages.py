"""Static-page tests for the P14 UI: Generate in the edit-image dialog, spend readout, Settings page."""

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "src" / "static"
_STUDIO = (_STATIC / "studio-v2.html").read_text(encoding="utf-8")
_SETTINGS = (_STATIC / "settings.html").read_text(encoding="utf-8")
_PROJECT = (_STATIC / "project.html").read_text(encoding="utf-8")


def _function(page: str, name: str) -> str:
    """Return the source of one top-level JS function in a page."""
    match = re.search(rf"\n(?:async )?function {name}\(.*?\n}}\n", page, re.S)
    assert match, f"function {name} not found"
    return match.group(0)


def test_edit_image_dialog_has_a_prompt_field_and_a_generate_button():
    modal = _STUDIO[_STUDIO.index('<div class="modal-backdrop" id="pencil-modal"'):_STUDIO.index('<div class="info-panel" id="info-panel">')]
    assert 'id="pencil-ai-prompt"' in modal and "<textarea" in modal
    assert 'id="pencil-generate-btn"' in modal and 'onclick="generateSceneImage()"' in modal
    # re-acquire and upload are still there
    assert 'id="pencil-reacquire-btn"' in modal and 'id="pencil-dropzone"' in modal


def test_generate_posts_the_prompt_and_nothing_runs_automatically():
    src = _function(_STUDIO, "generateSceneImage")
    assert "/generate`" in src and "'POST'" in src and "JSON.stringify({ prompt })" in src
    assert "reloadStoryboard()" in src and "refreshAiSpend()" in src
    # Only the button's handler calls it: acquisition and storyboard rendering never do.
    assert _STUDIO.count("generateSceneImage(") == 2  # definition + the button


def test_ai_image_is_a_strategy_and_an_empty_ai_scene_offers_generate_in_its_row():
    assert "{ key: 'ai_image',    label: 'AI image' }" in _STUDIO
    thumb = _function(_STUDIO, "buildThumbCell")
    assert "effStrategy(scene) === 'ai_image'" in thumb and "openPencilModal" in thumb and ">Generate<" in thumb


def test_generated_images_do_not_count_as_stock_acquisition():
    plan = _function(_STUDIO, "acquirePlan")
    assert "'operator_upload', 'ai_generated'" in plan
    assert "operatorFilled" in plan


def test_edit_image_is_available_before_acquisition():
    row = _function(_STUDIO, "buildSceneRow")
    pencil = row[row.index('id="pencil-btn-'):][:260]
    assert "disabled" not in pencil


def test_spend_readout_shows_images_spent_and_cap():
    assert 'id="sb-stat-ai-wrap"' in _STUDIO
    src = _function(_STUDIO, "refreshAiSpend")
    assert "/ai-spend" in src and "spent_usd" in src and "cap_usd" in src and "cost_per_image_usd" in src


def test_settings_page_saves_provider_model_and_key_without_ever_showing_a_key():
    assert 'id="img-provider"' in _SETTINGS and 'id="img-model"' in _SETTINGS
    assert 'id="img-key"' in _SETTINGS and 'type="password"' in _SETTINGS
    assert "/platform/tenant/settings/image" in _SETTINGS and "'PUT'" in _SETTINGS
    assert "key_hint" in _SETTINGS and "SETTINGS_ENCRYPTION_KEY" in _SETTINGS
    assert "clear_key_for" in _SETTINGS


def test_project_settings_has_the_optional_ai_image_style():
    assert 'id="set-ai-style"' in _PROJECT
    assert "ai_image_style" in _PROJECT
    # keeps the rest of the config when saving
    assert "...(project.config || {})" in _PROJECT


def test_settings_is_linked_from_the_project_pages_and_served():
    assert 'href="/settings"' in (_STATIC / "projects.html").read_text(encoding="utf-8")
    assert 'href="/settings"' in _PROJECT
    from fastapi.testclient import TestClient

    from src.config import Settings, get_settings
    from src.main import app
    from tests.cf_platform.p13_helpers import VALID_ENV

    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    try:
        r = TestClient(app, raise_server_exceptions=False).get("/settings")
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code in (200, 302)  # 302 to /login when the cookie is missing
