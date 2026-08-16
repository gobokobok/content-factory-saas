"""Tests for P9-S4 Native RenderWorker.

Coverage:
- film_look=True → sepia filter in per-scene section (before concat)
- film_look=False/None → no sepia in script
- lower_third → name + title drawtext with enable expression
- on_screen_text_overlay → drawtext with enable_expr
- no render_options → overlay section absent
- caption_y_override → ASS Dialogue MarginV = 1920 - y_override
- no lower_third → MarginV=0 in ASS events (style default)
- render_script.sh persisted to storage BEFORE subprocess call
- FFmpeg non-zero exit code raises RuntimeError
- no segment_type import in render_worker module
"""

import inspect
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import Artifact, LineageEnvelope, StageState
from cf_platform.workers.render_worker import (
    _FILM_LOOK_FILTER,
    RENDER_WORKER_REGISTRATION,
    RenderArtifact,
    _build_captions_with_y_override,
    _build_render_script,
    _film_look_section,
    _overlay_section,
    build_render_worker,
)
from src.models import (
    AssetManifest,
    LowerThirdSpec,
    ManifestEntry,
    OnScreenTextOverlay,
    SceneRenderOptions,
    Storyboard,
    StoryboardScene,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene(
    scene_id: str = "1",
    duration_s: float = 3.0,
    film_look: bool = False,
    lower_third: LowerThirdSpec | None = None,
    on_screen_text_overlay: OnScreenTextOverlay | None = None,
    voiceover_line: str = "Housing prices rose sharply.",
    sfx: str = "silence",
) -> StoryboardScene:
    render_options: SceneRenderOptions | None = None
    if film_look or lower_third or on_screen_text_overlay:
        render_options = SceneRenderOptions(
            film_look=film_look,
            lower_third=lower_third,
            on_screen_text_overlay=on_screen_text_overlay,
        )
    return StoryboardScene(
        scene=scene_id,
        clip_type="still_with_motion",
        duration_s=duration_s,
        voiceover_line=voiceover_line,
        segment_type="B-roll",
        primary_stk="housing market",
        context_stk="housing",
        concept_stk="economy",
        sfx=sfx,
        sfx_timing="on cut",
        render_options=render_options,
    )


def _storyboard(scenes: list[StoryboardScene]) -> Storyboard:
    from src.models import StoryboardGlobal, StoryboardSummary
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


def _manifest(scene_ids: list[str], run_id: str = "run-test") -> AssetManifest:
    entries = [
        ManifestEntry(
            scene_id=sid,
            clip_type="still_with_motion",
            segment_type="B-roll",
            file_key=f"runs/{run_id}/images/{sid}.jpg",
            source="pexels",
            qa_passed=True,
            qa_clip_score=None,
            fallback_used=False,
        )
        for sid in scene_ids
    ]
    return AssetManifest(run_id=run_id, entries=entries)


def _storyboard_artifact_envelope(storyboard: Storyboard, run_id: str = "run-test") -> dict:
    """Wrap a Storyboard in the artifact envelope format expected by read_artifact."""
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
    body = VerifiedStoryboardArtifact(
        prompt_version="v0.12",
        scene_count=len(storyboard.scenes),
        storyboard=storyboard.model_dump(by_alias=True, mode="json"),
        generated_at=datetime.now(UTC),
    )
    lineage = LineageEnvelope(
        run_id=run_id, worker="storyboard_worker", worker_version="1.0.0",
        prompt_version="v0.12", model="claude-sonnet-4-6", created_at=datetime.now(UTC),
    )
    art = Artifact(
        name="verified_storyboard", stage="storyboard", version=1,
        run_id=run_id, r2_key=f"users/operator/runs/{run_id}/storyboard/verified_storyboard@v1.json",
        lineage=lineage,
    )
    return {"artifact": art.model_dump(mode="json"), "body": body.model_dump(mode="json")}


def _manifest_artifact_envelope(manifest: AssetManifest, run_id: str = "run-test") -> dict:
    """Wrap an AssetManifest in the artifact envelope format expected by read_artifact."""
    from cf_platform.workers.acquisition_worker import AssetManifestArtifact
    body = AssetManifestArtifact(
        scene_count=len(manifest.entries),
        acquired=len(manifest.entries),
        failed=0,
        footage_summary={},
        manifest=manifest.model_dump(mode="json"),
        generated_at=datetime.now(UTC),
    )
    lineage = LineageEnvelope(
        run_id=run_id, worker="acquisition_worker", worker_version="1.0.0",
        prompt_version="none", model="none", created_at=datetime.now(UTC),
    )
    art = Artifact(
        name="asset_manifest", stage="acquisition", version=1,
        run_id=run_id, r2_key=f"users/operator/runs/{run_id}/acquisition/asset_manifest@v1.json",
        lineage=lineage,
    )
    return {"artifact": art.model_dump(mode="json"), "body": body.model_dump(mode="json")}


# ── _film_look_section ────────────────────────────────────────────────────────


def test_film_look_section_includes_sepia_filter():
    """film_look=True on a scene → sepia filter chain present in section."""
    sb = _storyboard([_scene("1", film_look=True)])
    result = _film_look_section(sb)
    assert result is not None
    assert _FILM_LOOK_FILTER in result


def test_film_look_section_references_scene_number():
    """film_look section writes to scene_01.mp4 and uses mv to replace in-place."""
    sb = _storyboard([_scene("1", film_look=True)])
    result = _film_look_section(sb)
    assert result is not None
    assert "scene_01.mp4" in result
    assert "mv" in result


def test_film_look_section_none_when_no_film_look():
    """No scene has film_look → _film_look_section returns None."""
    sb = _storyboard([_scene("1", film_look=False), _scene("2")])
    assert _film_look_section(sb) is None


def test_film_look_only_for_flagged_scenes():
    """Only scenes with film_look=True appear in the section."""
    sb = _storyboard([_scene("1", film_look=True), _scene("2", film_look=False)])
    result = _film_look_section(sb)
    assert result is not None
    assert "scene_01" in result
    assert "scene_02" not in result


# ── _overlay_section ──────────────────────────────────────────────────────────


def test_overlay_section_lower_third_no_longer_renders():
    """lower_third alone does not generate drawtext — person name is now OST (P10-S1 Bug 1)."""
    lt = LowerThirdSpec(name="Jerome Powell", title="Chair, Federal Reserve")
    sb = _storyboard([_scene("1", lower_third=lt, duration_s=4.0)])
    section, new_src = _overlay_section(sb, "$WORK/video_captioned.mp4")
    assert section == ""
    assert new_src == "$WORK/video_captioned.mp4"


def test_overlay_section_enable_expression():
    """on_screen_text_overlay drawtext has between(t,...) enable expression scoped to the scene."""
    ost = OnScreenTextOverlay(text="Rate hike", type="stat", enable_expr="between(t,0,5)")
    sb = _storyboard([_scene("1", duration_s=5.0, on_screen_text_overlay=ost)])
    section, _ = _overlay_section(sb, "$WORK/video_captioned.mp4")
    assert "between(t,0.000,5.000)" in section


def test_overlay_section_on_screen_text_overlay_uses_scene_range():
    """on_screen_text_overlay uses the freshly computed scene-range enable expression.

    The stored enable_expr on OnScreenTextOverlay is stale after voice-alignment
    adjusts scene durations; _overlay_section recomputes timing from t_offset so
    the overlay appears in sync with the actual video clip.
    """
    ost = OnScreenTextOverlay(
        text="38% decline",
        type="stat",
        enable_expr="between(t,2.500,4.500)",  # stale — should be ignored
    )
    sb = _storyboard([_scene("1", duration_s=3.0, on_screen_text_overlay=ost)])
    section, _ = _overlay_section(sb, "$WORK/video_captioned.mp4")
    # Fresh scene-range expression (scene starts at 0, duration 3.0 s)
    assert "between(t,0.000,3.000)" in section
    assert "between(t,2.500,4.500)" not in section  # stale expr must not appear
    assert "38\\% DECLINE" in section  # text is uppercased and % is escaped for drawtext


def test_overlay_section_empty_when_no_render_options():
    """Scenes with no render_options → overlay section is empty string."""
    sb = _storyboard([_scene("1"), _scene("2")])
    section, src = _overlay_section(sb, "$WORK/video_captioned.mp4")
    assert section == ""
    assert src == "$WORK/video_captioned.mp4"


# ── _build_captions_with_y_override ──────────────────────────────────────────


def test_caption_y_override_sets_margin_v():
    """lower_third with caption_y_override=1540 → MarginV=380 in Dialogue events."""
    from src.models import WordTimestamp

    lt = LowerThirdSpec(name="Jerome Powell", caption_y_override=1540)
    scene = _scene("1", duration_s=3.0, lower_third=lt)
    words = [
        WordTimestamp(word="housing", start_ms=0, end_ms=500, confidence=1.0),
        WordTimestamp(word="prices", start_ms=500, end_ms=1000, confidence=1.0),
    ]
    ass = _build_captions_with_y_override([[words[0], words[1]]], [scene], "TikTok")
    # MarginV = 1920 - 1540 = 380
    assert ",0,0,380,," in ass


def test_caption_no_override_uses_zero_margin():
    """Scene without lower_third → MarginV=0 in ASS events (use style default)."""
    from src.models import WordTimestamp

    scene = _scene("1", duration_s=3.0)
    words = [WordTimestamp(word="housing", start_ms=0, end_ms=500, confidence=1.0)]
    ass = _build_captions_with_y_override([words], [scene], "TikTok")
    assert ",0,0,0,," in ass


# ── _build_render_script ──────────────────────────────────────────────────────


def test_render_script_contains_film_look_for_flagged_scene():
    """Script includes sepia filter section when a scene has film_look=True."""
    sb = _storyboard([_scene("1", film_look=True)])
    mf = _manifest(["1"])
    script = _build_render_script("run42", sb, mf, None, "neutral", True)
    assert _FILM_LOOK_FILTER in script


def test_render_script_no_sepia_when_no_film_look():
    """Script has no sepia filter when no scene has film_look."""
    sb = _storyboard([_scene("1")])
    mf = _manifest(["1"])
    script = _build_render_script("run42", sb, mf, None, "neutral", True)
    assert "hqdn3d" not in script


def test_render_script_overlay_section_absent_for_lower_third_only():
    """lower_third alone does not add drawtext to render script (P10-S1 Bug 1 — use OST instead)."""
    lt = LowerThirdSpec(name="Janet Yellen", title="Treasury Secretary")
    sb = _storyboard([_scene("1", lower_third=lt)])
    mf = _manifest(["1"])
    script = _build_render_script("run42", sb, mf, None, "neutral", True)
    assert "Janet Yellen" not in script


def test_render_script_film_look_before_concat():
    """Film look section appears before the concat section in the script."""
    sb = _storyboard([_scene("1", film_look=True)])
    mf = _manifest(["1"])
    script = _build_render_script("run42", sb, mf, None, "neutral", True)
    fl_pos = script.index("hqdn3d")
    concat_pos = script.index("Concatenate")
    assert fl_pos < concat_pos


# ── Full worker: registration + integration ───────────────────────────────────


def test_render_worker_registration_pins():
    """RENDER_WORKER_REGISTRATION has expected version and no-model markers."""
    assert RENDER_WORKER_REGISTRATION.worker_version == "1.0.0"
    assert RENDER_WORKER_REGISTRATION.model == "none"
    assert RENDER_WORKER_REGISTRATION.prompt_version == "none"


@pytest.mark.asyncio
async def test_render_script_persisted_before_subprocess():
    """render_script.sh is written to storage before the subprocess call."""
    run_id = "run-persist"
    storage = InMemoryArtifactStorage()
    sb = _storyboard([_scene("1")])
    mf = _manifest(["1"], run_id=run_id)

    sb_key = f"users/operator/runs/{run_id}/storyboard/verified_storyboard@v1.json"
    mf_key = f"users/operator/runs/{run_id}/acquisition/asset_manifest@v1.json"
    await storage.put_json(sb_key, _storyboard_artifact_envelope(sb, run_id))
    await storage.put_json(mf_key, _manifest_artifact_envelope(mf, run_id))

    # Put a fake asset file in bytes store
    await storage.put_bytes(
        f"runs/{run_id}/images/1.jpg", b"JPEG_FAKE", content_type="image/jpeg"
    )
    # Put a fake voiceover so the script check passes at execution time
    await storage.put_bytes(
        f"runs/{run_id}/voiceover/vo.mp3", b"AUDIO_FAKE", content_type="audio/mpeg"
    )

    call_order: list[str] = []
    original_put_bytes = storage.put_bytes

    async def tracking_put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        call_order.append(key)
        await original_put_bytes(key, data, content_type)

    storage.put_bytes = tracking_put_bytes  # type: ignore[method-assign]

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Done"
    mock_result.stderr = ""

    fake_mp4 = b"FAKE_MP4"

    def fake_subprocess_run(*args, **kwargs):
        # Simulate final.mp4 being written by the script
        out = Path(f"/tmp/{run_id}/output/final.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(fake_mp4)
        return mock_result

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=fake_subprocess_run)):
        worker = build_render_worker(storage, ffmpeg_timeout_seconds=60)
        state = StageState(
            run_id=run_id, user_id="operator", inputs={},
            artifacts={"verified_storyboard": sb_key, "asset_manifest": mf_key},
        )
        output = await worker(state)

    # render_script.sh must appear in the call order BEFORE final.mp4
    script_key = f"runs/{run_id}/render_script.sh"
    video_key = f"runs/{run_id}/output/final.mp4"
    assert script_key in call_order
    assert video_key in call_order
    assert call_order.index(script_key) < call_order.index(video_key)
    assert isinstance(output.artifact, RenderArtifact)


