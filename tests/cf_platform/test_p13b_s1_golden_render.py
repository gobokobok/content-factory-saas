"""Golden render-script tests (P13b-S1).

These pin the exact bash script the RenderWorker produces for a spread of runs. They
were written and committed BEFORE the builder was rewired to read the Timeline, so
any byte of difference after that rewiring fails here. A golden may only change on
purpose: regenerate with ``UPDATE_GOLDEN=1 pytest tests/cf_platform/test_p13b_s1_golden_render.py``
and state the difference in the story Handover.

The harness runs the whole worker (alignment → timing → script) against in-memory
storage with FFmpeg stubbed out, and captures ``render_script.sh``. The only
non-deterministic line, ``# generated_at:``, is masked.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import Artifact, LineageEnvelope, StageState
from cf_platform.workers.acquisition_worker import AssetManifestArtifact
from cf_platform.workers.render_worker import build_render_worker
from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
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

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "render"
RUN_ID = "gold1"
_GENERATED_AT = re.compile(r"^# generated_at: .*$", re.MULTILINE)


# ── Fixture builders ──────────────────────────────────────────────────────────


def words(n: int, word_ms: int = 400, offset_ms: int = 240) -> list[VoiceWordTimestamp]:
    """Return n back-to-back words "w0".."w{n-1"} after a short pre-silence."""
    return [
        VoiceWordTimestamp(
            word=f"w{i}", start_ms=offset_ms + i * word_ms,
            end_ms=offset_ms + (i + 1) * word_ms, confidence=0.99,
        )
        for i in range(n)
    ]


def scene(
    sid: str, *, duration_s: float = 3.0, clip_type: str = "still_with_motion",
    motion: str | None = "ken_burns", start_word: int | None = None, end_word: int | None = None,
    start_ms: int | None = None, text: str | None = None, text_type: str | None = None,
    sfx: str = "", film_look: bool = False, overlay: str | None = None,
    caption_y: int | None = None, voiceover_line: str | None = None,
) -> StoryboardScene:
    """Build one storyboard scene with the fields the render script reads."""
    opts = None
    if film_look or overlay or caption_y:
        opts = SceneRenderOptions(
            film_look=film_look,
            lower_third=LowerThirdSpec(name="n", caption_y_override=caption_y) if caption_y else None,
            on_screen_text_overlay=(
                OnScreenTextOverlay(text=overlay, type="stat", enable_expr="") if overlay else None
            ),
        )
    return StoryboardScene(
        scene=sid, clip_type=clip_type, duration_s=duration_s,
        voiceover_line=voiceover_line or f"line for scene {sid}",
        primary_stk="a", context_stk="b", concept_stk="c",
        motion_effect=motion, on_screen_text=text, on_screen_text_type=text_type,
        sfx=sfx, sfx_timing="on cut", render_options=opts,
        start_word=start_word, end_word=end_word,
        scene_start_ms=start_ms,
    )


def storyboard(scenes: list[StoryboardScene]) -> Storyboard:
    """Wrap scenes in a Storyboard with a summary of the scenes' summed duration."""
    return Storyboard(**{
        "global": StoryboardGlobal(subtitle_style="TikTok", bg_music="upbeat", visual_style="Documentary"),
        "scenes": scenes,
        "summary": StoryboardSummary(
            total_scenes=len(scenes),
            total_duration_s=sum(s.duration_s for s in scenes),
            rhythm=" / ".join(["SM"] * len(scenes)),
        ),
    })


def manifest(scenes: list[StoryboardScene], exts: dict[str, str] | None = None,
             sources: dict[str, str] | None = None) -> AssetManifest:
    """One acquired manifest entry per scene; ext/source default to .jpg / pexels."""
    exts = exts or {}
    sources = sources or {}
    entries = []
    for s in scenes:
        ext = exts.get(s.scene, ".jpg")
        folder = "images" if ext in (".jpg", ".jpeg", ".png", ".webp") else "video"
        entries.append(ManifestEntry(
            scene_id=s.scene, clip_type=s.clip_type, segment_type="B-roll",
            file_key=f"runs/{RUN_ID}/{folder}/{s.scene}{ext}", status="acquired",
            source=sources.get(s.scene, "pexels"), qa_passed=True,
        ))
    return AssetManifest(run_id=RUN_ID, entries=entries)


