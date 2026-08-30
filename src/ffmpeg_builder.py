"""FFmpeg shell script generator — assembles storyboard assets into a 9:16 YouTube Short."""

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.alignment import proportional_fallback
from src.captions import build_captions_ass, build_word_synced_captions_ass
from src.exceptions import FFmpegBuildError
from src.models import (
    AssetManifest,
    AudioSettings,
    ManifestEntry,
    Storyboard,
    StoryboardScene,
    VideoSettings,
    WordTimestamp,
    normalize_motion_effect,
)

logger = logging.getLogger(__name__)

_FPS = 25
_OUT_W = 1080  # Default output width (9:16)
_OUT_H = 1920  # Default output height (9:16)
_DUCKING_FACTOR = 0.4  # Multiplier applied to music volume when ducking is enabled

_ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

# ── Colour grade presets (P8-S6) ──────────────────────────────────────────────

# Maps preset name → FFmpeg -vf filter string.  "neutral" is absent intentionally
# (no filter → output unchanged from source colours).
_COLOUR_GRADE_PRESETS: dict[str, str] = {
    "vivid": "eq=saturation=1.3:contrast=1.08",
    "warm": "colorchannelmixer=rr=1.08:bb=0.88,eq=saturation=1.1",
    "cinematic": "curves=m='0/10 128/118 245/235':s='0/0 255/255',eq=saturation=0.9",
    "muted": "eq=saturation=0.75:contrast=0.95:brightness=0.015",
}


def _get_color_grade_filter(preset: str) -> str | None:
    """Return the FFmpeg filter string for the given preset, or None for 'neutral'.

    Unknown presets log a warning and fall back to neutral (no filter).
    """
    if preset == "neutral":
        return None
    if preset in _COLOUR_GRADE_PRESETS:
        return _COLOUR_GRADE_PRESETS[preset]
    logger.warning(
        "Unknown COLOR_GRADE_PRESET %r — falling back to 'neutral' (no colour grade)", preset
    )
    return None


def _apply_color_grade(filter_str: str, video_source: str) -> str:
    """Generate the bash snippet that applies a colour-grade filter, writing video_graded.mp4."""
    return (
        "# ── Colour grade ─────────────────────────────────────────\n"
        "ffmpeg -y \\\n"
        f'  -i "{video_source}" \\\n'
        f'  -vf "{filter_str}" \\\n'
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
        '  "$WORK/video_graded.mp4"'
    )


def _dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    """Return (width, height) pixel dimensions for the given aspect ratio string."""
    return _ASPECT_DIMENSIONS.get(aspect_ratio, (_OUT_W, _OUT_H))


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


# Maximum number of Deepgram words to scan ahead when looking for the next
# voiceover token match. Bounds the damage from a single mismatched token
# (e.g. storyboard "zero point zero three" vs. Deepgram "point oh three") to
# a handful of skipped words instead of letting `pos` drift to a much later
# occurrence of a common word elsewhere in the transcript. See DECISIONS.md D045.
def assign_words_to_scenes(
    scenes: list[StoryboardScene],
    words: list[WordTimestamp],
) -> list[list[WordTimestamp]]:
    """
    Assign Deepgram words to storyboard scenes by timestamp.

    Builds cumulative scene time windows from scene.duration_s. Each word is placed in
    the scene whose [start_s, end_s) window contains word.start_ms / 1000. Words whose
    timestamp falls before the first window go to scene 0; words at or beyond the total
    duration go to the last scene.

    Caption text comes from word.word (the Deepgram transcript), not voiceover_line, so
    TTS numerals ("three") align correctly with script digits ("3").
    """
    if not scenes:
        return []
    if not words:
        return [[] for _ in scenes]

    n = len(scenes)
    # Build cumulative end-time boundaries for each scene
    scene_end: list[float] = []
    cumulative = 0.0
    for scene in scenes:
        cumulative += scene.duration_s
        scene_end.append(cumulative)

    result: list[list[WordTimestamp]] = [[] for _ in scenes]
    last = n - 1

    for word in words:
        t = word.start_ms / 1000.0
        # Find the first scene whose end boundary is strictly greater than t
        idx = last
        for i, end_t in enumerate(scene_end):
            if t < end_t:
                idx = i
                break
        result[idx].append(word)

    return result


# Minimum duration for an alignment-derived scene clip: 2 frames.
# Much smaller than _MIN_SCENE_DURATION_S (0.5 s) which is appropriate only
# for storyboard-only timing.  Applying the 0.5 s floor to alignment-computed
# durations causes cumulative lag when short hard-cut list items (e.g. a
# single spoken word) have a gap_based value below 500 ms.
_MIN_ALIGNED_DURATION_S: float = round(2.0 / _FPS, 3)  # ≈ 0.08 s at 25 fps


