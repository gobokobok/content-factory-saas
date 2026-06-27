"""RenderWorker (P9-S4) — asset_manifest + voice_alignment → render_script.sh + final.mp4.

Reads render_options per scene to drive all render decisions (film_look, lower_third,
on_screen_text_overlay, caption_y_override). Persists render_script.sh to R2 before
FFmpeg execution so it is always available for debugging.
"""

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.acquisition_worker import AssetManifestArtifact
from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
from cf_platform.workers.voice_production import VoiceAlignmentArtifact

logger = logging.getLogger(__name__)

# Sepia film-look filter chain applied per-scene before concat.
_FILM_LOOK_FILTER = (
    "hqdn3d=3:2:6:4,"
    "noise=alls=8:allf=t,"
    "colorchannelmixer="
    "rr=0.393:rg=0.769:rb=0.189:"
    "gr=0.349:gg=0.686:gb=0.168:"
    "br=0.272:bg=0.534:bb=0.131,"
    "eq=saturation=0.4"
)

# ASS PlayResY for 1080×1920 — used to convert frame-y to MarginV.
_PLAY_RES_Y = 1920

RENDER_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="none",
    prompt="",
    model="none",
    sampling_params={},
)


class RenderArtifact(BaseModel):
    """Terminal artifact of the RenderWorker."""

    render_script_key: str
    video_key: str
    scene_count: int
    duration_s: float
    generated_at: datetime


# ── Render-script helpers ─────────────────────────────────────────────────────


def _film_look_section(storyboard) -> Optional[str]:
    """In-place sepia commands for scenes with render_options.film_look=True.

    Runs BEFORE the concat step so only the affected clips carry the filter.
    Each command overwrites scene_NN.mp4 in-place via a temp file.
    """
    cmds: list[str] = []
    for i, scene in enumerate(storyboard.scenes, 1):
        if scene.render_options and scene.render_options.film_look:
            n = f"{i:02d}"
            cmds.append(
                f"# Film look: scene {n} ({scene.scene})\n"
                f'ffmpeg -y -i "$WORK/scene_{n}.mp4" \\\n'
                f'  -vf "{_FILM_LOOK_FILTER}" \\\n'
                "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
                f'  "$WORK/scene_{n}_fl.mp4"\n'
                f'mv "$WORK/scene_{n}_fl.mp4" "$WORK/scene_{n}.mp4"'
            )
    if not cmds:
        return None
    return (
        "# ── Film look (per-scene sepia) ─────────────────────────────\n"
        + "\n\n".join(cmds)
    )


def _build_captions_with_y_override(
    scene_words: list,
    storyboard_scenes: list,
    subtitle_style: str,
    play_res_y: int = _PLAY_RES_Y,
) -> str:
    """Word-synced ASS captions with per-scene MarginV for lower_third scenes.

    For each scene that has render_options.lower_third.caption_y_override set,
    the ASS Dialogue events for that scene are emitted with
    MarginV = _PLAY_RES_Y - caption_y_override so the caption baseline shifts
    up to clear the lower-third band.  0 in all other events means "use style
    default", which is the normal TikTok/Classic bottom position.
    """
    from src.captions import _captions_header, format_ass_time

    _CHUNK_SIZE = 5

    margin_overrides: list[Optional[int]] = []
    for scene in storyboard_scenes:
        if (
            scene.render_options
            and scene.render_options.lower_third
            and scene.render_options.lower_third.caption_y_override
        ):
            y = scene.render_options.lower_third.caption_y_override
            margin_overrides.append(play_res_y - y)
        else:
            margin_overrides.append(None)

    events: list[str] = []
    for idx, words in enumerate(scene_words):
        if not words:
            continue
        mv = margin_overrides[idx] if idx < len(margin_overrides) else None
        margin_v = mv if mv is not None else 0

        chunks = [words[j : j + _CHUNK_SIZE] for j in range(0, len(words), _CHUNK_SIZE)]
        for j, chunk in enumerate(chunks):
            next_chunk = chunks[j + 1] if j + 1 < len(chunks) else None
            chunk_texts = [w.word for w in chunk]
            for k, word_ts in enumerate(chunk):
                before = chunk_texts[:k]
                active = "{\\c&H0000FFFF&}" + word_ts.word + "{\\c&H00FFFFFF&}"
                after = chunk_texts[k + 1 :]
                text = " ".join(before + [active] + after)
                start_s = word_ts.start_ms / 1000.0
                if k + 1 < len(chunk):
                    end_s = chunk[k + 1].start_ms / 1000.0
                elif next_chunk:
                    end_s = next_chunk[0].start_ms / 1000.0
                else:
                    end_s = word_ts.end_ms / 1000.0
                events.append(
                    f"Dialogue: 0,{format_ass_time(start_s)},{format_ass_time(end_s)},"
                    f"VoiceCaption,,0,0,{margin_v},,{text}"
                )

    header = _captions_header(subtitle_style)
    if events:
        return header + "\n".join(events) + "\n"
    return header