def _lineage(worker: str) -> LineageEnvelope:
    """Return a throwaway lineage envelope."""
    return LineageEnvelope(
        run_id=RUN_ID, worker=worker, worker_version="1.0.0",
        prompt_version="none", model="none", created_at=datetime.now(UTC),
    )


def _envelope(name: str, stage: str, body) -> dict:
    """Wrap a body model in the stored artifact envelope."""
    art = Artifact(
        name=name, stage=stage, version=1, run_id=RUN_ID,
        r2_key=f"users/operator/runs/{RUN_ID}/{stage}/{name}@v1.json", lineage=_lineage(name),
    )
    return {"artifact": art.model_dump(mode="json"), "body": body.model_dump(mode="json")}


async def render_script(
    sb: Storyboard, mf: AssetManifest, *, alignment: list[VoiceWordTimestamp] | None = None,
    method: str = "deepgram_nova2", total_s: float | None = None,
    inputs: dict | None = None, color_grade: str = "neutral", blur_fill: bool = True,
    music_in_run: bool = False,
) -> str:
    """Run the RenderWorker with FFmpeg stubbed and return the script it persisted."""
    storage = InMemoryArtifactStorage()
    prefix = f"users/operator/runs/{RUN_ID}"
    sb_key = f"{prefix}/storyboard/verified_storyboard@v1.json"
    mf_key = f"{prefix}/acquisition/asset_manifest@v1.json"
    sb_body = VerifiedStoryboardArtifact(
        prompt_version="v", scene_count=len(sb.scenes),
        storyboard=sb.model_dump(by_alias=True, mode="json"), generated_at=datetime.now(UTC),
    )
    mf_body = AssetManifestArtifact(
        scene_count=len(mf.entries), acquired=len(mf.entries), failed=0, footage_summary={},
        manifest=mf.model_dump(mode="json"), generated_at=datetime.now(UTC),
    )
    await storage.put_json(sb_key, _envelope("verified_storyboard", "storyboard", sb_body))
    await storage.put_json(mf_key, _envelope("asset_manifest", "acquisition", mf_body))
    artifacts = {"verified_storyboard": sb_key, "asset_manifest": mf_key}
    if alignment is not None:
        va_key = f"{prefix}/voice/voice_alignment@v1.json"
        va_body = VoiceAlignmentArtifact(
            mp3_r2_key="", word_timestamps=alignment, alignment_method=method,
            total_duration_s=total_s if total_s is not None else alignment[-1].end_ms / 1000 + 0.3,
        )
        await storage.put_json(va_key, _envelope("voice_alignment", "voice", va_body))
        artifacts["voice_alignment"] = va_key
    for entry in mf.entries:
        await storage.put_bytes(entry.file_key, b"ASSET")
    if music_in_run:
        await storage.put_bytes(f"runs/{RUN_ID}/music/bed.mp3", b"M", content_type="audio/mpeg")

    result = MagicMock(returncode=0, stdout="", stderr="")

    def fake_run(*_a, **_k):
        """Pretend the script ran: leave a final.mp4 behind."""
        out = Path(f"/tmp/{RUN_ID}/output/final.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"MP4")
        return result

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=fake_run)):
        worker = build_render_worker(
            storage, color_grade_preset=color_grade, blur_fill_enabled=blur_fill,
            ffmpeg_timeout_seconds=60,
        )
        await worker(StageState(run_id=RUN_ID, user_id="operator", inputs=inputs or {}, artifacts=artifacts))
    return (await storage.get_bytes(f"runs/{RUN_ID}/render_script.sh")).decode("utf-8")