def compute_scene_durations_from_alignment(
    scenes: list[StoryboardScene],
    scene_words: list[list[WordTimestamp]],
) -> list[StoryboardScene]:
    """
    Return new StoryboardScene instances with duration_s derived from alignment timestamps.

    For all scenes except the last, duration is gap-based:
        duration_s = (first_word_start_ms[next_matched] - first_word_start_ms[N]) / 1000

    where *next_matched* is the first scene after N that has matched words.  Skipping
    over unmatched scenes in the look-ahead preserves the telescoping property even
    when the v0.9 coverage rule misses a scene edge case.

    The telescoping sum guarantees that every matched scene's visual start is locked
    to its VO anchor: cumulative lead = first_word_0 / 1000 (≈ 240 ms VO pre-silence),
    constant throughout the video.

    A speech-trail cap (_SPEECH_TRAIL_MS) was previously applied here to prevent
    orphan VO words from bloating the preceding scene's visual.  It was removed because:
    1. The cap fires on *intentional* natural pauses as well as orphan words.
    2. Each cap-firing permanently reduces the cumulative total, so the visual/VO
       drift grows scene-by-scene — reaching 4+ seconds of accumulated lead by the
       end of a 90-second video.
    3. The v0.9 storyboard prompt (COVERAGE RULE) eliminates orphan words at the
       source, so the cap was never needed.

    For the last matched scene (no further anchors):
        duration_s = (last_matched_word.end_ms - first_matched_word.start_ms) / 1000
    Scenes with no matched words retain their original duration_s.
    Unmatched scenes that fall between two matched scenes ("covered") are set to
    _MIN_ALIGNED_DURATION_S, and the preceding matched scene's gap-based duration
    is reduced by the same amount.  This keeps the total for that span equal to
    (T_next_matched - T_current) / 1000 — perfect telescoping even in the presence
    of unmatched scenes.

    Unmatched scenes that are NOT covered (e.g. after the last matched word) retain
    their original storyboard duration_s.

    Alignment-derived durations are floored at _MIN_ALIGNED_DURATION_S (≈ 0.08 s).
    """
    n = len(scenes)
    first_start_ms: list[int | None] = [
        (scene_words[i][0].start_ms if i < len(scene_words) and scene_words[i] else None)
        for i in range(n)
    ]

    # Pre-compute, for each scene, the index of the next scene with matched words.
    # Used both to derive the gap-based duration for matched scenes and to identify
    # unmatched scenes whose gap has already been "covered" by a preceding matched
    # scene's look-ahead (so they must not add extra time to the cumulative sum).
    next_matched_idx: list[int | None] = [None] * n
    for i in range(n):
        for j in range(i + 1, n):
            if first_start_ms[j] is not None:
                next_matched_idx[i] = j
                break

    # Identify unmatched scenes that are "covered" by a preceding matched scene's
    # look-ahead.  Scene k is covered when the last matched scene before k already
    # stretched its duration all the way to scene k's successor.
    covered: set[int] = set()
    for i in range(n):
        if first_start_ms[i] is not None and next_matched_idx[i] is not None:
            j = next_matched_idx[i]
            # All scenes strictly between i and j are unmatched (by construction of
            # next_matched_idx) and are now covered by scene i's look-ahead.
            for k in range(i + 1, j):
                covered.add(k)

    updated: list[StoryboardScene] = []
    for i, scene in enumerate(scenes):
        words_i = scene_words[i] if i < len(scene_words) else []

        if not words_i:
            if i in covered:
                # This scene's gap was already absorbed by the preceding matched
                # scene's look-ahead duration.  Give it the absolute minimum so
                # the cumulative sum stays locked to alignment anchors.
                updated.append(
                    scene.model_copy(update={"duration_s": _MIN_ALIGNED_DURATION_S})
                )
            else:
                # No preceding matched scene covered this gap — keep storyboard
                # duration (e.g. orphan scenes after the last matched word).
                updated.append(scene)
            continue

        j = next_matched_idx[i]
        if j is not None:
            # Gap-based: duration spans from this scene's first word to the next
            # matched scene's first word.  Subtract the minimal duration reserved
            # for any unmatched scenes between i and j so the total of scenes
            # i … j-1 telescopes exactly to (T_j - T_i) / 1000.
            n_covered = j - i - 1  # unmatched scenes between i and j
            raw_gap = (first_start_ms[j] - words_i[0].start_ms) / 1000.0  # type: ignore[operator]
            duration_s = raw_gap - n_covered * _MIN_ALIGNED_DURATION_S
        else:
            # No further matched scene — last segment; use speech span only.
            duration_s = (words_i[-1].end_ms - words_i[0].start_ms) / 1000.0

        updated.append(
            scene.model_copy(
                update={"duration_s": max(_MIN_ALIGNED_DURATION_S, round(duration_s, 3))}
            )
        )

    return updated


