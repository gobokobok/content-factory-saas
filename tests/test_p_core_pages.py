"""Sprint P-CORE — the Studio's features as Super screens of the new design (D118).

The page code is checked as text (the suite has no browser): that each screen exists, which routes it
calls, and that the old pages are only redirects now. What the server allows is covered by the
P-AUTH tests; these pin what the screens ask for.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app

_UI = Path(__file__).resolve().parents[1] / "src" / "static" / "ui"
_STATIC = _UI.parent


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture(scope="module")
def core() -> str:
    return (_UI / "core.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def run() -> str:
    return (_UI / "core-run.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def host() -> str:
    return (_UI / "creator.js").read_text(encoding="utf-8")


class TestOldAddressesRedirect:
    def test_the_studio_and_root_serve_the_hop_page(self):
        for path in ("/", "/studio"):
            r = _client().get(path)
            assert r.status_code == 200 and "/create" in r.text and "Content Factory Studio" not in r.text

    def test_the_hop_page_carries_a_run_bookmark_and_maps_retired_stages(self):
        page = (_STATIC / "go.html").read_text()
        assert "#run\\/" in page and "location.replace('/create#run/'" in page
        for old, new in (("upload", "script"), ("transcript", "script"), ("video", "render")):
            assert f"{old}: '{new}'" in page

    @pytest.mark.parametrize(
        "url,target",
        [
            ("/project?id=abc", "/create#project/abc"),
            ("/project?id=abc&tab=ideas", "/create#project/abc/ideas"),
            ("/project?id=abc&tab=nonsense", "/create#project/abc"),
            ("/project", "/create#projects"),
            ("/library?kind=ai", "/create#library/ai"),
            ("/library?kind=bogus", "/create#library/videos"),
            ("/settings", "/create#settings/integrations"),
            ("/settings?tab=defaults", "/create#settings/defaults"),
        ],
    )
    def test_each_old_page_address_goes_to_its_screen(self, url, target):
        r = _client().get(url)
        assert r.status_code == 302 and r.headers["location"] == target

    def test_the_old_page_files_are_gone(self):
        for name in ("projects.html", "project.html", "library.html", "settings.html", "studio-v2.html", "studio.html"):
            assert not (_STATIC / name).exists(), name
        for name in ("shell.js", "shell.css", "app.js", "app.css"):
            assert not (_UI / name).exists(), name


class TestTheHost:
    def test_a_basic_session_gets_only_the_libraries(self, host, core):
        assert "/ui/core.js" in host and "loadCore(me.effective_type !== 'super')" in host
        assert "BASIC ? name === 'library'" in core
        # core-run.js loads for Basic too, but mounts only script generation and narration.
        assert "window.CoreRun.init(A, window.Core, BASIC)" in core
        run = (Path(__file__).resolve().parents[1] / "src" / "static" / "ui" / "core-run.js").read_text()
        assert "if (BASIC) return;\n\n    // Storyboard toolbar." in run

    def test_the_host_hands_unknown_routes_to_core(self, host):
        assert "window.Core.handles(name)" in host and "window.Core.route(name, id, step, more)" in host

    def test_an_uploaded_video_is_not_replaced_without_asking(self, host):
        assert "confirm_overwrite: uploaded" in host and "Replace the uploaded video?" in host

    def test_static_assets_are_revalidated(self):
        src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text()
        assert 'path.startswith("/ui/")' in src and '"Cache-Control"] = "no-cache"' in src


class TestTheScriptLockHasOneOwner:
    """Typing in a locked script froze the page: two painters disagreed about readOnly (2026-10-21)."""

    def test_the_super_script_painter_follows_the_hosts_lock(self, host, run):
        # creator.js decides the lock and shares it; core-run.js must not unlock the field again.
        assert "scriptWords, scriptOk, scriptLocked," in host
        assert "const locked = A.scriptLocked();" in run
        assert "ta.readOnly = locked ||" in run
        assert "src === 'generate' && !locked" in run

    def test_a_locked_script_says_why_and_offers_the_way_out(self, host):
        page = (_STATIC / "creator.html").read_text(encoding="utf-8")
        assert 'id="script-lock"' in page and "Creator.startFromThis()" in page
        assert "$('#script-lock')" in host and "classList.toggle('hidden', !locked)" in host


class TestScreens:
    def test_every_route_of_the_old_shell_is_a_screen(self, core):
        for name in ("'projects'", "'project'", "'library'", "'settings'"):
            assert name in core
        for tab in ("'ideas'", "'runs'", "'settings'", "'defaults'", "'integrations'"):
            assert tab in core

    def test_the_five_libraries(self, core):
        for kind in ("videos", "audio", "footage", "ai", "music"):
            assert f"{kind}: '" in core
        assert "/platform/library/${kind}" in core and "URL.createObjectURL" in core

    def test_projects_ideas_and_assets_use_the_projects_routes(self, core):
        for needle in ("'/platform/projects'", "/shortlist", "/assets", "'/platform/tenant/defaults'",
                       "'/platform/tenant/blocks'", "/platform/tenant/integrations/", "/platform/tenant/settings/image",
                       "channel_identity", "ai_image_style", "run_defaults"):
            assert needle in core, needle

    def test_a_key_is_never_shown_only_a_hint(self, core):
        assert 'type="password"' in core and "key_hint" in core and "never shown again" in core

    def test_starting_a_video_from_ideas_goes_through_the_new_video_screen(self, core):
        assert "#new/${encodeURIComponent(C.project.project_id)}" in core and "itemIds" in core

    def test_the_menu_is_the_beta_panel(self):
        """Projects, Libraries (Videos, Images, AI assets, BG music) and Settings, as section headers over one flowing list."""
        menu = (_UI / "super-menu.js").read_text()
        for needle in ("#projects", "'#library/' + k", "#settings/integrations", "#settings/defaults", "All projects",
                       "'Videos'", "'Images'", "'BG music'", "Projects</div>", "Libraries</div>", "Settings</div>"):
            assert needle in menu, needle
        assert "Audio" not in menu and "Footage" not in menu and "New video" not in menu
        assert "if (basic) { container.innerHTML = libraries" in menu   # Basic: Libraries only

    def test_a_project_lists_its_pages_under_all_projects(self, core):
        for page in ("Overview", "Ideas", "Runs", "Settings"):
            assert f"'{page}'" in core
        assert 'id="nav-project"' not in core and "nav-project" in core

    def test_everyone_starts_at_runs(self, host):
        assert "go('#projects')" not in host


class TestRunControls:
    def test_the_metadata_step_is_added_for_super_only(self, run, host):
        assert "A.STEPS.push('metadata')" in run and "'metadata'" not in host.split("const STEP_NAMES")[0].split("const STEPS")[1]
        assert "/platform/workers/metadata" in run

    def test_script_has_three_sources(self, run):
        for needle in ("Generate script with AI", "data-s=\"generate\"", "data-s=\"upload\"", "/platform/blocks/idea-to-script",
                       "target_duration_seconds", "/voice-source", "/voice/upload", "/transcript", "dry_run"):
            assert needle in run, needle

    def test_replacing_an_uploaded_voiceover_asks_first(self, run):
        assert "Replace the uploaded voiceover?" in run and "confirm_discard" in run

    def test_voice_has_pace_and_style(self, run):
        assert "narration_pace" in run and "narration_style" in run

    def test_realistic_storyboard_controls(self, run):
        for needle in ("/platform/workers/acquisition", "only_missing", "/reacquire", "primary_stk", "asset_strategy",
                       "/storyboard/boundaries", "sfx_enabled", "/platform/studio/sfx-library"):
            assert needle in run, needle

    def test_re_acquiring_everything_asks_first(self, run):
        assert "Acquire every scene again?" in run

    def test_capcut_export_and_upload(self, run):
        assert "/export/capcut" in run and "/output/upload" in run and "confirm_overwrite=true" in run
        assert "format_track" in run and "caption_style" in run and "music_enabled" in run

    def test_look_language_cast_and_library_save(self, run):
        for needle in ("/visuals", "confirm_reset", "/language", "cast_mode", "AI Director", "Custom", "/platform/creator/assets", "/assets/from-run"):
            assert needle in run, needle

    def test_changing_the_look_asks_before_discarding_the_storyboard(self, run):
        assert "needs_confirmation" in run and "Change and discard" in run

    def test_auto_advance_stops_where_money_is_asked_for(self, run):
        assert "image generation always asks first" in run and "A.planAssets()" in run

    def test_new_video_has_project_and_look(self, run):
        for needle in ("new-project", "'/platform/creator/runs'", "project_id", "look", "item_ids", "/platform/projects/"):
            assert needle in run, needle


class TestServerSide:
    def test_the_hidden_personal_project_is_not_in_the_project_list(self):
        from tests.cf_platform.p12_helpers import p12_env

        with p12_env() as env:
            from datetime import UTC, datetime

            from cf_platform.core.projects import Project

            now = datetime.now(UTC)
            import asyncio

            asyncio.new_event_loop().run_until_complete(env.projects.save(Project(
                project_id="default-operator-x", tenant_id="operator", name="Hidden", config={"hidden": True},
                created_at=now, updated_at=now)))
            names = [p["name"] for p in env.client.get("/platform/projects").json()]
            assert "Hidden" not in names