def check_golden(name: str, script: str) -> None:
    """Compare script to tests/golden/render/{name}.sh (or rewrite it with UPDATE_GOLDEN=1)."""
    masked = _GENERATED_AT.sub("# generated_at: <masked>", script)
    path = GOLDEN_DIR / f"{name}.sh"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(masked, encoding="utf-8")
        return
    assert path.exists(), f"missing golden {path} — run with UPDATE_GOLDEN=1"
    assert masked == path.read_text(encoding="utf-8"), f"render script drifted from golden {name}"


# ── Cases ─────────────────────────────────────────────────────────────────────

PORTRAIT = {"format_track": "portrait"}
EFFECTS = ("ken_burns", "zoom_in", "zoom_out", "pan_right", "pan_left", "static")


def _aligned(n_scenes: int = 3, per_scene: int = 4, **kw) -> tuple[Storyboard, AssetManifest, list]:
    """A storyboard cut every per_scene words of an aligned voiceover (live start_word path)."""
    w = words(n_scenes * per_scene)
    scenes = []
    for k in range(n_scenes):
        a, b = k * per_scene, (k + 1) * per_scene - 1
        scenes.append(scene(
            str(k + 1), duration_s=(w[b].end_ms - w[a].start_ms) / 1000, start_word=a, end_word=b,
            start_ms=w[a].start_ms, voiceover_line=" ".join(x.word for x in w[a:b + 1]),
            **kw.get(str(k + 1), {}),
        ))
    return storyboard(scenes), manifest(scenes), w


@pytest.mark.asyncio
async def test_golden_each_motion_effect_portrait():
    """A still with each of the six motion effects, 9:16, no alignment."""
    scenes = [scene(str(i + 1), duration_s=2.5 + i * 0.37, motion=e) for i, e in enumerate(EFFECTS)]
    script = await render_script(storyboard(scenes), manifest(scenes), inputs=PORTRAIT)
    check_golden("motion_each_effect_9x16", script)


@pytest.mark.asyncio
async def test_golden_each_motion_effect_landscape():
    """The same six effects at 16:9 (pans use the 1920-wide travel budget)."""
    scenes = [scene(str(i + 1), duration_s=2.5 + i * 0.37, motion=e) for i, e in enumerate(EFFECTS)]
    script = await render_script(storyboard(scenes), manifest(scenes), inputs={"format_track": "landscape"})
    check_golden("motion_each_effect_16x9", script)


@pytest.mark.asyncio
async def test_golden_legacy_motion_names_and_unset():
    """Pre-D081 names and a missing effect normalise to ken_burns (D081)."""
    scenes = [
        scene("1", motion="scale"), scene("2", motion="ken_burns_in"),
        scene("3", motion=None), scene("4", motion=None, clip_type="hard_cut"),
    ]
    script = await render_script(
        storyboard(scenes), manifest(scenes, exts={"4": ".jpg"}), inputs=PORTRAIT,
    )
    check_golden("motion_legacy_and_unset", script)


@pytest.mark.asyncio
async def test_golden_stock_video_scene():
    """A hard-cut stock video scene next to a still."""
    scenes = [scene("1", clip_type="hard_cut", motion=None, duration_s=6.2), scene("2", duration_s=3.1)]
    script = await render_script(storyboard(scenes), manifest(scenes, exts={"1": ".mp4"}), inputs=PORTRAIT)
    check_golden("stock_video_scene", script)


@pytest.mark.asyncio
async def test_golden_operator_video_on_still_scene():
    """D089: an mp4 on a still scene renders as footage; its motion effect is ignored."""
    scenes = [scene("1", motion="zoom_in", duration_s=4.0), scene("2", motion="pan_left", duration_s=4.0)]
    script = await render_script(
        storyboard(scenes), manifest(scenes, exts={"1": ".mp4", "2": ".mov"}), inputs=PORTRAIT,
    )
    check_golden("operator_video_on_still_scene", script)


