"""Timeline -> CapCut draft plan (P13b-S3, D100).

Pure mapping, no pycapcut and no I/O: it turns the platform's `timeline.json` (plus the
size / length of each media file, which only the laptop can measure) into a plan of
clips in microseconds — the unit CapCut drafts use. `export_capcut.py` writes the plan
to a draft with pycapcut. Keeping the mapping separate is what makes it testable in CI,
where neither CapCut nor pycapcut exists.

The motion values mirror the FFmpeg render (src/ffmpeg_builder.py) so the two paths
move alike: zoom rates per second, and a pan that travels min(headroom, 12% of the
output width per second), centred on the picture. A picture with less than 10% of the
width to spare is enlarged until it has that much, so a pan is always visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SUPPORTED_SCHEMA_VERSIONS = (1,)
TESTED_WITH = "CapCut 8.9.1 (macOS), pycapcut 0.0.3"

US_PER_MS = 1000

# Mirrors src/ffmpeg_builder.py (_KEN_BURNS_RATE_PER_S, _ZOOM_RATE_PER_S, _PAN_TRAVEL_FRACTION_PER_S).
KEN_BURNS_RATE_PER_S = 0.01
ZOOM_RATE_PER_S = 0.02
PAN_TRAVEL_FRACTION_PER_S = 0.12
# Mirrors src/ffmpeg_builder._PAN_MIN_TRAVEL_FRACTION.
PAN_MIN_TRAVEL_FRACTION = 0.10
# Mirrors src/ffmpeg_builder._DUCKING_FACTOR.
DUCKING_FACTOR = 0.4

# Caption chunking mirrors the ASS builders: Standard shows a rolling 5-word line, Punch one word.
STANDARD_CHUNK_WORDS = 5
MIN_CAPTION_US = 80 * US_PER_MS

# Text look, tuned on 1080-wide canvases (the spike's sizes, which opened correctly in CapCut 8.9.1).
OST_SIZE = 11.0
PUNCH_SIZE = 18.0
STANDARD_SIZE = 12.0
# Vertical centres, in CapCut's units (+1 = top edge, -1 = bottom edge). On-screen text sits with
# its box top at 30% of the height; 9:16 captions sit on the ASS MarginV 576 band.
OST_Y = 0.26
CAPTION_Y_PORTRAIT = {"standard": -0.36, "punch": -0.33}
CAPTION_Y_LANDSCAPE = -0.7


class TimelineError(Exception):
    """The timeline cannot be turned into a draft (unknown schema version, bad content)."""


@dataclass(frozen=True)
class MediaInfo:
    """What the laptop measured about one media file (microseconds, pixels)."""

    width: int = 0
    height: int = 0
    duration_us: int = 0


@dataclass(frozen=True)
class KeyframePlan:
    """One keyframe: a CapCut property name, a time within the clip, and a value."""

    prop: str  # "uniform_scale" | "position_x"
    time_us: int
    value: float


@dataclass
class VideoClipPlan:
    """A scene's footage on the video track."""

    scene_id: str
    path: str
    kind: str  # "image" | "video"
    start_us: int
    duration_us: int
    scale: float
    source_duration_us: int | None = None  # footage: how much of the file plays
    muted: bool = True
    keyframes: list[KeyframePlan] = field(default_factory=list)


@dataclass
class TextClipPlan:
    """An editable text clip (on-screen text or a caption)."""

    track: str  # "on_screen_text" | "captions"
    text: str
    start_us: int
    duration_us: int
    size: float
    bold: bool
    color: tuple[float, float, float]
    transform_y: float
    background: tuple[str, float] | None = None  # (hex colour, alpha)
    border: bool = False
    max_line_width: float = 0.82


@dataclass
class AudioClipPlan:
    """A voiceover, music or SFX clip."""

    track: str  # "voiceover" | "music" | "sfx"
    path: str
    start_us: int
    duration_us: int
    volume: float