def fill_caption_gaps(
    scenes: list[StoryboardScene],
    scene_words: list[list[WordTimestamp]],
) -> list[list[WordTimestamp]]:
    """
    Inject filler captions for unmatched scenes whose audio gap was absorbed into a
    preceding matched scene (see compute_scene_durations_from_alignment's "covered"
    scenes).

    Those scenes get no Dialogue events from build_word_synced_captions_ass (their
    scene_words list is empty), so their voiceover_line text is appended as
    proportionally-timed filler words to the preceding matched scene's word list,
    spanning from that scene's last matched word to the next matched scene's first
    word. Returns a new scene_words list; does not mutate the input.
    """
    n = len(scenes)
    first_start_ms: list[int | None] = [
        scene_words[i][0].start_ms if i < len(scene_words) and scene_words[i] else None
        for i in range(n)
    ]
    next_matched_idx: list[int | None] = [None] * n
    for i in range(n):
        for j in range(i + 1, n):
            if first_start_ms[j] is not None:
                next_matched_idx[i] = j
                break

    result = [list(words) for words in scene_words]

    for i in range(n):
        j = next_matched_idx[i]
        if first_start_ms[i] is None or j is None or not result[i]:
            continue
        gap_text = " ".join(
            scenes[k].voiceover_line.strip() for k in range(i + 1, j) if scenes[k].voiceover_line.strip()
        )
        if not gap_text:
            continue
        gap_start_ms = result[i][-1].end_ms
        gap_duration_s = (first_start_ms[j] - gap_start_ms) / 1000.0
        if gap_duration_s <= 0:
            continue
        result[i].extend(
            WordTimestamp(
                word=w.word,
                start_ms=w.start_ms + gap_start_ms,
                end_ms=w.end_ms + gap_start_ms,
                confidence=0.0,
            )
            for w in proportional_fallback(gap_text, gap_duration_s)
        )

    return result


def build_ffmpeg_script(
    run_id: str,
    storyboard: Storyboard,
    manifest: AssetManifest,
    scene_words: list[list[WordTimestamp]] | None = None,
    audio: AudioSettings | None = None,
    video_settings: VideoSettings | None = None,
    color_grade_preset: str = "neutral",
    blur_fill_enabled: bool = True,
) -> str:
    """
    Build a self-contained bash script that assembles the run's assets into a Short.

    video_settings controls:
      - aspect_ratio: output dimensions (9:16 → 1080×1920, 16:9 → 1920×1080, 1:1 → 1080×1080)
      - subtitles: 'TikTok' or 'Classic' selects ASS style; 'none' skips caption burn steps
      - audio: music volume, ducking, and loop/fit playback mode
    audio kwarg is still accepted for backwards compat; video_settings.audio takes precedence
    when video_settings is provided.

    color_grade_preset: one of neutral|vivid|warm|cinematic|muted (COLOR_GRADE_PRESET env var).
    blur_fill_enabled: when True, landscape still images use blur-fill compositing (BLUR_FILL_ENABLED).

    When scene_words is provided (Deepgram words grouped per scene), captions use
    word-level sync with the active word highlighted in yellow.  Falls back to
    scene-boundary captions derived from voiceover_line when no alignment data is available.
    Raises FFmpegBuildError if any scene lacks an acquired asset (file_key is None).
    """
    if video_settings is None:
        video_settings = VideoSettings()
    # audio kwarg wins when passed directly; otherwise derive from video_settings
    if audio is None:
        audio = video_settings.audio

    out_w, out_h = _dimensions_for_aspect_ratio(video_settings.aspect_ratio)
    subtitles = video_settings.subtitles
    subtitle_style = subtitles  # "TikTok" or "Classic" (ignored when "none")

    entries: dict[str, ManifestEntry] = {e.scene_id: e for e in manifest.entries}

    for scene in storyboard.scenes:
        entry = entries.get(scene.scene)
        if entry is None or entry.file_key is None:
            raise FFmpegBuildError(
                f"Scene '{scene.scene}' has no acquired asset — run asset acquisition first"
            )

    total_s = storyboard.summary.total_duration_s
    n_scenes = len(storyboard.scenes)

    # on-screen text overlay (build_ass / _write_captions_ass / _burn_captions) is
    # intentionally unwired — kept for future rewiring when revisited.
    if subtitles != "none":
        if scene_words:
            captions_ass_content = build_word_synced_captions_ass(
                scene_words, subtitle_style=subtitle_style, aspect_ratio=video_settings.aspect_ratio
            )
        else:
            captions_ass_content = build_captions_ass(
                storyboard.scenes, subtitle_style=subtitle_style, aspect_ratio=video_settings.aspect_ratio
            )

    parts = [
        _header(run_id, n_scenes, total_s),
        _preamble(run_id),
        _voiceover_check(),
        _music_check(audio),
        _debug_section(),
        _scene_section(storyboard, entries, run_id, out_w, out_h, blur_fill_enabled=blur_fill_enabled),
        _filter_complex_concat(n_scenes),
    ]

    if subtitles != "none":
        parts.append(_write_voiceover_captions_ass(captions_ass_content))  # type: ignore[arg-type]
        parts.append(_burn_voiceover_captions())
        video_source = "$WORK/video_captioned.mp4"
    else:
        video_source = "$WORK/video_only.mp4"

    color_grade_filter = _get_color_grade_filter(color_grade_preset)
    if color_grade_filter:
        parts.append(_apply_color_grade(color_grade_filter, video_source))
        video_source = "$WORK/video_graded.mp4"

    parts.append(_audio_section(storyboard, audio, video_source=video_source))
    parts.append(f'echo "Done: /tmp/{run_id}/output/final.mp4"')
    return "\n\n".join(parts) + "\n"


