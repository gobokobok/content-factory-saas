"""FFmpeg shell script generator — assembles storyboard assets into a 9:16 YouTube Short."""

from datetime import datetime, timezone
from typing import Optional

from src.exceptions import FFmpegBuildError
from src.models import AssetManifest, ManifestEntry, Storyboard, StoryboardScene

_FPS = 25
_OUT_W = 1080
_OUT_H = 1920
_SCALED_W = _OUT_W * 2   # 2160 — upscaled source for zoompan headroom
_SCALED_H = _OUT_H * 2   # 3840
_MUSIC_VOL = 0.15


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
    n_scenes = storyboard.summary.total_scenes

    parts = [
        _header(run_id, n_scenes, total_s),
        _preamble(run_id),
        _voiceover_check(),
        _music_check(total_s),
        _scene_section(storyboard, entries, run_id),
        _concat_list(storyboard),
        _concat_command(),
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
    """Abort with a clear error if no voiceover .mp3 is present."""
    return (
        "# ── Voiceover ─────────────────────────────────────────────\n"
        'VO=$(ls "$BASE/voiceover/"*.mp3 2>/dev/null | head -1)\n'
        'if [ -z "$VO" ]; then\n'
        '  echo "ERROR: no .mp3 found in $BASE/voiceover/ — upload voiceover before rendering" >&2\n'
        "  exit 1\n"
        "fi\n"
        'echo "Voiceover: $VO"'
    )


def _music_check(total_s: float) -> str:
    """Warn and generate a silent placeholder if no background music .mp3 is present."""
    return (
        "# ── Background music ───────────────────────────────────────\n"
        'MUSIC=$(ls "$BASE/music/"*.mp3 2>/dev/null | head -1)\n'
        'if [ -z "$MUSIC" ]; then\n'
        '  echo "WARNING: no music found in $BASE/music/ — rendering without background music"\n'
        "  ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo \\\n"
        f"    -t {total_s:.1f} \\\n"
        "    -c:a libmp3lame -q:a 9 \\\n"
        '    "$BASE/music/_silence.mp3" \\\n'
        "    2>/dev/null\n"
        '  MUSIC="$BASE/music/_silence.mp3"\n'
        "fi\n"
        'echo "Music: $MUSIC"'
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
        f"crop={_OUT_W}:{_OUT_H}"
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
        f"scale={_SCALED_W}:{_SCALED_H}:force_original_aspect_ratio=increase,"
        f"crop={_SCALED_W}:{_SCALED_H}"
    )
    zoompan_vf = _zoompan_filter(scene.clip_type, scene.motion_effect, frames)
    vf = f"{scale_vf},{zoompan_vf}"
    return (
        f"# Scene {num:02d} — {scene.scene} — {clip_label} — {scene.duration_s}s\n"
        f"ffmpeg -y -loop 1 -framerate {_FPS} -i \"{local}\" \\\n"
        f"  -t {scene.duration_s} \\\n"
        f'  -vf "{vf}" \\\n'
        "  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -an \\\n"
        f"  {out}"
    )


def _concat_list(storyboard: Storyboard) -> str:
    """Write concat.txt with one entry per scene segment."""
    file_lines = "\n".join(
        f"file '$WORK/scene_{i:02d}.mp4'" for i in range(1, len(storyboard.scenes) + 1)
    )
    return (
        "# ── Concat list ─────────────────────────────────────────────\n"
        'cat > "$WORK/concat.txt" << CONCAT_EOF\n'
        f"{file_lines}\n"
        "CONCAT_EOF"
    )


def _concat_command() -> str:
    """Concatenate all scene segments into a single silent video."""
    return (
        "# ── Concatenate scenes ─────────────────────────────────────\n"
        "ffmpeg -y -f concat -safe 0 -i \"$WORK/concat.txt\" \\\n"
        "  -c copy \\\n"
        '  "$WORK/video_only.mp4"'
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
        '  -i "$WORK/video_only.mp4" \\',
        '  -i "$VO" \\',
        '  -i "$MUSIC" \\',
        '  "${_sfx_inputs[@]}" \\',
        '  -filter_complex "[1:a]volume=1.0[vo];[2:a]volume=0.15[music]${_sfx_filters};[vo][music]${_sfx_labels}amix=inputs=${_n_audio}:duration=first:normalize=0[aout]" \\',
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