@pytest.mark.asyncio
async def test_golden_pan_on_narrow_portrait_still():
    """D091: pans scale with force_original_aspect_ratio=increase (any still, either ratio)."""
    scenes = [scene("1", motion="pan_left", duration_s=3.4), scene("2", motion="pan_right", duration_s=0.9)]
    script = await render_script(storyboard(scenes), manifest(scenes, exts={"1": ".png"}), inputs=PORTRAIT)
    check_golden("pan_narrow_portrait", script)


@pytest.mark.asyncio
async def test_golden_blur_fill_person_photo_and_film_look_and_grade():
    """A wikimedia person portrait (blur-fill), a film-look scene and a colour grade."""
    scenes = [scene("1", motion="pan_left", film_look=True), scene("2", motion="zoom_out")]
    script = await render_script(
        storyboard(scenes), manifest(scenes, sources={"1": "wikimedia_person"}),
        inputs=PORTRAIT, color_grade="warm",
    )
    check_golden("blur_fill_film_look_grade", script)


@pytest.mark.asyncio
async def test_golden_blur_fill_disabled():
    """BLUR_FILL_ENABLED off: a person portrait renders like any other still."""
    scenes = [scene("1", motion="zoom_in")]
    script = await render_script(
        storyboard(scenes), manifest(scenes, sources={"1": "wikimedia_person"}),
        inputs=PORTRAIT, blur_fill=False,
    )
    check_golden("blur_fill_disabled", script)


@pytest.mark.asyncio
async def test_golden_captions_standard_aligned():
    """Standard captions from word-synced alignment, 9:16, live start_word boundaries."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs={**PORTRAIT, "caption_style": "standard"})
    check_golden("captions_standard_aligned", script)


@pytest.mark.asyncio
async def test_golden_captions_punch_aligned():
    """Punch captions (one word, upper case)."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs={**PORTRAIT, "caption_style": "punch"})
    check_golden("captions_punch_aligned", script)


@pytest.mark.asyncio
async def test_golden_captions_landscape_aligned():
    """Captions at 16:9 fall back to the original styling."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs={"format_track": "landscape"})
    check_golden("captions_landscape_aligned", script)


@pytest.mark.asyncio
async def test_golden_captions_off():
    """captions=False burns no subtitles."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs={**PORTRAIT, "captions": False})
    check_golden("captions_off", script)


@pytest.mark.asyncio
async def test_golden_captions_without_alignment():
    """No voice alignment: captions come from the voiceover lines."""
    scenes = [scene("1", voiceover_line="Prices rose again."), scene("2", voiceover_line="Wages did not.")]
    script = await render_script(storyboard(scenes), manifest(scenes), inputs=PORTRAIT)
    check_golden("captions_voiceover_lines", script)


@pytest.mark.asyncio
async def test_golden_on_screen_text_and_caption_override():
    """Plain on_screen_text, an overlay object, and a caption_y_override scene."""
    sb, mf, w = _aligned(
        n_scenes=4,
        **{
            "1": {"text": "Up 40% since 2020", "text_type": "stat"},
            "2": {"overlay": "Median price: $412,000", "caption_y": 1540},
            "3": {},
            "4": {"text": "It's don't 100% — a very long on-screen text that has to wrap onto lines", "text_type": "label"},
        },
    )
    script = await render_script(sb, mf, alignment=w, inputs=PORTRAIT)
    check_golden("on_screen_text", script)


@pytest.mark.asyncio
async def test_golden_sfx_present():
    """SFX with and without on-screen text (0.7s sync offset) and a 'silence' scene."""
    sb, mf, w = _aligned(
        n_scenes=4,
        **{
            "1": {"sfx": "whoosh"},
            "2": {"sfx": "impact", "text": "Big number", "text_type": "stat"},
            "3": {"sfx": "silence"},
            "4": {"sfx": "whoosh"},
        },
    )
    script = await render_script(sb, mf, alignment=w, inputs=PORTRAIT)
    check_golden("sfx_present", script)