def _escape_drawtext(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter value.

    Order matters: backslash first, then bash $ (prevents shell interpolation),
    then FFmpeg-specific chars. Unicode arrows/dashes are normalised to ASCII
    because Poppins does not contain these glyphs and renders them as boxes.
    """
    text = (
        text.replace("→", "->")
        .replace("←", "<-")
        .replace("↑", "^")
        .replace("↓", "v")
        .replace("–", "-")
        .replace("—", "-")
        .replace("…", "...")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    return (
        text.replace("\\", "\\\\")
        .replace("$", "\\$")
        .replace("'", "\\'")
        .replace(":", "\\:")
    )


def _pad_video_to_audio_duration(video_source: str) -> str:
    """Extend the last frame of the video to match voiceover duration.

    When scene duration_s values sum to less than the actual TTS audio length
    (they often do because TTS pace varies), the final frame freezes while
    audio plays on. This step measures both durations at runtime and applies
    tpad=stop_mode=clone to freeze-extend the video cleanly.

    Uses $VO (set by _voiceover_check) rather than a hardcoded path so the
    correct voiceover file is always probed regardless of filename/extension.
    """
    return (
        "# ── Pad video to match voiceover duration ───────────────────\n"
        f'_VID_DUR=$(ffprobe -v quiet -print_format json -show_format "{video_source}" \\\n'
        "  | python3 -c \"import sys,json; print(json.load(sys.stdin)['format']['duration'])\" 2>/dev/null || echo 0)\n"
        '_VO_DUR=$(ffprobe -v quiet -print_format json -show_format "$VO" \\\n'
        "  | python3 -c \"import sys,json; print(json.load(sys.stdin)['format']['duration'])\" 2>/dev/null || echo 0)\n"
        '_PAD=$(python3 -c "v=float(\'$_VID_DUR\'); a=float(\'$_VO_DUR\'); print(max(0.0, a - v))")\n'
        'echo "Pad: video=${_VID_DUR}s  vo=${_VO_DUR}s  pad=${_PAD}s"\n'
        'if python3 -c "import sys; sys.exit(0 if float(\'$_PAD\') > 0.1 else 1)"; then\n'
        f'  ffmpeg -y -i "{video_source}" \\\n'
        '    -vf "tpad=stop=-1:stop_mode=clone:stop_duration=$_PAD" \\\n'
        "    -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p \\\n"
        '    "$WORK/video_padded.mp4"\n'
        "else\n"
        f'  cp "{video_source}" "$WORK/video_padded.mp4"\n'
        "fi"
    )


def _overlay_section(storyboard, video_source: str) -> tuple[str, str]:
    """Single ffmpeg pass with drawtext filters for lower_third + on_screen_text_overlay.

    Returns (section_str, new_video_source). Returns ('', video_source) when no scene
    has render_options with a lower_third or on_screen_text_overlay set.
    """
    filters: list[str] = []
    t_offset = 0.0

    for scene in storyboard.scenes:
        opts = scene.render_options
        if opts:
            scene_start = t_offset
            scene_end = t_offset + scene.duration_s
            enable = f"between(t,{scene_start:.3f},{scene_end:.3f})"

            if opts.lower_third:
                lt = opts.lower_third
                name = _escape_drawtext(lt.name)
                filters.append(
                    f"drawtext=text='{name}':fontfile=/usr/local/share/fonts/Poppins-Bold.ttf"
                    f":fontsize=34:fontcolor=white"
                    f":x=(w-text_w)/2:y=h-text_h-220:enable='{enable}'"
                )
                if lt.title:
                    title = _escape_drawtext(lt.title)
                    filters.append(
                        f"drawtext=text='{title}':fontfile=/usr/local/share/fonts/Poppins-Regular.ttf"
                        f":fontsize=26:fontcolor=white@0.85"
                        f":x=(w-text_w)/2:y=h-text_h-270:enable='{enable}'"
                    )

            if opts.on_screen_text_overlay:
                ost = opts.on_screen_text_overlay
                text = _escape_drawtext(ost.text.upper())
                filters.append(
                    f"drawtext=text='{text}':fontfile=/usr/local/share/fonts/Poppins-Bold.ttf"
                    f":fontsize=60:fontcolor=white"
                    f":box=1:boxcolor=black@0.55:boxborderw=18"
                    f":x=max(40\\,(w-text_w)/2):y=(h-text_h)/2:enable='{enable}'"
                )

        t_offset += scene.duration_s

    if not filters:
        return "", video_source

    combined = ",\\\n  ".join(filters)
    new_source = "$WORK/video_overlaid.mp4"
    section = (
        "# ── Overlays: lower_third + on_screen_text ─────────────────\n"
        f'ffmpeg -y -i "{video_source}" \\\n'
        f'  -vf "{combined}" \\\n'
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
        f'  "{new_source}"'
    )
    return section, new_source


def _collect_overlay_filters(storyboard) -> list[str]:
    """Return drawtext filter strings for lower_third + on_screen_text overlays.

    Used by _build_render_script to merge overlay rendering into the single
    post-processing FFmpeg pass rather than a separate invocation.
    """
    filters: list[str] = []
    t_offset = 0.0
    for scene in storyboard.scenes:
        opts = scene.render_options
        if opts:
            scene_start = t_offset
            scene_end = t_offset + scene.duration_s
            enable = f"between(t,{scene_start:.3f},{scene_end:.3f})"
            if opts.lower_third:
                lt = opts.lower_third
                name = _escape_drawtext(lt.name)
                filters.append(
                    f"drawtext=text='{name}':fontfile=/usr/local/share/fonts/Poppins-Bold.ttf"
                    f":fontsize=34:fontcolor=white"
                    f":x=(w-text_w)/2:y=h-text_h-220:enable='{enable}'"
                )
                if lt.title:
                    title = _escape_drawtext(lt.title)
                    filters.append(
                        f"drawtext=text='{title}':fontfile=/usr/local/share/fonts/Poppins-Regular.ttf"
                        f":fontsize=26:fontcolor=white@0.85"
                        f":x=(w-text_w)/2:y=h-text_h-270:enable='{enable}'"
                    )
            if opts.on_screen_text_overlay:
                ost = opts.on_screen_text_overlay
                text = _escape_drawtext(ost.text.upper())
                filters.append(
                    f"drawtext=text='{text}':fontfile=/usr/local/share/fonts/Poppins-Bold.ttf"
                    f":fontsize=60:fontcolor=white"
                    f":box=1:boxcolor=black@0.55:boxborderw=18"
                    f":x=max(40\\,(w-text_w)/2):y=(h-text_h)/2:enable='{enable}'"
                )
        t_offset += scene.duration_s
    return filters


def _build_render_script(
    run_id: str,
    storyboard,
    manifest,
    scene_words: Optional[list],
    color_grade_preset: str,
    blur_fill_enabled: bool,
    format_track: str = "portrait",
) -> str:
    """Assemble the complete render bash script with render_options extensions.

    Calls private helpers from src.ffmpeg_builder for base structure, then inserts
    film_look passes (before concat), overlays (after captions/grade), and wires
    caption y-overrides for lower_third scenes.

    `format_track` selects the output resolution: portrait → 1080×1920 (Shorts),
    landscape → 1920×1080 (standard YouTube).
    """
    from src.captions import build_captions_ass
    from src.ffmpeg_builder import (
        _audio_section,
        _debug_section,
        _filter_complex_concat,
        _get_color_grade_filter,
        _header,
        _music_check,
        _preamble,
        _scene_section,
        _voiceover_check,
        _write_voiceover_captions_ass,
    )
    from src.models import VideoSettings

    video_settings = VideoSettings()
    audio = video_settings.audio
    subtitles = video_settings.subtitles
    if format_track == "landscape":
        out_w, out_h = 1920, 1080
    else:
        out_w, out_h = 1080, 1920
    entries = {e.scene_id: e for e in manifest.entries}
    n_scenes = len(manifest.entries)

    parts = [
        _header(run_id, n_scenes, storyboard.summary.total_duration_s),
        _preamble(run_id),
        _voiceover_check(),
        _music_check(audio),
        _debug_section(),
        _scene_section(storyboard, entries, run_id, out_w, out_h, blur_fill_enabled=blur_fill_enabled),
    ]

    # Film look: per-scene sepia applied BEFORE concat so only affected clips carry it
    film_part = _film_look_section(storyboard)
    if film_part:
        parts.append(film_part)

    parts.append(_filter_complex_concat(n_scenes))

    # Pad BEFORE captions so captions beyond the raw clip duration burn onto the
    # freeze-extended frames rather than being silently dropped.
    parts.append(_pad_video_to_audio_duration("$WORK/video_only.mp4"))

    # Merge captions + colour grade + overlays into a single FFmpeg pass.
    # Running them as separate passes meant 3 full decode+encode cycles over the
    # full video duration. A chained -vf filter handles all three in one pass.
    post_vf: list[str] = []

    if subtitles != "none":
        if scene_words:
            ass_content = _build_captions_with_y_override(
                scene_words, storyboard.scenes, subtitles, play_res_y=out_h
            )
        else:
            ass_content = build_captions_ass(storyboard.scenes, subtitle_style=subtitles)
        parts.append(_write_voiceover_captions_ass(ass_content))
        post_vf.append("ass=$WORK/voiceover_captions.ass")

    grade_filter = _get_color_grade_filter(color_grade_preset)
    if grade_filter:
        post_vf.append(grade_filter)

    post_vf.extend(_collect_overlay_filters(storyboard))

    if post_vf:
        combined = ",\\\n  ".join(post_vf)
        parts.append(
            "# ── Post-process: captions + grade + overlays (single pass) ─\n"
            'ffmpeg -y \\\n'
            '  -i "$WORK/video_padded.mp4" \\\n'
            f'  -vf "{combined}" \\\n'
            "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
            '  "$WORK/video_postproc.mp4"'
        )
        video_source = "$WORK/video_postproc.mp4"
    else:
        video_source = "$WORK/video_padded.mp4"

    parts.append(_audio_section(storyboard, audio, video_source=video_source))
    parts.append(f'echo "Done: /tmp/{run_id}/output/final.mp4"')

    return "\n\n".join(parts) + "\n"


# ── Asset download ────────────────────────────────────────────────────────────


async def _download_assets(run_id: str, manifest, storage: ArtifactStorage) -> None:
    """Download all acquired scene assets and voiceover/music/sfx files to /tmp/{run_id}/."""
    from src.ffmpeg_builder import _local_path

    for entry in manifest.entries:
        if entry.file_key:
            local = Path(_local_path(run_id, entry.file_key))
            local.parent.mkdir(parents=True, exist_ok=True)
            data = await storage.get_bytes(entry.file_key)
            local.write_bytes(data)

    for subfolder in ("voiceover", "music", "sfx"):
        prefix = f"runs/{run_id}/{subfolder}/"
        for key in await storage.list_keys(prefix):
            local = Path(_local_path(run_id, key))
            local.parent.mkdir(parents=True, exist_ok=True)
            data = await storage.get_bytes(key)
            local.write_bytes(data)


# ── Worker factory ────────────────────────────────────────────────────────────


def build_render_worker(
    storage: ArtifactStorage,
    color_grade_preset: str = "neutral",
    blur_fill_enabled: bool = True,
    ffmpeg_timeout_seconds: int = 1800,
) -> WorkerNode:
    """Build the native RenderWorker node.

    Reads verified_storyboard, asset_manifest, and optionally voice_alignment
    from state.artifacts. Applies render_options per scene — all render decisions
    come from render_options fields. Persists render_script.sh before execution; uploads final.mp4.

    Args:
        storage: artifact storage for R2 reads/writes.
        color_grade_preset: FFmpeg colour grade preset name (default "neutral").
        blur_fill_enabled: whether to blur-fill portrait stills (default True).
        ffmpeg_timeout_seconds: subprocess timeout in seconds (default 1800).
    """
    from src.ffmpeg_builder import (
        assign_words_to_scenes,
        compute_scene_durations_from_alignment,
        fill_caption_gaps,
        redistribute_scene_durations,
    )
    from src.models import AssetManifest, Storyboard, WordTimestamp

    async def _worker(state: StageState) -> WorkerOutput:
        """Build render script, download assets, execute FFmpeg, upload final.mp4."""
        run_id = state.run_id

        # Read verified storyboard
        _, sb_body = await read_artifact(storage, state.artifacts["verified_storyboard"])
        sb_art = VerifiedStoryboardArtifact.model_validate(sb_body)
        storyboard = Storyboard.model_validate(sb_art.storyboard)

        # Read asset manifest
        _, mf_body = await read_artifact(storage, state.artifacts["asset_manifest"])
        mf_art = AssetManifestArtifact.model_validate(mf_body)
        manifest = AssetManifest.model_validate(mf_art.manifest)

        # Read voice alignment (optional)
        scene_words: Optional[list] = None
        if "voice_alignment" in state.artifacts:
            try:
                _, va_body = await read_artifact(
                    storage, state.artifacts["voice_alignment"]
                )
                va = VoiceAlignmentArtifact.model_validate(va_body)
                if va.word_timestamps:
                    src_timestamps = [
                        WordTimestamp(
                            word=w.word,
                            start_ms=w.start_ms,
                            end_ms=w.end_ms,
                            confidence=w.confidence,
                        )
                        for w in va.word_timestamps
                    ]
                    if va.alignment_method == "deepgram_nova2":
                        # Two-pass assignment so word windows are accurate even when
                        # estimated storyboard durations differ from actual VO pace.
                        # Pass 1: assign using estimated durations → rough aligned durations
                        words_pass1 = assign_words_to_scenes(storyboard.scenes, src_timestamps)
                        adjusted_pass1 = compute_scene_durations_from_alignment(
                            storyboard.scenes, words_pass1
                        )
                        # Pass 2: assign using aligned durations → tight word windows
                        scenes_pass1 = storyboard.model_copy(
                            update={"scenes": adjusted_pass1}
                        ).scenes
                        raw_scene_words = assign_words_to_scenes(scenes_pass1, src_timestamps)
                        adjusted = compute_scene_durations_from_alignment(
                            scenes_pass1, raw_scene_words
                        )
                    else:
                        raw_scene_words = assign_words_to_scenes(
                            storyboard.scenes, src_timestamps
                        )
                        adjusted = redistribute_scene_durations(
                            storyboard.scenes, va.total_duration_s
                        )
                    storyboard = storyboard.model_copy(update={"scenes": adjusted})
                    scene_words = fill_caption_gaps(storyboard.scenes, raw_scene_words)

                if va.mp3_r2_key:
                    ext = Path(va.mp3_r2_key).suffix or ".mp3"
                    vo_local = Path(f"/tmp/{run_id}/voiceover/voiceover{ext}")
                    vo_local.parent.mkdir(parents=True, exist_ok=True)
                    vo_data = await storage.get_bytes(va.mp3_r2_key)
                    vo_local.write_bytes(vo_data)
            except Exception as exc:
                logger.warning(
                    "RenderWorker: could not load voice_alignment for run %s: %s", run_id, exc
                )

        # Build render script
        format_track: str = state.inputs.get("format_track", "landscape")
        script_content = _build_render_script(
            run_id=run_id,
            storyboard=storyboard,
            manifest=manifest,
            scene_words=scene_words,
            color_grade_preset=color_grade_preset,
            blur_fill_enabled=blur_fill_enabled,
            format_track=format_track,
        )

        # Persist render_script.sh to R2 BEFORE execution for debuggability
        script_key = f"runs/{run_id}/render_script.sh"
        await storage.put_bytes(
            script_key, script_content.encode("utf-8"), content_type="text/plain"
        )
        logger.info("RenderWorker: render_script.sh written → %s", script_key)

        # Download all scene assets to /tmp/{run_id}/
        await _download_assets(run_id, manifest, storage)

        # Write and chmod the local script
        local_script = Path(f"/tmp/{run_id}/render_script.sh")
        local_script.parent.mkdir(parents=True, exist_ok=True)
        local_script.write_bytes(script_content.encode("utf-8"))
        local_script.chmod(0o755)

        # Execute FFmpeg render
        result = await asyncio.to_thread(
            subprocess.run,
            [str(local_script)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=ffmpeg_timeout_seconds,
        )

        # Persist FFmpeg log regardless of exit code
        log_key = f"runs/{run_id}/ffmpeg_log.txt"
        try:
            log_bytes = (result.stdout + result.stderr).encode("utf-8", errors="replace")
            await storage.put_bytes(log_key, log_bytes, content_type="text/plain")
        except Exception as log_exc:
            logger.warning("RenderWorker: failed to write ffmpeg_log.txt: %s", log_exc)

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg exited {result.returncode} for run {run_id}. "
                f"Check R2 key {log_key!r} for details."
            )

        # Upload final.mp4 to R2
        output_path = Path(f"/tmp/{run_id}/output/final.mp4")
        if not output_path.exists():
            raise RuntimeError(f"final.mp4 not produced after render for run {run_id}")

        video_key = f"runs/{run_id}/output/final.mp4"
        await storage.put_bytes(
            video_key, output_path.read_bytes(), content_type="video/mp4"
        )
        logger.info("RenderWorker: final.mp4 uploaded → %s", video_key)

        shutil.rmtree(f"/tmp/{run_id}", ignore_errors=True)

        return WorkerOutput(
            artifact=RenderArtifact(
                render_script_key=script_key,
                video_key=video_key,
                scene_count=len(storyboard.scenes),
                duration_s=storyboard.summary.total_duration_s,
                generated_at=datetime.now(timezone.utc),
            )
        )

    return _worker