@pytest.mark.asyncio
async def test_render_survives_stale_invalid_on_screen_text_type():
    """A stored storyboard with an out-of-enum on_screen_text_type (e.g. a legacy/stale
    value like "descriptor") must not raise a pydantic ValidationError on render — it
    should be sanitised the same way every other Storyboard.model_validate call site
    sanitises it (see _sanitize_storyboard_data)."""
    run_id = "run-stale-ost"
    storage = InMemoryArtifactStorage()
    sb = _storyboard([_scene("1")])
    mf = _manifest(["1"], run_id=run_id)

    sb_key = f"users/operator/runs/{run_id}/storyboard/verified_storyboard@v1.json"
    mf_key = f"users/operator/runs/{run_id}/acquisition/asset_manifest@v1.json"

    envelope = _storyboard_artifact_envelope(sb, run_id)
    # Corrupt the raw stored dict with an invalid on_screen_text_type, bypassing the
    # Storyboard pydantic model entirely — mirrors how this value ends up on disk.
    envelope["body"]["storyboard"]["scenes"][0]["on_screen_text"] = "Some label"
    envelope["body"]["storyboard"]["scenes"][0]["on_screen_text_type"] = "descriptor"

    await storage.put_json(sb_key, envelope)
    await storage.put_json(mf_key, _manifest_artifact_envelope(mf, run_id))
    await storage.put_bytes(f"runs/{run_id}/images/1.jpg", b"X", content_type="image/jpeg")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Done"
    mock_result.stderr = ""

    def fake_subprocess_run(*args, **kwargs):
        out = Path(f"/tmp/{run_id}/output/final.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE_MP4")
        return mock_result

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=fake_subprocess_run)):
        worker = build_render_worker(storage, ffmpeg_timeout_seconds=60)
        state = StageState(
            run_id=run_id, user_id="operator", inputs={},
            artifacts={"verified_storyboard": sb_key, "asset_manifest": mf_key},
        )
        output = await worker(state)

    assert isinstance(output.artifact, RenderArtifact)


