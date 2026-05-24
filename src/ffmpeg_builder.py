"""FFmpeg shell script generator — assembles storyboard assets into a 9:16 YouTube Short."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.captions import build_ass, build_captions_ass
from src.exceptions import FFmpegBuildError
from src.models import AssetManifest, ManifestEntry, Storyboard, StoryboardScene

_FPS = 25
_OUT_W = 1080
_OUT_H = 1920
_MUSIC_VOL = 0.15


_MIN_SCENE_DURATION_S = 0.5


def get_audio_duration(path: Path) -> float:
    """
    Measure audio file duration in seconds using ffprobe.

    Raises FFmpegBuildError if ffprobe exits non-zero or the output cannot be parsed.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise FFmpegBuildError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise FFmpegBuildError(f"Could not parse ffprobe output for {path}: {exc}") from exc


def redistribute_scene_durations(
    scenes: list[StoryboardScene], audio_duration: float
) -> list[StoryboardScene]:
    """
    Return new StoryboardScene instances with duration_s scaled to match audio_duration.

    Word count of voiceover_line is used as the proportional weight per scene.
    Scenes with no words are assigned weight 1 so they still receive a slice.
    Each resulting duration is floored at _MIN_SCENE_DURATION_S.
    """
    weights = [max(1, len(s.voiceover_line.split())) for s in scenes]
    total_weight = sum(weights)
    return [
        scene.model_copy(
            update={"duration_s": max(_MIN_SCENE_DURATION_S, round(audio_duration * w / total_weight, 2))}
        )
        for scene, w in zip(scenes, weights)
    ]


def build_ffmpeg_script(run_id: str, storyboard: Storyboard, manifest: AssetManifest) -> str:
    """
    Build a self-contained bash script that assembles the run's assets into a 9:16 Short.

    Raises FFmpegBuildError if any scene lacks an acquired asset (file_key is None).
    """
    entries: dict[str, ManifestEntry] = {e.scene_id: e for e in manifest.entries}

    for scene in storyboard.scenes:
        entry = entries.get(scene.scene)
        if entry is None or entry.file_key is None:
            raise FFmpegBuildError(
                f"Scene '{scene.scene}' has no acquired asset — run asset acquisition first"
            )

    total_s = storyboard.summary.total_duration_s
    n_scenes = len(manifest.entries)
    ass_content = build_ass(storyboard.scenes)
    captions_ass_content = build_captions_ass(storyboard.scenes)

    parts = [
        _header(run_id, n_scenes, total_s),
        _preamble(run_id),
        _voiceover_check(),
        _music_check(),
        _debug_section(),
        _scene_section(storyboard, entries, run_id),
        _filter_complex_concat(n_scenes),
        _write_captions_ass(ass_content),
        _burn_captions(),
        _write_voiceover_captions_ass(captions_ass_content),
        _burn_voiceover_captions(),
        _audio_section(storyboard),
        f'echo "Done: /tmp/{run_id}/output/final.mp4"',
    ]
    return "\n\n".join(parts) + "\n"


# ── Section builders ──────────────────────────────────────────────────────────