@dataclass
class DraftPlan:
    """Everything the draft needs, in microseconds."""

    width: int
    height: int
    fps: int
    video: list[VideoClipPlan] = field(default_factory=list)
    texts: list[TextClipPlan] = field(default_factory=list)
    audio: list[AudioClipPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_schema(timeline: dict) -> None:
    """Raise TimelineError unless the timeline's schema_version is one this script knows."""
    version = timeline.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        known = ", ".join(str(v) for v in SUPPORTED_SCHEMA_VERSIONS)
        raise TimelineError(
            f"This export uses timeline schema version {version!r}; this script understands "
            f"{known}. Update the script (git pull in the project, then re-run) or download "
            "the zip again from a Studio that matches it."
        )


def cover_scale(media_w: int, media_h: int, canvas_w: int, canvas_h: int) -> float:
    """Scale that makes media cover the canvas when CapCut fits it inside (>= 1.0).

    CapCut places media at its contain size; FFmpeg scales to cover and crops. The
    ratio between the two is max(media aspect / canvas aspect, canvas aspect / media aspect).
    """
    if not (media_w and media_h):
        return 1.0
    media_aspect = media_w / media_h
    canvas_aspect = canvas_w / canvas_h
    return max(media_aspect / canvas_aspect, canvas_aspect / media_aspect)


def pan_zoom(media_w: int, media_h: int, canvas_w: int, canvas_h: int) -> float:
    """Extra scale (>= 1.0) a pan needs so the covered picture has PAN_MIN_TRAVEL_FRACTION to spare.

    The FFmpeg render enlarges a picture that is short of spare width; this is the same
    factor, applied on top of the cover scale. 1.0 for a picture that already has enough.
    """
    if not (media_w and media_h):
        return 1.0
    covered_w = media_w * max(canvas_w / media_w, canvas_h / media_h)
    return max(1.0, canvas_w * (1 + PAN_MIN_TRAVEL_FRACTION) / covered_w)


def motion_keyframes(
    effect: str | None, duration_us: int, scale: float, media_w: int, media_h: int,
    canvas_w: int, canvas_h: int,
) -> list[KeyframePlan]:
    """Keyframes for a still's motion effect, matching the FFmpeg render's speed.

    Zooms are a rate per second of scene (ken_burns 1%/s, zoom_in/out 2%/s), applied on
    top of the cover scale. A pan slides the picture sideways by min(horizontal headroom,
    12% of the canvas width per second), centred; position values are in half-canvas-widths.
    The headroom counts the enlargement `plan_draft` gives a pan clip (see pan_zoom).
    """
    seconds = duration_us / 1_000_000
    if effect == "ken_burns":
        return _scale_ramp(duration_us, scale, scale * (1 + KEN_BURNS_RATE_PER_S * seconds))
    if effect == "zoom_in":
        return _scale_ramp(duration_us, scale, scale * (1 + ZOOM_RATE_PER_S * seconds))
    if effect == "zoom_out":
        return _scale_ramp(duration_us, scale * (1 + ZOOM_RATE_PER_S * seconds), scale)
    if effect in ("pan_left", "pan_right") and media_w and media_h:
        # FFmpeg scales to cover (force_original_aspect_ratio=increase) and slides a window;
        # the headroom is how much wider than the canvas the covered picture is.
        factor = max(canvas_w / media_w, canvas_h / media_h)
        headroom = max(0.0, media_w * factor * pan_zoom(media_w, media_h, canvas_w, canvas_h) - canvas_w)
        travel = min(headroom, canvas_w * PAN_TRAVEL_FRACTION_PER_S * seconds)
        half_units = travel / canvas_w  # (travel / 2) px in half-canvas-width units
        if half_units <= 0:
            return []
        # pan_right: the window moves right, so the picture moves left (+ -> -).
        start, end = (half_units, -half_units) if effect == "pan_right" else (-half_units, half_units)
        return [KeyframePlan("position_x", 0, start), KeyframePlan("position_x", duration_us, end)]
    return []  # static, or no effect


def _scale_ramp(duration_us: int, start: float, end: float) -> list[KeyframePlan]:
    """Two uniform-scale keyframes, from start at the clip's first frame to end at its last."""
    return [KeyframePlan("uniform_scale", 0, start), KeyframePlan("uniform_scale", duration_us, end)]


def caption_clips(timeline: dict) -> list[TextClipPlan]:
    """Editable caption clips in the run's style, timed like the ASS captions.

    Punch: one upper-cased word per clip, lasting until the next word starts in its scene
    (the last word of a scene lasts its own length). Standard: one clip per rolling
    5-word line. CapCut text clips take one style for the whole clip, so Standard's
    per-word highlight is not reproduced; the line stays on screen until the next one.
    """
    if not timeline.get("captions_enabled") or timeline.get("captions_source") != "alignment":
        return []
    punch = timeline.get("caption_style") == "punch"
    portrait = timeline.get("aspect_ratio") == "9:16"
    y = CAPTION_Y_PORTRAIT["punch" if punch else "standard"] if portrait else CAPTION_Y_LANDSCAPE

    per_scene: dict[int, list[dict]] = {}
    for word in timeline.get("caption_words", []):
        per_scene.setdefault(word["scene_index"], []).append(word)

    def shown(word: dict) -> str:
        """The caption text for one word: spelled-out numbers, upper-cased for Punch."""
        text = word.get("display") or word["word"]
        return text.upper() if punch else text

    clips: list[TextClipPlan] = []
    chunk_size = 1 if punch else STANDARD_CHUNK_WORDS
    for _, words in sorted(per_scene.items()):
        chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
        for j, chunk in enumerate(chunks):
            start_ms = chunk[0]["start_ms"]
            end_ms = chunks[j + 1][0]["start_ms"] if j + 1 < len(chunks) else chunk[-1]["end_ms"]
            clips.append(TextClipPlan(
                track="captions", text=" ".join(shown(w) for w in chunk),
                start_us=start_ms * US_PER_MS, duration_us=max(MIN_CAPTION_US, (end_ms - start_ms) * US_PER_MS),
                size=PUNCH_SIZE if punch else STANDARD_SIZE, bold=True, color=(1.0, 1.0, 1.0),
                transform_y=y, border=True, max_line_width=0.9 if punch else 0.82,
            ))
    return clips


def plan_draft(timeline: dict, media: dict[str, MediaInfo]) -> DraftPlan:
    """Turn a timeline and the measured media files into the draft's clips.

    `media` maps each run-relative path in the timeline to what was measured for it.
    A file missing from `media` is skipped with a warning (SFX / music) or raises
    TimelineError (scene footage, voiceover).
    """
    check_schema(timeline)
    width, height = timeline["width"], timeline["height"]
    plan = DraftPlan(width=width, height=height, fps=timeline.get("fps", 25))

    for scene in timeline["scenes"]:
        info = media.get(scene["asset_path"])
        if info is None:
            raise TimelineError(f"Scene {scene['scene_id']}: {scene['asset_path']} is not in the zip.")
        start_us = scene["start_ms"] * US_PER_MS
        duration_us = (scene["end_ms"] - scene["start_ms"]) * US_PER_MS
        scale = cover_scale(info.width, info.height, width, height)
        clip = VideoClipPlan(
            scene_id=scene["scene_id"], path=scene["asset_path"], kind=scene["asset_kind"],
            start_us=start_us, duration_us=duration_us, scale=scale,
        )
        if scene["asset_kind"] == "video":
            # Footage is trimmed to the scene and muted; motion effects do not apply (D089).
            clip.source_duration_us = min(duration_us, info.duration_us) if info.duration_us else duration_us
            if clip.source_duration_us < duration_us:
                clip.duration_us = clip.source_duration_us
                plan.warnings.append(
                    f"Scene {scene['scene_id']}: the footage is {clip.source_duration_us / 1e6:.2f}s but the "
                    f"scene lasts {duration_us / 1e6:.2f}s, so the last "
                    f"{(duration_us - clip.source_duration_us) / 1e6:.2f}s is empty."
                )
        else:
            if scene.get("motion_effect") in ("pan_left", "pan_right"):
                # Enlarge a picture with no room to pan, as the FFmpeg render does.
                clip.scale = scale * pan_zoom(info.width, info.height, width, height)
            clip.keyframes = motion_keyframes(
                scene.get("motion_effect"), duration_us, scale, info.width, info.height, width, height,
            )
        plan.video.append(clip)

        text = scene.get("text")
        if text:
            plan.texts.append(TextClipPlan(
                track="on_screen_text", text=text["text"].upper(),
                start_us=text["start_ms"] * US_PER_MS,
                duration_us=(text["end_ms"] - text["start_ms"]) * US_PER_MS,
                size=OST_SIZE, bold=True, color=(0.0, 0.0, 0.0), transform_y=OST_Y,
                background=("#FFFFFF", 0.55), max_line_width=0.8,
            ))

    plan.texts.extend(caption_clips(timeline))
    plan.audio.extend(_audio_clips(timeline, media, plan.warnings))
    return plan


def _audio_clips(timeline: dict, media: dict[str, MediaInfo], warnings: list[str]) -> list[AudioClipPlan]:
    """Voiceover, music (looped or fitted) and SFX clips."""
    total_us = timeline["duration_ms"] * US_PER_MS
    clips: list[AudioClipPlan] = []

    vo_path = timeline.get("voiceover_path")
    if not vo_path or vo_path not in media:
        raise TimelineError("The voiceover is not in the zip.")
    vo_us = media[vo_path].duration_us or total_us
    clips.append(AudioClipPlan("voiceover", vo_path, 0, vo_us, 1.0))

    music_path = timeline.get("music_path")
    if music_path:
        info = media.get(music_path)
        if info is None or not info.duration_us:
            warnings.append(f"Music {music_path} is not in the zip (or has no length) — left out.")
        else:
            gain = timeline["music_volume"] / 100.0
            if timeline.get("music_ducking"):
                gain *= DUCKING_FACTOR
            # The music runs as long as the voiceover (amix duration=first in the render).
            clips.extend(_music_clips(music_path, info.duration_us, vo_us, gain, timeline.get("music_playback_mode")))

    for scene in timeline["scenes"]:
        path = scene.get("sfx_path")
        if not path:
            continue
        info = media.get(path)
        if info is None or not info.duration_us:
            warnings.append(f"Scene {scene['scene_id']}: SFX {path} is not in the zip — left out.")
            continue
        clips.append(AudioClipPlan("sfx", path, scene["sfx_delay_ms"] * US_PER_MS, info.duration_us, 1.0))
    return clips


def _music_clips(path: str, music_us: int, span_us: int, gain: float, mode: str | None) -> list[AudioClipPlan]:
    """Music across span_us: one pass ("fit"), or repeated end to end ("loop")."""
    if mode != "loop":
        return [AudioClipPlan("music", path, 0, min(music_us, span_us), gain)]
    clips: list[AudioClipPlan] = []
    cursor = 0
    while cursor < span_us:
        length = min(music_us, span_us - cursor)
        clips.append(AudioClipPlan("music", path, cursor, length, gain))
        cursor += length
    return clips


def assign_tracks(clips: list, base: str) -> dict[str, list]:
    """Spread clips over as many tracks as needed so none overlap on one track.

    A CapCut track holds sequential clips; two overlapping ones (two SFX hits close
    together) need their own track. Returns {track name: clips in time order}; the
    first track is `base`, further ones `base 2`, `base 3` ...
    """
    tracks: list[list] = []
    for clip in sorted(clips, key=lambda c: c.start_us):
        for track in tracks:
            if track[-1].start_us + track[-1].duration_us <= clip.start_us:
                track.append(clip)
                break
        else:
            tracks.append([clip])
    return {(base if i == 0 else f"{base} {i + 1}"): track for i, track in enumerate(tracks)}
