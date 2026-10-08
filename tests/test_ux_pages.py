"""Tests for the UI/UX build's pages: the shared shell, the project / library / settings pages
and the one-pipeline Studio.

Covers:
- Every page is served, not cached, and sits behind the login
- The shared shell (left panel + breadcrumbs) is on every page and links to every area
- The panel folds, remembers the choice, and a run starts folded without remembering it
- Studio: one five-step pipeline, the Script step chooses the source, run settings are a drawer,
  the voice source can be switched, the storyboard is a list of cards with inline on-screen text
- Project pages: four views, a run without an idea, idea editing, tenant-default inheritance
- Libraries read the tenant-wide API and download through a blob; Settings has Integrations and Defaults
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
_UI = _STATIC / "ui"

_VALID_ENV = {
    "ENVIRONMENT": "dev", "R2_ACCOUNT_ID": "x", "R2_ACCESS_KEY_ID": "x", "R2_SECRET_ACCESS_KEY": "x",
    "R2_BUCKET_NAME": "x", "ANTHROPIC_API_KEY": "x", "PEXELS_API_KEY": "x", "REPLICATE_API_TOKEN": "x",
    "FREESOUND_API_KEY": "x", "OPERATOR_PASSWORD": "x", "SESSION_SECRET_KEY": "x",
}


def _client() -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
    return TestClient(app, raise_server_exceptions=False)


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


_PAGES = ["/", "/project?id=default", "/library?kind=videos", "/settings?tab=integrations", "/settings?tab=defaults", "/studio"]


class TestServing:
    @pytest.mark.parametrize("path", _PAGES)
    def test_page_is_served_and_not_cached(self, path):
        r = _client().get(path)
        assert r.status_code == 200
        assert "no-store" in r.headers["cache-control"]
        assert 'id="cf-nav"' in r.text and 'id="cf-crumbs"' in r.text

    @pytest.mark.parametrize("asset", ["shell.js", "shell.css", "app.js", "app.css"])
    def test_shared_assets_are_served(self, asset):
        r = _client().get(f"/ui/{asset}")
        assert r.status_code == 200 and len(r.text) > 100

    @pytest.mark.parametrize("path", _PAGES + ["/ui/shell.js"])
    def test_everything_requires_login(self, path):
        with patch("src.main.verify_cookie", return_value=False):
            r = _client().get(path, headers={"accept": "text/html"}, follow_redirects=False)
            assert r.status_code == 302 and r.headers["location"] == "/login"

    @pytest.mark.parametrize("name", ["projects.html", "project.html", "library.html", "settings.html", "studio-v2.html"])
    def test_every_page_loads_the_shell(self, name):
        page = _read(name)
        assert "/ui/shell.js" in page and "/ui/shell.css" in page
        assert "CFShell.mount(" in page


class TestShell:
    def test_panel_lists_projects_libraries_and_settings(self):
        js = (_UI / "shell.js").read_text(encoding="utf-8")
        for needle in ("Projects", "Libraries", "Settings", "/library?kind=${k}", "['videos', 'Videos']", "['audio', 'Audio']",
                       "['footage', 'Footage']", "['ai', 'AI generations']", "['music', 'Music & SFX']",
                       "/settings?tab=integrations", "/settings?tab=defaults", "'Overview'", "'Ideas'", "'Runs'"):
            assert needle in js, needle

    def test_folding_is_remembered_but_a_run_starts_folded_and_does_not_remember(self):
        js = (_UI / "shell.js").read_text(encoding="utf-8")
        assert "cf_nav_fold" in js and "toggleFold" in js
        assert "foldDefault === 'folded'" in js and "override = next" in js  # a run's choice is not stored

    def test_phone_width_uses_a_drawer(self):
        css = (_UI / "shell.css").read_text(encoding="utf-8")
        assert "max-width: 760px" in css and "translateX(-100%)" in css and "cf-nav-open" in css

    def test_breadcrumbs_are_not_a_bar_of_their_own(self):
        css = (_UI / "shell.css").read_text(encoding="utf-8")
        crumbs = css[css.index(".cf-crumbs {"): css.index("}", css.index(".cf-crumbs {"))]
        assert "background" not in crumbs and "border" not in crumbs


class TestStudio:
    def test_one_pipeline_for_every_run(self):
        page = _read("studio-v2.html")
        assert "const STAGES = ['script', 'voice', 'storyboard', 'render', 'metadata'];" in page
        assert "UPLOADED_STAGES" not in page and "GENERATED_STAGES" not in page
        assert "const SUB_STAGES = { upload: 'script', transcript: 'script', settings: 'script' };" in page

    def test_steps_are_arrow_shaped_with_one_status_dot(self):
        page = _read("studio-v2.html")
        assert "clip-path: polygon(" in page and ".step-done::before" in page and ".step-fail::before" in page
        assert 'class="steps" id="stage-track"' in page

    def test_script_step_chooses_the_source(self):
        page = _read("studio-v2.html")
        for needle in ("chooseScriptSource('${k}')", "card('generate'", "card('paste'", "card('upload', 'From a voiceover'", "restartScriptSource", "putVoiceSource",
                       "/voice-source", "switchToGeneratedVoice", "Generate a voice from the script instead"):
            assert needle in page, needle

    def test_switching_to_a_generated_voice_asks_first(self):
        page = _read("studio-v2.html")
        put = page[page.index("async function putVoiceSource"): page.index("async function switchToGeneratedVoice")]
        assert "needs_confirmation" in put and "confirm(" in put and "confirm_discard: true" not in put
        assert "putVoiceSource(source, true)" in put

    def test_run_settings_is_a_drawer_not_a_step(self):
        page = _read("studio-v2.html")
        assert 'id="settings-drawer"' in page and "openSettingsDrawer()" in page and ">Run settings</button>" in page
        assert "settings: 'Settings'" not in page  # no longer a step label
        assert 'id="run-language"' in page and "onRunLanguageChange" in page

    def test_an_uploaded_alignment_is_not_a_generated_voice(self):
        page = _read("studio-v2.html")
        assert "startsWith('uploaded')" in page

    def test_storyboard_is_a_list_of_cards_with_inline_on_screen_text(self):
        page = _read("studio-v2.html")
        row = page[page.index("function buildSceneRow"): page.index("/** Save the on-screen text field")]
        assert 'class="sc-card' in row and 'class="sc-ost' in row and 'onchange="onOstChange' in row
        assert "sc-pencil" in row and "openPencilModal" in row  # the pencil sits on the asset
        assert "mergeScene(" in row and "id=\"sfx-${sceneId}\"" in row
        change = page[page.index("async function onOstChange"): page.index("// Inline editing — on-screen text (")]
        assert "clear_on_screen_text: true" in change  # emptying the field removes the text

    def test_both_storyboard_views_are_named(self):
        page = _read("studio-v2.html")
        assert ">Storyboard</button>" in page and ">Script</button>" in page

    def test_new_runs_start_from_tenant_then_project_then_the_runs_format(self):
        page = _read("studio-v2.html")
        seed = page[page.index("const td = state.tenantDefaults"): page.index("subject: state.runContext?.idea_title")]
        assert seed.index("td.format") < seed.index("run_defaults") < seed.index("state.runFormat")


class TestProjectPages:
    def test_four_views_selected_by_tab(self):
        page = _read("project.html")
        for view in ("viewOverview", "viewIdeas", "viewRuns", "viewSettings"):
            assert view in page
        assert "['overview', 'ideas', 'runs', 'settings']" in page

    def test_a_run_can_start_without_an_idea(self):
        page = _read("project.html")
        assert "dlgNewRun([])" in page and "item_ids: window._newRunIds" in page
        assert "aspect_ratio: $('nr-format').value" in page and "language: $('nr-lang').value" in page

    def test_ideas_can_be_edited(self):
        page = _read("project.html")
        assert "jsonOpts('PATCH', body)" in page and "dlgIdea(" in page

    def test_project_settings_show_where_a_value_comes_from(self):
        page = _read("project.html")
        assert "Inherited from Settings → Defaults" in page and "Overridden for this project" in page and "Reset to Defaults" in page

    def test_only_overrides_are_stored(self):
        page = _read("project.html")
        assert "reset ? delete config.language" in page and "delete rd.aspect_ratio" in page

    def test_run_rows_show_progress_not_a_bare_status(self):
        page = _read("project.html")
        assert "steps_done" in page and "current_step" in page and "Needs attention" in page

    def test_new_project_asks_only_four_things(self):
        page = _read("projects.html")
        for field in ('id="np-name"', 'id="np-niche"', 'id="np-lang"', 'id="np-format"'):
            assert field in page
        assert "if ($('np-lang').value !== tenantDefaults.language)" in page  # only a difference is stored


class TestLibraryAndSettingsPages:
    def test_library_reads_the_tenant_api_and_downloads_through_a_blob(self):
        page = _read("library.html")
        assert "/platform/library/${KIND}" in page and "URL.createObjectURL" in page
        for kind in ("videos", "audio", "footage", "ai", "music"):
            assert f"{kind}:" in page
        assert "asset_id" in page and "project_name" in page and "run_name" in page

    def test_settings_has_integrations_and_defaults(self):
        page = _read("settings.html")
        assert "/platform/tenant/integrations" in page and "/platform/tenant/defaults" in page
        assert "Railway variable" in page and 'type="password"' in page

    def test_a_key_is_never_rendered_back(self):
        page = _read("settings.html")
        assert "key_hint" in page and ".api_key" not in page