def _header(run_id: str, n_scenes: int, total_s: float) -> str:
    """Generate the comment header block with run metadata."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "#!/bin/bash\n"
        "# ============================================================\n"
        "# Content Factory — FFmpeg assembly script\n"
        f"# run_id:          {run_id}\n"
        f"# generated_at:    {generated_at}\n"
        f"# scenes:          {n_scenes}\n"
        f"# total_duration:  {total_s:.1f}s\n"
        "# ============================================================\n"
        "set -euo pipefail"
    )


def _preamble(run_id: str) -> str:
    """Declare BASE and WORK variables and create required directories."""
    return (
        f'BASE="/tmp/{run_id}"\n'
        'WORK="$BASE/work"\n'
        'mkdir -p "$WORK" "$BASE/output"'
    )


def _voiceover_check() -> str:
    """
    Abort with a clear error if no voiceover audio file is present.

    Uses a glob loop instead of ls | head -1 so the check is safe under
    set -euo pipefail: ls *.mp3 with no matches exits non-zero, which with
    pipefail propagates as a non-zero pipeline exit and silently kills the
    script via set -e before any error message is printed.
    Accepts .mp3, .wav, and .m4a.
    """
    return (
        "# ── Voiceover ─────────────────────────────────────────────\n"
        'VO=""\n'
        'for _vo_f in "$BASE/voiceover/"*.mp3 "$BASE/voiceover/"*.wav "$BASE/voiceover/"*.m4a; do\n'
        '  [ -f "$_vo_f" ] && { VO="$_vo_f"; break; }\n'
        "done\n"
        'if [ -z "$VO" ]; then\n'
        '  echo "ERROR: no audio file (.mp3/.wav/.m4a) found in $BASE/voiceover/ — upload voiceover before rendering" >&2\n'
        "  exit 1\n"
        "fi\n"
        'echo "Voiceover: $VO"'
    )


def _music_check() -> str:
    """
    Check for a background music file and set MUSIC_ARGS for the audio assembly step.

    If a music file (.mp3/.wav/.m4a) is found in $BASE/music/, MUSIC_ARGS is set
    to (-i "$MUSIC") so it is opened as a file input.
    If no music file is found, MUSIC_ARGS is set to (-f lavfi -i anullsrc=r=44100:cl=stereo)
    so the audio assembly uses a direct silence source without a fragile intermediate
    file generation step.  The intermediate _silence.mp3 approach is deliberately
    avoided: it requires a working libmp3lame encoder and an extra ffmpeg invocation
    that can fail silently under set -euo pipefail.
    """
    return (
        "# ── Background music ───────────────────────────────────────\n"
        'MUSIC=""\n'
        'for _m_f in "$BASE/music/"*.mp3 "$BASE/music/"*.wav "$BASE/music/"*.m4a; do\n'
        '  [ -f "$_m_f" ] && { MUSIC="$_m_f"; break; }\n'
        "done\n"
        'if [ -z "$MUSIC" ]; then\n'
        '  echo "WARNING: no music found in $BASE/music/ — rendering without background music"\n'
        '  MUSIC_ARGS=(-f lavfi -i anullsrc=r=44100:cl=stereo)\n'
        "else\n"
        '  MUSIC_ARGS=(-i "$MUSIC")\n'
        "fi\n"
        'echo "Music: ${MUSIC:-<none — using anullsrc silence>}"'
    )


def _debug_section() -> str:
    """
    Generate pre-flight diagnostics printed to stdout before any scene encoding.

    Output is captured by the renderer and written to run_log.txt regardless of
    exit code — giving visibility into missing files and the FFmpeg version on
    the target host. Uses || guards throughout so set -e never triggers here.
    """
    return (
        "# ── Pre-flight diagnostics ─────────────────────────────\n"
        'echo "=== PRE-FLIGHT CHECK ==="\n'
        'ffmpeg -version 2>&1 | head -1 || echo "ffmpeg not in PATH"\n'
        'echo "VO=$VO"\n'
        'test -f "$VO" && echo "VO: $(wc -c < "$VO") bytes" || echo "VO: NOT FOUND"\n'
        'echo "MUSIC=$MUSIC"\n'
        'test -f "$MUSIC" && echo "MUSIC: exists" || echo "MUSIC: NOT FOUND"\n'
        'echo "video/:  $(ls "$BASE/video/"  2>/dev/null || echo "(empty or missing)")"\n'
        'echo "images/: $(ls "$BASE/images/" 2>/dev/null || echo "(empty or missing)")"\n'
        'echo "=== END PRE-FLIGHT ==="'
    )


def _scene_section(
    storyboard: Storyboard, entries: dict[str, ManifestEntry], run_id: str
) -> str:
    """Generate one ffmpeg command per scene."""
    parts = ["# ── Per-scene processing ─────────────────────────────────"]
    for i, scene in enumerate(storyboard.scenes, 1):
        entry = entries[scene.scene]
        parts.append(_render_scene(scene, entry, run_id, i))
    return "\n\n".join(parts)


def _render_scene(
    scene: StoryboardScene, entry: ManifestEntry, run_id: str, num: int
) -> str:
    """Generate the ffmpeg command for a single scene segment."""
    local = _local_path(run_id, entry.file_key)  # type: ignore[arg-type]
    out = f'"$WORK/scene_{num:02d}.mp4"'
    if scene.clip_type == "hard_cut":
        return _render_video_scene(scene, local, out, num)
    return _render_image_scene(scene, local, out, num)


def _render_video_scene(
    scene: StoryboardScene, local: str, out: str, num: int
) -> str:
    """Trim and scale a video clip to the output portrait format."""
    vf = (
        f"scale={_OUT_W}:{_OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={_OUT_W}:{_OUT_H},setsar=1:1"
    )
    return (
        f"# Scene {num:02d} — {scene.scene} — hard_cut — {scene.duration_s}s\n"
        f'ffmpeg -y -i "{local}" \\\n'
        f"  -t {scene.duration_s} \\\n"
        f'  -vf "{vf}" \\\n'
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        f"  {out}"
    )


def _render_image_scene(
    scene: StoryboardScene, local: str, out: str, num: int
) -> str:
    """Animate a still image using zoompan and write it as a video segment."""
    frames = int(scene.duration_s * _FPS)
    clip_label = scene.clip_type
    if scene.motion_effect:
        clip_label += f" ({scene.motion_effect})"
    scale_vf = (
        f"scale={_OUT_W}:{_OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={_OUT_W}:{_OUT_H}"
    )
    zoompan_vf = _zoompan_filter(scene.clip_type, scene.motion_effect, frames)
    vf = f"{scale_vf},{zoompan_vf},setsar=1:1"
    return (
        f"# Scene {num:02d} — {scene.scene} — {clip_label} — {scene.duration_s}s\n"
        f"ffmpeg -y -loop 1 -framerate {_FPS} -i \"{local}\" \\\n"
        f"  -t {scene.duration_s} \\\n"
        f'  -vf "{vf}" \\\n'
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        f"  {out}"
    )


def _filter_complex_concat(n_scenes: int) -> str:
    """
    Concatenate scene segments via filter_complex instead of the concat demuxer.

    The concat demuxer copies bitstreams without resetting PTS, which causes
    non-monotonic DTS and progressive audio drift. Using the concat filter with
    explicit setpts=PTS-STARTPTS per clip normalises timestamps before joining.
    """
    input_lines = "\n".join(
        f'  -i "$WORK/scene_{i:02d}.mp4" \\'
        for i in range(1, n_scenes + 1)
    )
    setpts_parts = ";".join(
        f"[{i}:v]setpts=PTS-STARTPTS[v{i}]" for i in range(n_scenes)
    )
    concat_inputs = "".join(f"[v{i}]" for i in range(n_scenes))
    filter_complex = f"{setpts_parts};{concat_inputs}concat=n={n_scenes}:v=1:a=0[vout]"
    return (
        "# ── Concatenate scenes (filter_complex — no concat demuxer) ────\n"
        "ffmpeg -y \\\n"
        f"{input_lines}\n"
        f'  -filter_complex "{filter_complex}" \\\n'
        '  -map "[vout]" \\\n'
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        '  "$WORK/video_only.mp4"'
    )


def _write_captions_ass(ass_content: str) -> str:
    """
    Embed the ASS subtitle file into the script via a quoted heredoc.

    The single-quoted delimiter ('__ASS_EOF__') prevents bash from expanding
    $-variables, backticks, or ASS override-tag braces (e.g. {\\an8}) inside
    the heredoc body. The redirect target ("$WORK/captions.ass") is outside
    the heredoc and is still expanded correctly.
    """
    return (
        "# ── Write captions.ass ────────────────────────────────────\n"
        "cat << '__ASS_EOF__' > \"$WORK/captions.ass\"\n"
        + ass_content
        + "__ASS_EOF__"
    )


def _burn_captions() -> str:
    """Burn ASS subtitles into the concatenated video using the vf ass= filter."""
    return (
        "# ── Burn captions ─────────────────────────────────────────\n"
        "ffmpeg -y \\\n"
        "  -i \"$WORK/video_only.mp4\" \\\n"
        "  -vf \"ass=$WORK/captions.ass\" \\\n"
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        "  \"$WORK/video_captioned.mp4\""
    )


def _write_voiceover_captions_ass(ass_content: str) -> str:
    """
    Embed the voiceover captions ASS file into the script via a quoted heredoc.

    The single-quoted delimiter prevents bash from expanding $-variables or
    ASS override-tag braces inside the heredoc body.
    """
    return (
        "# ── Write voiceover_captions.ass ──────────────────────────\n"
        "cat << '__VCAP_EOF__' > \"$WORK/voiceover_captions.ass\"\n"
        + ass_content
        + "__VCAP_EOF__"
    )


def _burn_voiceover_captions() -> str:
    """Burn voiceover captions ASS into video_captioned.mp4, producing video_captioned2.mp4."""
    return (
        "# ── Burn voiceover captions ────────────────────────────────\n"
        "ffmpeg -y \\\n"
        "  -i \"$WORK/video_captioned.mp4\" \\\n"
        "  -vf \"ass=$WORK/voiceover_captions.ass\" \\\n"
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        "  \"$WORK/video_captioned2.mp4\""
    )


def _audio_section(storyboard: Storyboard) -> str:
    """
    Build the audio assembly ffmpeg command.

    SFX inputs are conditional: each file is checked for existence at runtime
    with [ -f "..." ] so the script runs correctly even when SFX files were
    not acquired (e.g. before Freesound integration is implemented).
    The filter_complex and amix input count are built dynamically in bash.
    """
    sfx_entries: list[tuple[str, int]] = []  # (sfx_name, delay_ms)
    offset_s = 0.0
    for scene in storyboard.scenes:
        if scene.sfx.lower() != "silence":
            delay_ms = _parse_sfx_delay_ms(scene.sfx_timing, scene.duration_s, offset_s)
            sfx_entries.append((scene.sfx, delay_ms))
        offset_s += scene.duration_s

    lines = [
        "# ── Audio assembly ─────────────────────────────────────────",
        "# SFX inputs are conditional — only include files present at render time",
        "_sfx_inputs=()",
        '_sfx_filters=""',
        '_sfx_labels=""',
        "_sfx_n=3",
        "_n_audio=2",
        "",
    ]

    for i, (sfx_name, delay_ms) in enumerate(sfx_entries):
        label = f"sfx{i}"
        lines.append(f'if [ -f "$BASE/sfx/{sfx_name}.mp3" ]; then')
        lines.append(f'  _sfx_inputs+=(-i "$BASE/sfx/{sfx_name}.mp3")')
        lines.append(f'  _sfx_filters="${{_sfx_filters}};[${{_sfx_n}}:a]adelay={delay_ms}|{delay_ms}[{label}]"')
        lines.append(f'  _sfx_labels="${{_sfx_labels}}[{label}]"')
        lines.append("  _sfx_n=$((_sfx_n + 1))")
        lines.append("  _n_audio=$((_n_audio + 1))")
        lines.append("fi")
        lines.append("")

    lines.extend([
        'ffmpeg -y \\',
        '  -i "$WORK/video_captioned2.mp4" \\',
        '  -i "$VO" \\',
        '  "${MUSIC_ARGS[@]}" \\',
        '  "${_sfx_inputs[@]}" \\',
        '  -filter_complex "[1:a]asetpts=PTS-STARTPTS,volume=1.0[vo];[2:a]asetpts=PTS-STARTPTS,volume=0.15[music]${_sfx_filters};[vo][music]${_sfx_labels}amix=inputs=${_n_audio}:duration=first:normalize=0[aout]" \\',
        '  -map 0:v -map "[aout]" \\',
        "  -c:v copy -c:a aac -b:a 192k \\",
        '  "$BASE/output/final.mp4"',
    ])

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _local_path(run_id: str, file_key: str) -> str:
    """Convert an R2 file key to the local /tmp path used during render."""
    prefix = f"runs/{run_id}/"
    relative = file_key[len(prefix):] if file_key.startswith(prefix) else file_key
    return f"/tmp/{run_id}/{relative}"


def _zoompan_filter(
    clip_type: str, motion_effect: Optional[str], frames: int
) -> str:
    """
    Return a zoompan filter expression for a still or animated clip.

    still_with_motion: gentle zoom in 1.0→1.05 (always centered).
    animated: pronounced 1.0→1.1 or 1.1→1.0 zoom, or 1.1x pan, driven by motion_effect.
    Unknown motion_effect falls back to zoom_in.
    """
    s = f"{_OUT_W}x{_OUT_H}"
    suffix = f":d={frames}:s={s}:fps={_FPS}"
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"

    if clip_type == "still_with_motion":
        return f"zoompan=z='1+0.05*on/{frames}':x='{cx}':y='{cy}'{suffix}"

    effect = (motion_effect or "zoom_in").lower().replace("-", "_")

    if effect == "zoom_in":
        return f"zoompan=z='1+0.1*on/{frames}':x='{cx}':y='{cy}'{suffix}"
    if effect == "zoom_out":
        return f"zoompan=z='1.1-0.1*on/{frames}':x='{cx}':y='{cy}'{suffix}"
    if effect == "pan_left":
        x = f"(iw-iw/zoom)*on/{frames}"
        return f"zoompan=z='1.1':x='{x}':y='{cy}'{suffix}"
    if effect == "pan_right":
        x = f"(iw-iw/zoom)*(1-on/{frames})"
        return f"zoompan=z='1.1':x='{x}':y='{cy}'{suffix}"

    # Unrecognised effect — fall back to zoom_in
    return f"zoompan=z='1+0.1*on/{frames}':x='{cx}':y='{cy}'{suffix}"


def _parse_sfx_delay_ms(sfx_timing: str, duration_s: float, scene_offset_s: float) -> int:
    """
    Return the adelay value in milliseconds for an SFX placed within a scene.

    Recognised sfx_timing values: "scene_start", "mid", "end", "<float>s".
    Unrecognised values default to scene_start.
    """
    timing = sfx_timing.strip().lower()
    if timing == "scene_start":
        within = 0.0
    elif timing == "mid":
        within = duration_s / 2
    elif timing == "end":
        within = max(0.0, duration_s - 0.5)
    elif timing.endswith("s"):
        try:
            within = float(timing[:-1])
        except ValueError:
            within = 0.0
    else:
        within = 0.0
    return max(0, int((scene_offset_s + within) * 1000))