@pytest.mark.asyncio
async def test_ffmpeg_failure_raises_runtime_error():
    """Non-zero FFmpeg exit code raises RuntimeError."""
    run_id = "run-fail"
    storage = InMemoryArtifactStorage()
    sb = _storyboard([_scene("1")])
    mf = _manifest(["1"], run_id=run_id)

    sb_key = f"users/operator/runs/{run_id}/storyboard/verified_storyboard@v1.json"
    mf_key = f"users/operator/runs/{run_id}/acquisition/asset_manifest@v1.json"
    await storage.put_json(sb_key, _storyboard_artifact_envelope(sb, run_id))
    await storage.put_json(mf_key, _manifest_artifact_envelope(mf, run_id))
    await storage.put_bytes(f"runs/{run_id}/images/1.jpg", b"X", content_type="image/jpeg")

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "ffmpeg: error encoding"

    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)):
        worker = build_render_worker(storage, ffmpeg_timeout_seconds=60)
        state = StageState(
            run_id=run_id, user_id="operator", inputs={},
            artifacts={"verified_storyboard": sb_key, "asset_manifest": mf_key},
        )
        with pytest.raises(RuntimeError, match="FFmpeg exited 1"):
            await worker(state)


# ── Module hygiene ────────────────────────────────────────────────────────────


def test_no_segment_type_import_in_render_worker():
    """render_worker.py must not import or reference segment_type."""
    import cf_platform.workers.render_worker as rw_module

    source = inspect.getsource(rw_module)
    assert "segment_type" not in source, (
        "render_worker.py must not reference segment_type — "
        "all routing must come from render_options fields"
    )