# ── Section builders ──────────────────────────────────────────────────────────


def _header(run_id: str, n_scenes: int, total_s: float) -> str:
    """Generate the comment header block with run metadata."""
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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


def _music_check(audio: AudioSettings) -> str:
    """
    Check for a background music file and set MUSIC_ARGS for the audio assembly step.

    Playback mode is applied when a music file is found:
    - "loop": adds -stream_loop -1 before the file input so the track repeats until
      the voiceover ends (amix duration=first cuts the output at VO length).
    - "fit": plays the track once; if shorter than the VO, amix silence-pads the tail.
    If no music file is found, MUSIC_ARGS is set to (-f lavfi -i anullsrc=r=44100:cl=stereo)
    so the audio assembly uses a direct silence source without a fragile intermediate
    file generation step.  The intermediate _silence.mp3 approach is deliberately
    avoided: it requires a working libmp3lame encoder and an extra ffmpeg invocation
    that can fail silently under set -euo pipefail.
    """
    if audio.playback_mode == "loop":
        music_input_args = 'MUSIC_ARGS=(-stream_loop -1 -i "$MUSIC")'
    else:
        music_input_args = 'MUSIC_ARGS=(-i "$MUSIC")'
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
        f"  {music_input_args}\n"
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
    storyboard: Storyboard,
    entries: dict[str, ManifestEntry],
    run_id: str,
    out_w: int = _OUT_W,
    out_h: int = _OUT_H,
    blur_fill_enabled: bool = True,
) -> str:
    """Generate one ffmpeg command per scene, run in parallel with a concurrency cap."""
    cmds = []
    for i, scene in enumerate(storyboard.scenes, 1):
        entry = entries[scene.scene]
        cmds.append(_render_scene(scene, entry, run_id, i, out_w, out_h, blur_fill_enabled=blur_fill_enabled))

    # Run scene encodes in parallel (max 4 concurrent jobs) — large win for still images
    # since zoompan/scale per-frame processing is CPU-bound and mostly independent.
    lines = ["# ── Per-scene processing (parallel, ≤4 concurrent) ──────────"]
    lines.append("_JOBS=(); _MAX=4")
    lines.append("")
    for cmd in cmds:
        # Append & to run in background; track PID; drain queue when full
        bg_cmd = cmd.rstrip() + " &\n_JOBS+=($!)"
        lines.append(bg_cmd)
        lines.append(
            'if [ ${#_JOBS[@]} -ge $_MAX ]; then\n'
            '  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done\n'
            '  _JOBS=()\n'
            'fi'
        )
        lines.append("")
    lines.append('for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done')
    lines.append("unset _JOBS _MAX")
    return "\n".join(lines)


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _render_scene(
    scene: StoryboardScene,
    entry: ManifestEntry,
    run_id: str,
    num: int,
    out_w: int = _OUT_W,
    out_h: int = _OUT_H,
    blur_fill_enabled: bool = True,
) -> str:
    """Generate the ffmpeg command for a single scene segment.

    Routes by file extension rather than clip_type alone.  A person portrait photo
    (JPEG) may be acquired for a scene whose storyboard clip_type is "hard_cut";
    passing a JPEG to _render_video_scene would produce a ~1-frame clip.  The
    extension check ensures images always go through _render_image_scene regardless
    of the storyboard clip_type.
    """
    local = _local_path(run_id, entry.file_key)  # type: ignore[arg-type]
    out = f'"$WORK/scene_{num:02d}.mp4"'

    # Route by file extension: JPEG/PNG assets must always use the still-image path
    # even when clip_type="hard_cut" (e.g. Wikipedia portrait for a short scene).
    file_ext = Path(local).suffix.lower()
    is_image_file = file_ext in _IMAGE_EXTS

    if scene.clip_type == "hard_cut" and not is_image_file:
        return _render_video_scene(scene, local, out, num, out_w, out_h)

    # Blur-fill only for person portrait photos (source=wikimedia_person).
    is_person_photo = getattr(entry, "source", None) == "wikimedia_person"
    return _render_image_scene(
        scene, local, out, num, out_w, out_h,
        blur_fill_enabled=blur_fill_enabled and is_person_photo,
    )


