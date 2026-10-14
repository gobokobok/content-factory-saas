"""Sprint P-LITE (LITE-S4) — the Creator pages at /create (D114, D117).

Covers:
- The page and its script are served, not cached, and sit behind the login
- The four steps, and what D114 leaves out of the Creator (no Metadata step, script
  generation, pace / style, Auto-advance, CapCut, voiceover upload, projects, Integrations)
- New video asks for format, language, master style and characters; Realistic is greyed
- The page talks to the Creator routes and reuses the Studio routes for everything else
- Paid and destructive actions ask first; long actions show progress and a Retry on failure
- The Studio page is untouched
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"

_VALID_ENV = {
    "ENVIRONMENT": "dev", "R2_ACCOUNT_ID": "x", "R2_ACCESS_KEY_ID": "x", "R2_SECRET_ACCESS_KEY": "x",
    "R2_BUCKET_NAME": "x", "ANTHROPIC_API_KEY": "x", "PEXELS_API_KEY": "x", "REPLICATE_API_TOKEN": "x",
    "FREESOUND_API_KEY": "x", "OPERATOR_PASSWORD": "x", "SESSION_SECRET_KEY": "x",
}


def _client() -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def page() -> str:
    return (_STATIC / "creator.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return (_STATIC / "ui" / "creator.js").read_text(encoding="utf-8")


class TestServing:
    def test_the_page_is_served_and_not_cached(self):
        r = _client().get("/create")
        assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
        assert '<script src="/ui/creator.js"></script>' in r.text

    def test_the_script_is_served(self):
        r = _client().get("/ui/creator.js")
        assert r.status_code == 200 and "window.Creator" in r.text

    @pytest.mark.parametrize("path", ["/create", "/ui/creator.js"])
    def test_it_requires_login(self, path):
        with patch("src.main.verify_cookie", return_value=False):
            r = _client().get(path, headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/login"

    def test_the_studio_page_is_still_the_studio(self):
        r = _client().get("/studio")
        assert r.status_code == 200 and "Content Factory Studio" in r.text and "creator.js" not in r.text


class TestScope:
    def test_four_steps_and_no_metadata(self, page, js):
        assert "const STEPS = ['script', 'voice', 'storyboard', 'render'];" in js
        assert [f'data-step="{i}"' in page for i in range(4)] == [True] * 4 and 'data-step="4"' not in page
        assert "metadata" not in page.lower() and "/workers/metadata" not in js

    @pytest.mark.parametrize("needle", [
        "CapCut", "capcut", "Auto-advance", "autoadv", "Integrations", "Defaults", "All projects",
        "Generate a script", "idea-to-script", "narration_pace", "Pace", "voice/upload", "Upload my own",
        "Sound effect", "sfx", "Save to library", "assets/from-run", "Cast",
    ])
    def test_what_the_creator_leaves_out_is_not_there(self, page, js, needle):
        assert needle not in page and needle not in js

    def test_the_left_panel_is_my_videos_and_log_out(self, page):
        left = page[page.index('id="left"'):page.index("RIGHT PANEL")]
        assert "My videos" in left and "New video" in left and "Log out" in left
        assert left.count('class="nav-btn"') == 3


class TestNewVideo:
    def test_it_asks_for_format_language_style_and_characters(self, page):
        form = page[page.index('id="s-new"'):page.index('id="s-run"')]
        for needle in ('id="new-title"', 'id="new-ar"', 'data-v="9:16"', 'data-v="16:9"', 'id="new-lang"',
                       'id="new-style"', 'id="new-chars"', "Add a character"):
            assert needle in form
        assert "cannot be changed later" in form

    def test_realistic_is_greyed_out(self, page):
        assert '<button data-v="realistic" disabled title="Coming soon">' in page

    def test_it_posts_to_the_creator_route_with_the_characters(self, js):
        create = js[js.index("async function createRun"):js.index("// ── One video: loading")]
        assert "'/platform/creator/runs'" in create and "characters" in create and "master_style" in create
        assert "Give every character a name and a description" in create


class TestTheRun:
    def test_it_reuses_the_studio_routes(self, js):
        for needle in ("/platform/creator/config", "/platform/workers/voice", "/platform/workers/storyboard",
                       "/platform/workers/render", "'/voice/status'", "'/storyboard/status'", "'/render/status'",
                       "'/images/plan'", "'/images/generate'", "'/images/status'", "/storyboard/continuity",
                       "/split`", "/merge`", "/generate`", "/upload`", "'/music'", "/settings`"):
            assert needle in js, needle

    def test_the_script_has_a_word_limit_and_is_paste_only(self, page, js):
        assert 'id="script-wc"' in page and "script_max_words" in js and "over the limit" in js

    def test_the_voice_is_one_dropdown_saved_on_the_run(self, page, js):
        assert 'id="voice-pick"' in page and "saveSettings({ voice" in js

    def test_images_show_the_estimate_before_anything_is_made(self, js):
        plan = js[js.index("async function planAssets"):js.index("async function watchImages")]
        assert plan.index("'/images/plan'") < plan.index("confirmBox(") < plan.index("'/images/generate'")
        assert "estimated_cost_usd" in plan and "cost_per_image_usd" in plan

    def test_recreating_the_storyboard_or_the_voice_asks_first(self, js):
        assert "Re-create the storyboard?" in js and "Your scene changes will be lost" in js
        assert "Re-generate the voiceover?" in js

    def test_next_waits_for_the_step(self, page, js):
        assert page.count('onclick="Creator.next()" disabled') == 3
        assert "$('#vo-next').disabled = !S.voice" in js and "!allAssets()" in js

    def test_long_actions_show_progress_and_failures_offer_retry(self, js):
        for fn in ("watchVoice", "watchStoryboard", "watchImages", "watchRender"):
            assert f"async function {fn}" in js
        assert js.count("failure('#job-") >= 8 and ">Retry</button>" in js
        assert "async function resumeJobs" in js

    def test_captions_default_to_none_and_the_video_can_be_downloaded(self, page, js):
        caps = page[page.index('id="cap-pick"'):page.index('id="music-pick"')]
        assert caps.index('value="none"') < caps.index('value="standard"') < caps.index('value="punch"')
        assert "Download video" in js
        # UI_GUIDELINES: a presigned URL is downloaded through a blob, never `<a href download>`.
        download = js[js.index("async function downloadVideo"):js.index("async function saveCaptions")]
        assert "URL.createObjectURL" in download and ".blob()" in download and 'download="' not in js

    def test_render_is_first_and_blue_and_download_is_outlined_beside_it(self, js, page):
        foot = js[js.index("const label = busy"):js.index("async function downloadVideo")]
        assert foot.index('class="btn accent" id="render-btn"') < foot.index('class="btn outline"')
        assert "'Re-render video' : 'Render video'" in foot
        assert ".btn.outline{" in page

    def test_format_look_and_language_are_fixed(self, page):
        settings = page[page.index('id="tab-settings"'):page.index('id="tab-help"')]
        assert "were chosen when the video was created" in settings
        assert "<select" not in settings and 'class="seg"' not in settings


class TestSafety:
    def test_server_text_is_escaped_before_it_reaches_the_page(self, js):
        """Names, descriptions and error text come from the user or the server: never raw into innerHTML."""
        for needle in ("esc(r.name", "esc(e.name)", "esc(e.description)", "esc(s.ai_prompt", "esc(title)", "esc(msg)"):
            assert needle in js, needle
        # The run's name is set as text, never as markup.
        assert "$('#run-title').textContent = S.run.name" in js

    def test_a_401_goes_to_the_login_page(self, js):
        assert "r.status === 401" in js and "location.href = '/login'" in js