@pytest.mark.asyncio
async def test_golden_sfx_absent_music_absent():
    """No SFX anywhere, no music file in the run."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs={**PORTRAIT, "music_enabled": False})
    check_golden("sfx_absent_music_absent", script)


@pytest.mark.asyncio
async def test_golden_music_present():
    """A music file in the run folder; the script finds it at run time."""
    sb, mf, w = _aligned()
    script = await render_script(sb, mf, alignment=w, inputs=PORTRAIT, music_in_run=True)
    check_golden("music_present", script)


@pytest.mark.asyncio
async def test_golden_timing_stored_scene_start_ms():
    """Deepgram alignment, scene_start_ms present but no start_word on the scenes."""
    sb, mf, w = _aligned()
    for s in sb.scenes:
        s.start_word = None
        s.end_word = None
    script = await render_script(sb, mf, alignment=w, inputs=PORTRAIT)
    check_golden("timing_stored_scene_start_ms", script)


@pytest.mark.asyncio
async def test_golden_timing_legacy_two_pass():
    """Deepgram alignment on a storyboard with no scene_start_ms: the two-pass path."""
    w = words(8)
    scenes = [
        scene("1", duration_s=1.6, voiceover_line="w0 w1 w2 w3"),
        scene("2", duration_s=1.6, voiceover_line="w4 w5 w6 w7"),
    ]
    script = await render_script(storyboard(scenes), manifest(scenes), alignment=w, inputs=PORTRAIT)
    check_golden("timing_legacy_two_pass", script)


@pytest.mark.asyncio
async def test_golden_timing_proportional_alignment():
    """A non-Deepgram alignment redistributes durations over the audio length."""
    w = words(8)
    scenes = [
        scene("1", duration_s=2.0, voiceover_line="w0 w1 w2"),
        scene("2", duration_s=2.0, voiceover_line="w3 w4 w5 w6 w7"),
    ]
    script = await render_script(
        storyboard(scenes), manifest(scenes), alignment=w, method="proportional", total_s=5.5, inputs=PORTRAIT,
    )
    check_golden("timing_proportional", script)


def _contraction_run() -> tuple[Storyboard, AssetManifest, list[VoiceWordTimestamp]]:
    """Raw Deepgram words with contraction splits ("don"+"'t" share a start_ms).

    The storyboard's start_word indexes the NORMALISED list (one entry per merged
    contraction); the artifact stores the raw list.
    """
    raw: list[VoiceWordTimestamp] = []
    t = 240
    for i in range(10):
        if i in (1, 3):  # two contractions → raw list is 2 longer than the normalised one
            raw.append(VoiceWordTimestamp(word=f"c{i}", start_ms=t, end_ms=t + 200, confidence=0.9))
            raw.append(VoiceWordTimestamp(word="'t", start_ms=t, end_ms=t + 200, confidence=0.9))
        else:
            raw.append(VoiceWordTimestamp(word=f"w{i}", start_ms=t, end_ms=t + 400, confidence=0.9))
        t += 400
    # normalised: 10 words at 240, 640, 1040, ... ; scenes start at normalised words 0, 4, 7
    norm_start = [240 + 400 * i for i in range(10)]
    scenes = [
        scene("1", duration_s=1.6, start_word=0, end_word=3, start_ms=norm_start[0], voiceover_line="a"),
        scene("2", duration_s=1.2, start_word=4, end_word=6, start_ms=norm_start[4], voiceover_line="b"),
        scene("3", duration_s=1.2, start_word=7, end_word=9, start_ms=norm_start[7], voiceover_line="c"),
    ]
    return storyboard(scenes), manifest(scenes), raw


@pytest.mark.asyncio
async def test_golden_contraction_heavy_script():
    """Scene cuts for a script whose Deepgram words include contraction splits.

    Pinned BEFORE the word-index fix; the fix intentionally changes this golden
    (scene 2 and 3 begin on the storyboard's words, not the raw list's).
    """
    sb, mf, raw = _contraction_run()
    script = await render_script(sb, mf, alignment=raw, inputs=PORTRAIT)
    check_golden("contraction_heavy", script)