def _render_video_scene(
    scene: StoryboardScene, local: str, out: str, num: int,
    out_w: int = _OUT_W, out_h: int = _OUT_H,
) -> str:
    """Trim and scale a video clip to the output dimensions, re-encoding at _FPS fps.

    Uses round(duration_s * _FPS) / _FPS as the -t value so the clip is an exact
    multiple of one frame.  This eliminates the one-frame-rounding error that arises
    when a non-frame-aligned float duration is passed to -t directly.

    -r {_FPS} converts the source video (commonly 30 fps from Pexels) to _FPS before
    the concat step so each per-scene clip carries the same frame rate.  Without this,
    the concat re-encoder receives mixed-fps inputs and the frame count (which
    determines clip duration in the final video) diverges from the intended duration.
    """
    vf = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1:1"
    )
    frames = round(scene.duration_s * _FPS)
    t_value = frames / _FPS
    return (
        f"# Scene {num:02d} — {scene.scene} — hard_cut — {scene.duration_s}s\n"
        f'ffmpeg -y -i "{local}" \\\n'
        f"  -t {t_value} \\\n"
        f'  -vf "{vf}" \\\n'
        # -r forces frame-rate conversion from source fps (e.g. 30) to _FPS (25),
        # ensuring the encoded clip has exactly `frames` frames.
        f"  -r {_FPS} \\\n"
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
        # Force the MP4 video track timescale to 1/25 so all per-scene clips share
        # an identical tbn.  Without this flag libx264 writes the container tbn
        # derived from the SOURCE clip (Pexels videos arrive with 12800, 15360, 30000
        # etc.).  Mixed-tbn clips confuse the concat demuxer's PTS accumulation and
        # produce wrong frame durations in the concatenated output (visually: freeze,
        # extra-long video, or frame-duplicated video).
        "  -video_track_timescale 25 \\\n"
        f"  {out}"
    )


def _render_image_scene(
    scene: StoryboardScene, local: str, out: str, num: int,
    out_w: int = _OUT_W, out_h: int = _OUT_H,
    blur_fill_enabled: bool = False,
) -> str:
    """Animate a still image using zoompan and write it as a video segment.

    When blur_fill_enabled=True (only set for wikimedia_person portrait photos),
    a blur-fill composite is applied: blurred full-frame background behind the
    sharp portrait scaled to fit.  Zoompan motion is applied to the composite
    so portraits aren't static.  All other images use scale+crop+zoompan.

    Uses round(duration_s * _FPS) to compute the frame count and derives -t from
    that integer so the clip is exactly `frames` frames long.
    """
    frames = round(scene.duration_s * _FPS)
    t_value = frames / _FPS
    clip_label = scene.clip_type
    if scene.motion_effect:
        clip_label += f" ({scene.motion_effect})"

    # Blur-fill portraits are already letterboxed into the frame, so there is no
    # overflow left to pan across — downgrade a pan to the default push there.
    effect = normalize_motion_effect(scene.motion_effect, scene.clip_type)
    if blur_fill_enabled and effect in ("pan_left", "pan_right"):
        effect = "ken_burns"

    scale_vf = _motion_vf_prefix(scene.clip_type, effect, frames, out_w, out_h)
    zoompan_vf = _zoompan_filter(scene.clip_type, effect, frames, out_w, out_h)
    # zoompan bounds output to d=frames and resets the microsecond PTS from the
    # JPEG/PNG decoder — skipping it causes container duration corruption.  Pans are
    # the one exception (see _zoompan_filter): they return "" and are dropped here.
    normal_vf = ",".join(p for p in (scale_vf, zoompan_vf, f"fps={_FPS}", "setsar=1:1") if p)

    common_encode = (
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
        # Same timescale normalisation as _render_video_scene — see comment there.
        # Image clips using -loop 1 + zoompan inherit a 1/1_000_000 microsecond
        # time base from the still-image decoder; forcing 25 here ensures the clip's
        # container tbn matches all other per-scene clips.
        "  -video_track_timescale 25 \\\n"
        f"  {out}"
    )
    ffmpeg_prefix = (
        f"ffmpeg -y -loop 1 -framerate {_FPS} -i \"{local}\" \\\n"
        f"  -t {t_value} \\\n"
    )

    header = f"# Scene {num:02d} — {scene.scene} — {clip_label} — {scene.duration_s}s"

    if not blur_fill_enabled:
        return (
            f"{header}\n"
            f'{ffmpeg_prefix}'
            f'  -vf "{normal_vf}" \\\n'
            f"{common_encode}"
        )

    # Blur-fill for portrait photos: blurred full-frame background + portrait
    # scaled to fit, with zoompan applied to the composite so the portrait isn't static.
    # NB: the blur-fill chain deliberately does NOT use scale_vf — it composites its
    # own background/foreground scales from the raw input.
    blur_vf = (
        f"[in]split=2[bg][fg];"
        f"[bg]scale={out_w}:{out_h},boxblur=20:5[blurred];"
        f"[fg]scale=iw*min({out_w}/iw\\,{out_h}/ih):ih*min({out_w}/iw\\,{out_h}/ih)[fitted];"
        f"[blurred][fitted]overlay=(W-w)/2:(H-h)/2[composite];"
        f"[composite]{zoompan_vf},fps={_FPS},setsar=1:1"
    )
    return (
        f"{header}\n"
        f'{ffmpeg_prefix}'
        f'  -vf "{blur_vf}" \\\n'
        f"{common_encode}"
    )


