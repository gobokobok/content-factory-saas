"""Tests for P10-S1: Asset quality, character sourcing, OST consistency.

Five production-quality bugs fixed in this story:
- Bug 1: lower_third removed — Character person name → on_screen_text OST instead
- Bug 2: segment_type normalisation (Claude outputs lowercase → must canonicalize)
- Bug 3: cross-scene asset deduplication via shared used_source_urls + asyncio.Lock
- Bug 4: Event OST synthesis via Haiku when on_screen_text is absent
- Bug 5: NotoSans font path replaces Poppins for Unicode arrow support
"""

import asyncio
import logging
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.workers.acquisition_worker import (
    _try_candidates,
)
from cf_platform.workers.render_worker import (
    _build_render_script,
    _collect_overlay_filters,
    _overlay_section,
)
from cf_platform.workers.storyboard_worker import (
    _apply_patches_and_render_options,
    _sanitize_storyboard_data,
)
from src.models import (
    AssetManifest,
    LowerThirdSpec,
    ManifestEntry,
    OnScreenTextOverlay,
    SceneRenderOptions,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene(
    scene_id: str = "1",
    segment_type: str = "B-roll",
    duration_s: float = 3.0,
    on_screen_text: Optional[str] = None,
    on_screen_text_type: Optional[str] = None,
    person_name: Optional[str] = None,
    render_options: Optional[SceneRenderOptions] = None,
) -> StoryboardScene:
    return StoryboardScene(
        scene=scene_id,
        clip_type="still_with_motion",
        duration_s=duration_s,
        voiceover_line="Housing prices rose sharply.",
        segment_type=segment_type,
        primary_stk="housing market",
        context_stk="housing",
        concept_stk="economy",
        sfx="",
        sfx_timing="",
        on_screen_text=on_screen_text,
        on_screen_text_type=on_screen_text_type,
        person_name=person_name,
        render_options=render_options,
    )


def _storyboard(scenes: list[StoryboardScene]) -> Storyboard:
    total_s = sum(s.duration_s for s in scenes)
    return Storyboard(
        **{
            "global": StoryboardGlobal(subtitle_style="TikTok", bg_music="upbeat", visual_style="Documentary"),
            "scenes": scenes,
            "summary": StoryboardSummary(
                total_scenes=len(scenes),
                total_duration_s=total_s,
                rhythm=" / ".join(["SM"] * len(scenes)),
            ),
        }
    )


def _manifest(scene_ids: list[str]) -> AssetManifest:
    entries = [
        ManifestEntry(
            scene_id=sid,
            clip_type="still_with_motion",
            segment_type="B-roll",
            file_key=f"runs/run1/images/{sid}.jpg",
            source="pexels",
            qa_passed=True,
        )
        for sid in scene_ids
    ]
    return AssetManifest(run_id="run1", entries=entries)


def _make_candidate(url: str = "https://example.com/img.jpg", width: int = 1920, height: int = 1080, source: str = "pexels"):
    from cf_platform.workers.acquisition_worker import _Candidate
    return _Candidate(
        url=url,
        source=source,
        width=width,
        height=height,
        duration_seconds=None,
        ext="jpg",
        content_type="image/jpeg",
        attribution=None,
    )


def _make_entry(scene_id: str = "1") -> ManifestEntry:
    return ManifestEntry(
        scene_id=scene_id,
        clip_type="still_with_motion",
        segment_type="B-roll",
        primary_stk="housing",
        context_stk="housing",
        concept_stk="economy",
        duration_s=3.0,
    )


# ── Bug 1: lower_third removed; Character person name → OST ──────────────────


def test_bug1_character_scene_sets_ost_not_lower_third():
    """Character scene with person_name → on_screen_text set, lower_third stays None."""
    scene = _scene("1", segment_type="Character", person_name="Jerome Powell")
    sb = _storyboard([scene])
    result = _apply_patches_and_render_options(sb, [])
    patched = result.scenes[0]

    assert patched.render_options is not None
    assert patched.render_options.lower_third is None
    assert patched.on_screen_text == "Jerome Powell"
    assert patched.on_screen_text_type == "person"


def test_bug1_character_ost_overlay_type_is_person():
    """OST overlay built for a Character scene has type='person'."""
    scene = _scene("1", segment_type="Character", person_name="Janet Yellen", duration_s=4.0)
    sb = _storyboard([scene])
    result = _apply_patches_and_render_options(sb, [])
    overlay = result.scenes[0].render_options.on_screen_text_overlay
    assert overlay is not None
    assert overlay.type == "person"
    assert overlay.text == "Janet Yellen"


def test_bug1_lower_third_alone_produces_no_drawtext():
    """A scene with only lower_third set produces no drawtext in the overlay section (Bug 1)."""
    lt = LowerThirdSpec(name="Jerome Powell", title="Federal Reserve Chair")
    scene = _scene("1", render_options=SceneRenderOptions(lower_third=lt))
    sb = _storyboard([scene])
    section, src = _overlay_section(sb, "$WORK/in.mp4")
    assert section == ""
    assert src == "$WORK/in.mp4"


def test_bug1_render_script_no_lower_third_drawtext():
    """render script contains no lower_third person name when only lower_third is set."""
    lt = LowerThirdSpec(name="Powell", title="Fed Chair")
    scene = _scene("1", render_options=SceneRenderOptions(lower_third=lt))
    sb = _storyboard([scene])
    mf = _manifest(["1"])
    script = _build_render_script("run1", sb, mf, None, "neutral", True)
    assert "Powell" not in script


# ── Bug 2: segment_type normalisation ────────────────────────────────────────


def _raw_scene(segment_type: str, person_name: Optional[str] = None) -> dict:
    return {
        "scene": "1",
        "clip_type": "still_with_motion",
        "duration_s": 3.0,
        "voiceover_line": "Test",
        "segment_type": segment_type,
        "primary_stk": "test",
        "context_stk": "test",
        "concept_stk": "test",
        "sfx": "",
        "sfx_timing": "",
        "on_screen_text": None,
        "on_screen_text_type": None,
        "person_name": person_name,
        "person_title": None,
        "motion_effect": None,
    }


def test_bug2_lowercase_character_is_normalised():
    """segment_type='character' (lowercase) is normalised to 'Character' by sanitizer."""
    scene = _raw_scene("character", person_name="Jerome Powell")
    data = {"scenes": [scene]}
    _sanitize_storyboard_data(data)
    assert data["scenes"][0]["segment_type"] == "Character"


def test_bug2_lowercase_broll_variants_normalised():
    """'b-roll' and 'broll' both normalise to 'B-roll'."""
    for variant in ("b-roll", "broll", "B-Roll"):
        scene = _raw_scene(variant)
        data = {"scenes": [scene]}
        _sanitize_storyboard_data(data)
        assert data["scenes"][0]["segment_type"] == "B-roll", f"'{variant}' → {data['scenes'][0]['segment_type']!r}"


def test_bug2_event_lowercase_normalised():
    """'event' normalises to 'Event'."""
    scene = _raw_scene("event")
    data = {"scenes": [scene]}
    _sanitize_storyboard_data(data)
    assert data["scenes"][0]["segment_type"] == "Event"


# ── Bug 3: cross-scene asset deduplication ────────────────────────────────────


@pytest.mark.asyncio
async def test_bug3_duplicate_url_skipped_and_flag_set():
    """When a URL is already in used_source_urls, the candidate is skipped and duplicate_avoided=True."""
    storage = InMemoryArtifactStorage()
    entry = _make_entry()
    candidate = _make_candidate(url="https://example.com/img.jpg")
    used: set[str] = {"https://example.com/img.jpg"}
    lock = asyncio.Lock()
    collected: list = []

    with patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl:
        result = await _try_candidates([candidate], entry, False, "run1", storage, collected, used, lock)

    assert result is False
    assert entry.duplicate_avoided is True
    mock_dl.assert_not_called()


@pytest.mark.asyncio
async def test_bug3_accepted_url_added_to_used_set():
    """A successfully acquired URL is added to used_source_urls for future deduplication."""
    from cf_platform.workers.acquisition_worker import qa_score
    from cf_platform.workers.acquisition_worker import QAResult

    storage = InMemoryArtifactStorage()
    entry = _make_entry()
    candidate = _make_candidate(url="https://example.com/fresh.jpg")
    used: set[str] = set()
    lock = asyncio.Lock()
    collected: list = []

    with (
        patch("cf_platform.workers.acquisition_worker.qa_score") as mock_qa,
        patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl,
    ):
        mock_qa.return_value = QAResult(passed=True, resolution_ok=True, duration_ok=True, clip_score=None, clip_enabled=False)
        mock_dl.return_value = b"bytes"
        result = await _try_candidates([candidate], entry, False, "run1", storage, collected, used, lock)

    assert result is True
    assert "https://example.com/fresh.jpg" in used


# ── Bug 4: Event OST synthesis ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bug4_event_without_ost_triggers_haiku_call():
    """_synthesize_event_ost calls Haiku for Event scenes with no on_screen_text."""
    from cf_platform.workers.storyboard_worker import _synthesize_event_ost

    event_scene = _scene("1", segment_type="Event", duration_s=3.0)
    assert event_scene.on_screen_text is None

    sb = _storyboard([event_scene])

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Rate hike 2018"

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await _synthesize_event_ost(sb, "fake-api-key")

    assert mock_client.messages.create.call_count == 1
    # _synthesize_event_ost always stores text as UPPERCASE
    assert result.scenes[0].on_screen_text == "RATE HIKE 2018"


@pytest.mark.asyncio
async def test_bug4_event_with_existing_ost_skipped():
    """_synthesize_event_ost does NOT call Haiku for Event scenes that already have on_screen_text."""
    from cf_platform.workers.storyboard_worker import _synthesize_event_ost

    event_scene = _scene("1", segment_type="Event", on_screen_text="Great Depression 1929", duration_s=3.0)
    sb = _storyboard([event_scene])

    mock_client = AsyncMock()

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await _synthesize_event_ost(sb, "fake-api-key")

    mock_client.messages.create.assert_not_called()
    assert result.scenes[0].on_screen_text == "Great Depression 1929"


@pytest.mark.asyncio
async def test_bug4_synthesis_cap_limits_calls(caplog):
    """_synthesize_event_ost makes at most _MAX_EVENT_OST_CALLS Haiku calls."""
    from cf_platform.workers.storyboard_worker import _MAX_EVENT_OST_CALLS, _synthesize_event_ost

    scenes = [_scene(str(i), segment_type="Event", duration_s=2.0) for i in range(_MAX_EVENT_OST_CALLS + 3)]
    sb = _storyboard(scenes)

    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.content = [MagicMock()]
        resp.content[0].text = f"Title {call_count}"
        return resp

    mock_client = AsyncMock()
    mock_client.messages.create = fake_create

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic", return_value=mock_client):
        await _synthesize_event_ost(sb, "fake-api-key")

    assert call_count == _MAX_EVENT_OST_CALLS


@pytest.mark.asyncio
async def test_bug4_synthesis_logs_warning(caplog):
    """_synthesize_event_ost logs a WARNING for each gap it fills."""
    from cf_platform.workers.storyboard_worker import _synthesize_event_ost

    scene = _scene("1", segment_type="Event", duration_s=3.0)
    sb = _storyboard([scene])

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Crisis moment"

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="cf_platform.workers.storyboard_worker"):
            await _synthesize_event_ost(sb, "fake-api-key")

    assert any("synthesised" in r.message.lower() or "Event" in r.message for r in caplog.records)


