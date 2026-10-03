"""Tests for P13-S3 / P13-S4 (UI): the Storyboard stage in studio-v2.html.

Static-page tests — they pin the new controls and the routes they call:
- Asset dropdown with the three strategies, wired to the scene PATCH
- split (click a word → "Split here") and merge ("Merge with next") controls
- merge confirmation when on-screen text or SFX would be dropped
- the confirm gate on the acquire button, and only-missing acquisition
- row upload control for Upload scenes, "needs asset" marking
- Table / Script toggle and the boundaries call with a dry-run preview
- the JS vocabulary matches src.models.ASSET_STRATEGIES
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app
from src.models import ASSET_STRATEGIES
from tests.cf_platform.p13_helpers import VALID_ENV

_PAGE = (Path(__file__).resolve().parents[2] / "src" / "static" / "studio-v2.html").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """Return the source of one top-level JS function in the page."""
    match = re.search(rf"\n(?:async )?function {name}\(.*?\n}}\n", _PAGE, re.S)
    assert match, f"function {name} not found in studio-v2.html"
    return match.group(0)


def test_studio_serves_the_storyboard_controls():
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    try:
        r = TestClient(app, raise_server_exceptions=False).get("/studio")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert r.status_code == 200
    assert "Confirm storyboard &amp; acquire" in r.text
    assert 'id="split-pop"' in r.text


class TestAssetColumn:
    def test_vocabulary_matches_the_backend(self):
        block = re.search(r"const ASSET_STRATEGIES = \[(.*?)\];", _PAGE, re.S).group(1)
        assert tuple(re.findall(r"key: '(\w+)'", block)) == ASSET_STRATEGIES
        assert re.findall(r"label: '([^']+)'", block) == ["Stock image", "Stock video", "Upload"]

    def test_asset_column_replaces_the_visual_badge(self):
        render = _function("renderStoryboard")
        assert "<th>Asset</th>" in render and "<th>Visual</th>" not in render

    def test_dropdown_is_a_small_cf_select_showing_the_effective_strategy(self):
        row = _function("buildSceneRow")
        assert 'class="cf-select cf-select--sm cf-select--asset" id="asset-${sceneId}"' in row
        assert "onAssetChange('${sceneId}')" in row
        assert "effStrategy(s)" in row
        assert "s.effective_asset_strategy" in _function("effStrategy")

    def test_change_patches_the_scene_and_rerenders(self):
        change = _function("onAssetChange")
        assert "patchScene(sceneId, { asset_strategy: el.value })" in change
        assert "reloadStoryboard()" in change
        assert "/storyboard/scenes/${sceneId}" in _function("patchScene")

    def test_motion_cell_still_follows_the_scene_kind(self):
        row = _function("buildSceneRow")
        assert "Motion effects apply to still images only" in row


class TestSplitAndMerge:
    def test_words_are_split_targets_except_the_first(self):
        row = _function("buildSceneRow")
        assert 'class="vo-word"' in row
        assert "openSplitPop(event, '${sceneId}', ${s.start_word + j})" in row
        assert "j === 0" in row  # a scene cannot be split before its first word

    def test_split_here_calls_the_split_route(self):
        assert ">Split here</button>" in _PAGE
        assert "`/scenes/${sceneId}/split`, 'POST', { at_word: atWord }" in _function("confirmSplit")

    def test_merge_button_on_every_row_but_the_last(self):
        row = _function("buildSceneRow")
        assert 'title="Merge with next scene"' in row
        assert "(nextScene && canEditBoundaries)" in row

    def test_merge_asks_before_dropping_text_or_sfx(self):
        merge = _function("mergeScene")
        assert "next.on_screen_text" in merge and "hasSfx(next)" in merge
        assert "confirm(" in merge
        assert merge.index("confirm(") < merge.index("/merge`, 'POST'")

    def test_both_rerender_from_the_response(self):
        for name in ("confirmSplit", "mergeScene"):
            assert "applyStoryboardResponse(data)" in _function(name)
        assert "renderStoryboard(data)" in _function("applyStoryboardResponse")


class TestConfirmGate:
    def test_three_button_states(self):
        plan = _function("acquirePlan")
        assert "Confirm storyboard & acquire →" in plan
        assert "missing scene" in plan
        assert "Re-acquire All" in plan
        assert "Acquire Assets" not in _PAGE

    def test_acquisition_sends_only_missing(self):
        acquire = _function("acquireAssets")
        assert "'/platform/workers/acquisition'" in acquire
        assert "only_missing: plan.onlyMissing" in acquire

    def test_nothing_is_acquired_without_the_button_or_auto_advance(self):
        # The only calls are the button's onclick and the Auto Advance hand-off.
        calls = re.findall(r".*[^n ]acquireAssets.*", _PAGE)
        calls = [c.strip() for c in calls if "function acquireAssets" not in c]
        assert len(calls) == 2
        assert any('onclick="acquireAssets()"' in c for c in calls)
        assert any("state.autoConfirm" in c and "setTimeout(acquireAssets" in c for c in calls)

    def test_scenes_needing_an_asset_are_marked(self):
        thumb = _function("buildThumbCell")
        assert "needs asset" in thumb and "thumb-needs" in thumb
        assert 'id="sb-stat-need"' in _function("renderStoryboard")

    def test_upload_scene_has_an_upload_control_in_its_row(self):
        thumb = _function("buildThumbCell")
        assert "effStrategy(scene) === 'upload'" in thumb
        assert 'class="row-upload"' in thumb and 'type="file"' in thumb
        assert "/scenes/${sceneId}/upload" in _function("uploadSceneFile")


class TestScriptView:
    def test_table_script_toggle(self):
        render = _function("renderStoryboard")
        assert "setSbView('table')" in render and "setSbView('script')" in render

    def test_one_paragraph_per_scene_separated_by_one_blank_line(self):
        assert r"join('\n\n')" in _function("scriptViewText")

    def test_apply_is_disabled_when_words_change(self):
        check = _function("onScriptViewInput")
        assert "btn.disabled = wordsChanged || unchanged" in check
        assert "Change the text in the Script stage" in check and "re-voicing" in check

    def test_apply_previews_with_a_dry_run_before_writing(self):
        apply = _function("applyScriptView")
        assert "'/boundaries', 'PUT', { ...body, dry_run: true }" in apply
        assert "preview.summary" in apply and "confirm(" in apply
        assert apply.index("dry_run: true") < apply.index("confirm(") < apply.rindex("'/boundaries', 'PUT', body")
