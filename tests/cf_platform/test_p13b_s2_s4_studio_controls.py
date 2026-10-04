"""Static-page tests for the CapCut controls in the Studio Render stage (P13b-S2, P13b-S4)."""

import re
from pathlib import Path

_PAGE = (Path(__file__).resolve().parents[2] / "src" / "static" / "studio-v2.html").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """Return the source of one top-level JS function in the page."""
    match = re.search(rf"\n(?:async )?function {name}\(.*?\n}}\n", _PAGE, re.S)
    assert match, f"function {name} not found in studio-v2.html"
    return match.group(0)


def test_download_for_capcut_sits_next_to_render_and_says_how_the_path_works():
    cta = _PAGE[_PAGE.index('id="render-cta"'):_PAGE.index('id="pane-metadata"') - 200]
    assert 'id="render-btn"' in cta and 'id="capcut-export-btn"' in cta
    assert "Download for CapCut" in cta
    assert "rendered in CapCut" in _PAGE or "render in CapCut" in _PAGE
    assert "upload the video here" in _PAGE


def test_export_button_opens_under_the_same_condition_as_render():
    update = _PAGE[_PAGE.index("const renderBtn = document.getElementById('render-btn')"):][:700]
    assert "acquired > 0" in update
    assert "capcut-export-btn" in update and "capcut-upload-btn" in update


def test_export_calls_the_route_and_uses_the_blob_download_pattern():
    src = _function("downloadCapcutExport")
    assert "/export/capcut?" in src
    for param in ("format_track", "captions", "caption_style", "music_enabled"):
        assert param in src
    assert "URL.createObjectURL(blob)" in src and "a.download" in src
    assert "r.ok" in src and "err.detail" in src          # a 409 shows its message
    assert 'href="' not in src and "download>" not in src  # never a cross-origin <a download>


def test_upload_control_posts_the_file_and_asks_before_replacing_a_render():
    src = _function("uploadCapcutVideo")
    assert "/output/upload" in src and "FormData" in src and "'POST'" in src
    assert "r.status === 409" in src and "confirm(" in src
    assert "confirm_overwrite=true" in src
    assert 'accept="video/mp4,.mp4"' in _PAGE and 'id="capcut-upload-input"' in _PAGE
    assert "Upload video from CapCut" in _PAGE


def test_after_an_upload_the_stage_shows_the_video_with_its_source_like_a_render():
    src = _function("uploadCapcutVideo")
    assert "state.stageStatus.render = 'done'" in src and "renderVideoResult(data)" in src
    assert "renderStageTrack()" in src
    assert "Source:" in _function("renderVideoResult") and "videoSourceLabel" in _function("renderVideoResult")
    assert "CapCut upload" in _function("videoSourceLabel") and "FFmpeg render" in _function("videoSourceLabel")


def test_rendering_over_a_capcut_video_asks_first_and_tells_the_server():
    src = _function("renderVideo")
    assert "source === 'capcut'" in src and "confirm(" in src
    assert "confirm_overwrite" in src
    # the question comes before the render is started
    assert src.index("confirm(") < src.index("fetch('/platform/workers/render'")