# ── Bug 5: NotoSans font path ─────────────────────────────────────────────────


def test_bug5_noto_font_path_in_overlay_section():
    """OST drawtext filters use NotoSans font, not Poppins."""
    ost = OnScreenTextOverlay(text="38% decline", type="stat", enable_expr="between(t,0,3)")
    scene = _scene("1", render_options=SceneRenderOptions(on_screen_text_overlay=ost))
    sb = _storyboard([scene])
    section, _ = _overlay_section(sb, "$WORK/in.mp4")
    assert "NotoSans" in section
    assert "Poppins" not in section


def test_bug5_noto_font_path_in_collect_overlay_filters():
    """_collect_overlay_filters (textfile= path) also references NotoSans."""
    scene = _scene("1", on_screen_text="Rate hike 2018", on_screen_text_type="stat", duration_s=3.0)
    scene_with_ost = scene.model_copy(update={"on_screen_text": "Rate hike 2018"})
    sb = _storyboard([scene_with_ost])
    _, filters = _collect_overlay_filters(sb)
    filter_block = "\n".join(filters)
    assert "NotoSans" in filter_block
    assert "Poppins" not in filter_block


def test_bug5_noto_font_in_render_script():
    """OST drawtext in render script uses NotoSans, not Poppins (Bug 5).

    The ASS caption style line still uses Poppins for subtitles — that's expected.
    Only the drawtext overlay font must be NotoSans.
    """
    ost = OnScreenTextOverlay(text="Rate up 0.75%", type="stat", enable_expr="between(t,0,3)")
    scene = _scene("1", render_options=SceneRenderOptions(on_screen_text_overlay=ost), duration_s=3.0)
    sb = _storyboard([scene])
    mf = _manifest(["1"])
    script = _build_render_script("run1", sb, mf, None, "neutral", True)
    assert "NotoSans" in script
    assert "fontfile=/usr/local/share/fonts/Poppins-Bold.ttf" not in script  # OST must not use Poppins