def _filter_complex_concat(n_scenes: int) -> str:
    """
    Concatenate scene segments using the concat demuxer with full re-encode.

    Why NOT filter_complex concat:
      Scene clips arrive with mixed time bases — Pexels video clips produce
      tbns like 12800, 15360, 30000 depending on their native frame rate, and
      image/zoompan clips can carry a 1/1_000_000 microsecond time base.
      The filter_complex concat filter inherits the most-precise tbn from all
      inputs; libx264 then reads that tbn at encoder-init time, computes a
      frame rate of up to ~1,000,000 fps, and refuses to open ("Error while
      opening encoder" / "MB rate > level limit", exit 187).  fps= filter and
      -r flag workarounds both rely on the same underlying FFmpeg mechanism and
      do not fix the tbn metadata before libx264 sees it.

    Why concat demuxer + re-encode works:
      The concat demuxer streams decoded frames sequentially through a single
      ffmpeg process.  With -r {_FPS} the encoder is told the true frame rate
      before any time base inference occurs; libx264 generates fresh PTS values
      from scratch.  Re-encoding at CRF 18 preserves visual quality.

    The filelist is written line-by-line using echo so no extra tool is needed
    and the path quoting works under set -euo pipefail.
    """
    file_lines = "\n".join(
        f'echo "file \'$WORK/scene_{i:02d}.mp4\'" >> "$WORK/filelist.txt"'
        for i in range(1, n_scenes + 1)
    )
    return (
        "# ── Concatenate scenes (concat demuxer + re-encode) ────────────────\n"
        'rm -f "$WORK/filelist.txt"\n'
        f"{file_lines}\n"
        "ffmpeg -y \\\n"
        '  -f concat -safe 0 \\\n'
        '  -i "$WORK/filelist.txt" \\\n'
        f"  -r {_FPS} \\\n"
        # NOTE: do NOT add -vsync cfr here.  cfr examines input PTS to decide when
        # to duplicate frames; if any clip has a tbn mismatch it duplicates frames
        # and inflates the output to 2-3x the correct duration.
        # The correct fix is -video_track_timescale 25 on every per-scene clip so all
        # clips share tbn=25 before the concat demuxer accumulates their durations.
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
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
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
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


def _burn_voiceover_captions(input_path: str = "$WORK/video_only.mp4") -> str:
    """Burn voiceover captions ASS into input_path, producing video_captioned.mp4."""
    return (
        "# ── Burn voiceover captions ────────────────────────────────\n"
        "ffmpeg -y \\\n"
        f"  -i \"{input_path}\" \\\n"
        "  -vf \"ass=$WORK/voiceover_captions.ass\" \\\n"
        "  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \\\n"
        "  \"$WORK/video_captioned.mp4\""
    )


def _audio_section(
    storyboard: Storyboard,
    audio: AudioSettings,
    video_source: str = "$WORK/video_captioned.mp4",
) -> str:
    """
    Build the audio assembly ffmpeg command.

    Music volume is computed from audio settings at script-generation time:
    - vol_factor = music_volume / 100.0
    - ducking_enabled=True:  effective_vol = vol_factor * _DUCKING_FACTOR
    - ducking_enabled=False: effective_vol = vol_factor
    The computed value is embedded directly in the filter_complex string so no
    bash arithmetic is required at render time.

    SFX inputs are conditional: each file is checked for existence at runtime
    with [ -f "..." ] so the script runs correctly even when SFX files were
    not acquired (e.g. before Freesound integration is implemented).
    The filter_complex and amix input count are built dynamically in bash.
    """
    vol_factor = audio.music_volume / 100.0
    effective_vol = vol_factor * _DUCKING_FACTOR if audio.ducking_enabled else vol_factor
    music_vol_str = f"{effective_vol:.3f}"

    sfx_entries: list[tuple[str, int]] = []  # (sfx_name, delay_ms)
    offset_s = 0.0
    for scene in storyboard.scenes:
        if scene.sfx and scene.sfx.lower() != "silence":
            delay_ms = max(0, int((offset_s + _sfx_delay_within_scene_s(scene)) * 1000))
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

    filter_complex_line = (
        '  -filter_complex "[1:a]asetpts=PTS-STARTPTS,volume=1.0[vo];'
        '[2:a]asetpts=PTS-STARTPTS,volume='
        + music_vol_str
        + '[music]${_sfx_filters};[vo][music]${_sfx_labels}amix=inputs=${_n_audio}:duration=first:normalize=0[aout]" \\'
    )

    # Measure the voiceover duration at render time and trim the video input to that
    # exact length.  Scene duration estimates (alignment-based or storyboard) can
    # drift by a few seconds over a 30-scene run; without this trim the extra video
    # frames extend the output past the VO end, producing a longer-than-expected
    # video with a frozen last frame.  If the video is shorter than the VO the
    # -t flag is harmless — FFmpeg reads the video to its end and the audio
    # continues over the frozen last frame until the VO finishes.
    lines.extend([
        '# Trim video to VO duration so accumulated scene-duration drift never extends the output',
        'VO_DURATION=$(ffprobe -v quiet -show_entries format=duration'
        ' -of default=noprint_wrappers=1:nokey=1 "$VO")',
        'ffmpeg -y \\',
        '  -t "$VO_DURATION" \\',
        f'  -i "{video_source}" \\',
        '  -i "$VO" \\',
        '  "${MUSIC_ARGS[@]}" \\',
        '  "${_sfx_inputs[@]}" \\',
        filter_complex_line,
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


# Zoom rate for the zoom_in / zoom_out presets: 2% of frame size per second of
# scene duration (D081).  Expressed per-second rather than per-clip so a 2s and a
# 6s scene push at the same visible speed instead of the same total amount.
_ZOOM_RATE_PER_S = 0.02

# Ken Burns keeps its pre-D081 shape exactly: a fixed 1.0 -> 1.05 push across the
# whole clip, regardless of duration.  Do not "rationalise" this into a per-second
# rate — it is the default every existing run renders with.
_KEN_BURNS_TOTAL = 0.05

# Pan travel budget, as a fraction of the output width per second of scene
# duration.  The pan traverses min(available headroom, budget) pixels, centred on
# the image, so a wide landscape still in a 9:16 frame drifts sideways at a
# constant readable speed instead of racing across the full width on short scenes.
# This is the knob to turn if the pan reads too fast or too slow.
_PAN_TRAVEL_FRACTION_PER_S = 0.12


def _pan_travel_expr(out_w: int, duration_s: float) -> str:
    """Return the FFmpeg expression for a pan's travel distance in pixels.

    min(available horizontal headroom, budget), where the budget grows with scene
    duration at _PAN_TRAVEL_FRACTION_PER_S of the output width per second.  Commas
    inside the expression are backslash-escaped because the expression is embedded
    in a comma-separated -vf filter chain.
    """
    budget_px = out_w * _PAN_TRAVEL_FRACTION_PER_S * duration_s
    return f"min(max(0\\,iw-{out_w})\\,{budget_px:.1f})"


def _motion_vf_prefix(
    clip_type: str,
    motion_effect: str | None,
    frames: int,
    out_w: int = _OUT_W,
    out_h: int = _OUT_H,
) -> str:
    """Return the scale (and, for pans, crop) filters that precede zoompan.

    Non-pan effects keep the historical cover-and-centre-crop: the still is scaled
    to fill the frame and the overflow is discarded, so zoompan animates within a
    frame-sized image.

    Pan effects (D081) need the discarded overflow, so they scale to output HEIGHT
    only and leave the full width intact, then slide a frame-sized crop window
    across it with a time-driven x expression.  This is why pans cannot be done
    with zoompan: zoompan's crop region is always iw/zoom x ih/zoom, i.e. it always
    preserves the INPUT aspect ratio, so it cannot express a 9:16 window sliding
    across a 16:9 image without distorting it.
    """
    effect = normalize_motion_effect(motion_effect, clip_type)
    cover_scale = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h}"
    )
    if effect not in ("pan_left", "pan_right"):
        return cover_scale

    duration_s = frames / _FPS
    travel = _pan_travel_expr(out_w, duration_s)
    # Start the window offset from centre by half the travel so the pan is
    # symmetric about the middle of the image rather than hugging one edge.
    centre = f"(iw-{out_w})/2"
    if effect == "pan_right":
        x = f"{centre}-{travel}/2+{travel}*t/{duration_s:.4f}"
    else:
        x = f"{centre}+{travel}/2-{travel}*t/{duration_s:.4f}"
    return f"scale=-2:{out_h},crop={out_w}:{out_h}:x='{x}':y=0"


def _zoompan_filter(
    clip_type: str,
    motion_effect: str | None,
    frames: int,
    out_w: int = _OUT_W,
    out_h: int = _OUT_H,
) -> str:
    """Return a zoompan filter expression for a still clip's motion effect.

    Dispatches on the D081 controlled vocabulary (src.models.MOTION_EFFECTS) after
    normalising legacy names.  Before D081 this function returned early whenever
    clip_type was "still_with_motion" — which is every generated still — so
    motion_effect was dead code and every still rendered the same centre push.
    Now clip_type only supplies the DEFAULT when motion_effect is unset, so
    untouched runs still render exactly as they did.

    pan_left / pan_right return "" — their motion lives entirely in
    _motion_vf_prefix's time-driven crop, and appending a zoompan after a moving
    crop would DESTROY it: zoompan consumes one input frame and emits d frames from
    that single frame, so it freezes on the crop's first position.  (Verified: with
    a trailing zoompan the first and last frames of a pan differ by YAVG 0.03,
    i.e. not at all; without it, by 97.5.)  Those clips get their PTS from
    `-loop 1 -framerate {_FPS}` on the input plus the standalone fps={_FPS} that
    _render_image_scene appends, which is sufficient — the microsecond time base
    problem described below only arises when the still decoder's own timestamps
    reach the encoder untouched.

    out_w / out_h set the s= output size; default to module constants (9:16).
    """
    s = f"{out_w}x{out_h}"
    # fps is deliberately omitted from the zoompan parameter block.
    # When the input is a looped still image, FFmpeg uses a 1/1_000_000 (microsecond)
    # time base, which zoompan inherits.  Setting fps= inside zoompan only controls the
    # internal generation rate but does NOT reset the presentation timestamps — libx264
    # then sees an effective MB rate of ~8 billion/sec and refuses to open.  Instead, a
    # standalone fps={_FPS} filter is inserted after zoompan in _render_image_scene to
    # rewrite PTS values to a sane 1/25 time base before the encoder sees them.
    suffix = f":d={frames}:s={s}"
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"
    static = f"zoompan=z='1.0':x='{cx}':y='{cy}'{suffix}"

    effect = normalize_motion_effect(motion_effect, clip_type)

    # Pans carry their motion in the crop; a zoompan here would freeze it.
    if effect in ("pan_left", "pan_right"):
        return ""

    # "static" = hold.  z=1.0 constant; d=frames still bounds output and resets the
    # microsecond PTS from the JPEG/PNG decoder.
    if effect == "static":
        return static

    if effect == "ken_burns":
        return f"zoompan=z='1+{_KEN_BURNS_TOTAL}*on/{frames}':x='{cx}':y='{cy}'{suffix}"

    duration_s = frames / _FPS
    total = _ZOOM_RATE_PER_S * duration_s
    if effect == "zoom_in":
        # on/_FPS is elapsed seconds, so this is literally 2% per second.
        return f"zoompan=z='1+{_ZOOM_RATE_PER_S}*on/{_FPS}':x='{cx}':y='{cy}'{suffix}"
    if effect == "zoom_out":
        return (
            f"zoompan=z='{1 + total:.4f}-{_ZOOM_RATE_PER_S}*on/{_FPS}'"
            f":x='{cx}':y='{cy}'{suffix}"
        )

    # normalize_motion_effect only ever returns a MOTION_EFFECTS member, so this is
    # unreachable; kept so an added vocabulary entry degrades to a hold, not a crash.
    return static


# OST appear-delay (0.3s) + slide-in duration (0.4s) from
# cf_platform/workers/render_worker.py's _OST_SLIDE_IN_S (D074/D075). Duplicated
# here as a literal, not imported — src/ never imports cf_platform/ (D047). Keep
# in sync manually if the OST slide-in timing ever changes.
_SFX_OST_SYNC_OFFSET_S = 0.7


def _sfx_delay_within_scene_s(scene: StoryboardScene) -> float:
    """Within-scene SFX delay, in seconds, per the automatic-timing rule (D076).

    A scene with on-screen text: the SFX is timed to land as the OST slide-in
    finishes (_SFX_OST_SYNC_OFFSET_S into the scene). No on-screen text: SFX
    plays at the moment the scene starts (0.0s). This replaces manual timing —
    scene.sfx_timing is not consulted; see _parse_sfx_delay_ms below, which is
    kept (still tested, still correct) but is no longer called from
    _audio_section.
    """
    return _SFX_OST_SYNC_OFFSET_S if scene.on_screen_text else 0.0


def _parse_sfx_delay_ms(sfx_timing: str, duration_s: float, scene_offset_s: float) -> int:
    """
    Return the adelay value in milliseconds for an SFX placed within a scene.

    Recognised sfx_timing values: "scene_start", "mid", "end", "<float>s".
    Unrecognised values default to scene_start.

    Not currently called from _audio_section — SFX timing is now computed
    automatically by _sfx_delay_within_scene_s (D076). Kept for its existing
    test coverage and as a potential future manual-override hook.
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
