"""Timeline (P13b-S1) — the one artifact that describes a finalized run to a renderer.

A Timeline holds everything a renderer needs and nothing it has to re-derive: the
scenes with their resolved timing, the asset behind each one, motion, on-screen text,
caption words, voiceover, music and SFX. Two renderers read it — the FFmpeg script
builder on Railway and, via the zip export, the CapCut script on the operator's laptop
(D100) — so a cut can never land in a different place in the two.

`build_timeline` is the only place scene timing is resolved for rendering. It is a
pure function (D040): storyboard, manifest, voice alignment and settings in, Timeline
out. Reading artifacts and listing R2 is the job of the async helpers at the bottom.

The schema is versioned. Bump TIMELINE_SCHEMA_VERSION on any change a consumer must
notice; the laptop script refuses a version it does not know.
"""

import bisect
import logging
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field

from cf_platform.workers.voice_production import VoiceAlignmentArtifact
from src.models import (
    AWAITING_UPLOAD_STATUS,
    AssetManifest,
    AudioSettings,
    Storyboard,
    StoryboardScene,
    VideoSettings,
    WordTimestamp,
    normalize_motion_effect,
)

logger = logging.getLogger(__name__)

TIMELINE_SCHEMA_VERSION = 1

# On-screen text appears this long after its scene starts (D074) and is shown to the
# end of the scene. Mirrors the 0.3s in render_worker's overlay filter.
OST_APPEAR_DELAY_S = 0.3

FRAME_RATE = 25

_AUDIO_EXTS = (".mp3", ".wav", ".m4a")


class MissingAssetsError(Exception):
    """Raised when a scene has no file, so no renderer can use the storyboard yet."""


# ── Model ─────────────────────────────────────────────────────────────────────


class TimelineText(BaseModel):
    """On-screen text on a scene, with the window it is visible in (run-absolute ms)."""

    text: str
    type: str | None = None
    start_ms: int
    end_ms: int


class TimelineScene(BaseModel):
    """One scene: when it plays, which file it shows, and what is laid over it."""

    scene_id: str
    index: int = Field(description="1-based position; the FFmpeg script's scene number")
    start_ms: int
    end_ms: int
    duration_s: float = Field(description="Exact duration; start/end are this rounded to ms")
    asset_key: str = Field(description="R2 key of the scene's file")
    asset_path: str = Field(description="Path of the file relative to the run folder")
    asset_kind: Literal["image", "video"]
    asset_source: str | None = None
    # Canonical MOTION_EFFECTS member for a still; None for footage (D089).
    motion_effect: str | None = None
    text: TimelineText | None = None
    sfx_key: str | None = None
    sfx_path: str | None = None
    # Run-absolute offset at which the SFX starts (what FFmpeg's adelay uses).
    sfx_delay_ms: int | None = None


class TimelineCaptionWord(BaseModel):
    """One spoken word with its run-absolute timing, assigned to a scene."""

    scene_index: int
    word: str
    start_ms: int
    end_ms: int
    # What the caption shows: numbers spelled out (D073). Timing always follows `word`.
    display: str = ""


class Timeline(BaseModel):
    """Everything a renderer needs for one finalized run."""

    schema_version: int = TIMELINE_SCHEMA_VERSION
    run_id: str
    format_track: Literal["portrait", "landscape"]
    aspect_ratio: Literal["9:16", "16:9"]
    width: int
    height: int
    fps: int = FRAME_RATE
    duration_ms: int

    scenes: list[TimelineScene]

    captions_enabled: bool
    # "alignment": word-synced from the voice alignment; "script": one cue per scene
    # from the voiceover lines (no alignment available).
    captions_source: Literal["alignment", "script"]
    caption_style: Literal["standard", "punch"] = "standard"
    # The font family preset (VideoSettings.subtitles) — "TikTok" or "Classic".
    subtitle_style: str = "TikTok"
    caption_words: list[TimelineCaptionWord] = Field(default_factory=list)

    voiceover_key: str | None = None
    voiceover_path: str | None = None
    voiceover_duration_s: float | None = None

    music_key: str | None = None
    music_path: str | None = None
    music_volume: int = Field(description="0-100, the run's music volume setting")
    music_ducking: bool = False
    music_playback_mode: Literal["loop", "fit"] = "fit"

    def referenced_paths(self) -> list[str]:
        """Return the run-relative path of every file this timeline points at, deduplicated."""
        paths: list[str] = []
        for scene in self.scenes:
            paths.append(scene.asset_path)
        for path in (self.voiceover_path, self.music_path):
            if path:
                paths.append(path)
        for scene in self.scenes:
            if scene.sfx_path:
                paths.append(scene.sfx_path)
        return list(dict.fromkeys(paths))

    def referenced_keys(self) -> list[str]:
        """Return the R2 key of every file this timeline points at, in referenced_paths order."""
        keys: list[str] = []
        for scene in self.scenes:
            keys.append(scene.asset_key)
        for key in (self.voiceover_key, self.music_key):
            if key:
                keys.append(key)
        for scene in self.scenes:
            if scene.sfx_path:
                keys.append(f"runs/{self.run_id}/{scene.sfx_path}")
        return list(dict.fromkeys(keys))


class TimelineArtifact(BaseModel):
    """Run artifact wrapping a Timeline (stage "render", name "timeline")."""

    timeline: Timeline
    generated_at: datetime


class TimelineSettings(BaseModel):
    """Per-render choices that shape the timeline (the render request's options)."""

    format_track: Literal["portrait", "landscape"] = "landscape"
    captions: bool = True
    caption_style: Literal["standard", "punch"] = "standard"
    voiceover_key: str | None = None
    music_key: str | None = None
    video: VideoSettings = Field(default_factory=VideoSettings)


# ── Helpers ───────────────────────────────────────────────────────────────────


def relative_asset_path(run_id: str, file_key: str) -> str:
    """Return file_key relative to the run folder (``runs/{run_id}/images/1.jpg`` → ``images/1.jpg``)."""
    prefix = f"runs/{run_id}/"
    return file_key[len(prefix):] if file_key.startswith(prefix) else file_key


def missing_assets_message(storyboard, manifest) -> str | None:
    """Return why this storyboard cannot render yet, or None when every scene has an asset.

    The render script needs one acquired file per scene. Since P13 a scene can be
    without one on purpose — an "upload" scene the operator has not filled, or the
    second half of a split — so the gap is reported in words before any FFmpeg
    work starts, instead of surfacing as a failed script.
    """
    entries = {e.scene_id: e for e in manifest.entries}
    awaiting: list[str] = []
    missing: list[str] = []
    for scene in storyboard.scenes:
        entry = entries.get(scene.scene)
        # A file is all the render needs — a failed re-acquire leaves the previous
        # file in place with status "failed", and that still renders.
        if entry is not None and entry.file_key:
            continue
        waits_for_upload = scene.asset_strategy == "upload" or (
            entry is not None and entry.status == AWAITING_UPLOAD_STATUS
        )
        (awaiting if waits_for_upload else missing).append(scene.scene)

    parts: list[str] = []
    if awaiting:
        parts.append(
            f"Scene(s) {', '.join(awaiting)} are set to Upload and have no file yet — "
            "upload a file or change the asset type."
        )
    if missing:
        parts.append(
            f"Scene(s) {', '.join(missing)} have no asset — acquire them in the Storyboard stage."
        )
    return " ".join(parts) if parts else None


def _normalized_words(alignment: VoiceAlignmentArtifact) -> list:
    """The voiceover words exactly as the StoryboardWorker indexes them.

    A scene's start_word / end_word index THIS list, in which Deepgram's contraction
    splits ("don" + "'t" sharing a start time) are merged into one word. The alignment
    artifact stores the raw list, so indexing it directly drifts by one word per
    contraction (noted in P13-S2).
    """
    from cf_platform.workers.storyboard_worker import _normalize_deepgram_words

    return _normalize_deepgram_words([w.model_dump() for w in alignment.word_timestamps])


def resolve_scene_timing(
    storyboard: Storyboard,
    alignment: VoiceAlignmentArtifact | None,
) -> tuple[list[StoryboardScene], list[list[WordTimestamp]] | None]:
    """Resolve each scene's duration, and its caption words, against the voice alignment.

    Returns (scenes with duration_s set, scene_words). scene_words is None when there
    is no alignment to take caption words from — the captions then come from the
    voiceover lines. Four timing paths, as before P13b:

    1. Deepgram + stored scene_start_ms on every scene (P9-S9): boundaries come from
       the scenes' start_word indices into the CURRENT voiceover words, so a
       regenerated voiceover cannot leave stored times stale; stored times are used
       only when a scene lacks start_word.
    2. Deepgram without scene_start_ms: the two-pass gap-based legacy path.
    3. Any other alignment (proportional): durations spread over the audio length.
    4. No word timestamps at all: the storyboard's own durations.
    """
    from src.ffmpeg_builder import (
        assign_words_to_scenes,
        compute_scene_durations_from_alignment,
        fill_caption_gaps,
        redistribute_scene_durations,
    )

    if alignment is None or not alignment.word_timestamps:
        return list(storyboard.scenes), None

    src_timestamps = [
        WordTimestamp(word=w.word, start_ms=w.start_ms, end_ms=w.end_ms, confidence=w.confidence)
        for w in alignment.word_timestamps
    ]
    has_scene_timestamps = all(s.scene_start_ms is not None for s in storyboard.scenes)
    logger.info(
        "Timeline timing path: method=%s has_scene_timestamps=%s",
        alignment.alignment_method, has_scene_timestamps,
    )

    if alignment.alignment_method == "deepgram_nova2" and has_scene_timestamps:
        # Boundaries index the NORMALISED list; captions stay on the raw words (their
        # text and timing are what the voiceover actually says).
        boundary_words = _normalized_words(alignment)
        n_words = len(boundary_words)
        has_start_words = (
            n_words > 0
            and all(s.start_word is not None for s in storyboard.scenes)
            and len({s.start_word for s in storyboard.scenes}) > 1
        )
        if has_start_words:
            boundaries_ms = [
                boundary_words[max(0, min(s.start_word, n_words - 1))].start_ms
                for s in storyboard.scenes
            ]
        else:
            boundaries_ms = [s.scene_start_ms for s in storyboard.scenes]
        raw_scene_words: list[list[WordTimestamp]] = [[] for _ in storyboard.scenes]
        for w in src_timestamps:
            idx = bisect.bisect_right(boundaries_ms, w.start_ms) - 1
            idx = max(0, min(idx, len(storyboard.scenes) - 1))
            raw_scene_words[idx].append(w)
        # Gap-based durations: scene N holds until scene N+1's first word; the last
        # scene holds through the end of the audio (fixes the final-frame freeze).
        adjusted: list[StoryboardScene] = []
        n_scenes = len(storyboard.scenes)
        for i, scene in enumerate(storyboard.scenes):
            if i < n_scenes - 1:
                dur = (boundaries_ms[i + 1] - boundaries_ms[i]) / 1000.0
            else:
                dur = alignment.total_duration_s - boundaries_ms[i] / 1000.0
            adjusted.append(scene.model_copy(update={"duration_s": max(0.08, round(dur, 3))}))
    elif alignment.alignment_method == "deepgram_nova2":
        # Legacy two-pass path for storyboards without scene_start_ms.
        words_pass1 = assign_words_to_scenes(storyboard.scenes, src_timestamps)
        adjusted_pass1 = compute_scene_durations_from_alignment(storyboard.scenes, words_pass1)
        raw_scene_words = assign_words_to_scenes(adjusted_pass1, src_timestamps)
        adjusted = compute_scene_durations_from_alignment(adjusted_pass1, raw_scene_words)
    else:
        raw_scene_words = assign_words_to_scenes(storyboard.scenes, src_timestamps)
        adjusted = redistribute_scene_durations(storyboard.scenes, alignment.total_duration_s)

    return adjusted, fill_caption_gaps(adjusted, raw_scene_words)


# ── Assembly ──────────────────────────────────────────────────────────────────


def assemble_timeline(
    run_id: str,
    scenes: list[StoryboardScene],
    manifest: AssetManifest,
    scene_words: list[list[WordTimestamp]] | None,
    settings: TimelineSettings,
    voiceover_duration_s: float | None = None,
) -> Timeline:
    """Build the Timeline from scenes whose durations are already resolved.

    Split from build_timeline so the legacy `_build_render_script` signature (scenes
    and caption words in hand) can produce the same Timeline the real path does.
    Raises MissingAssetsError when a scene has no file.
    """
    from src.captions import spell_out_numbers
    from src.ffmpeg_builder import _IMAGE_EXTS, _sfx_delay_within_scene_s

    entries = {e.scene_id: e for e in manifest.entries}
    video = settings.video
    out_w, out_h = (1920, 1080) if settings.format_track == "landscape" else (1080, 1920)

    timeline_scenes: list[TimelineScene] = []
    offset_s = 0.0
    for i, scene in enumerate(scenes, 1):
        entry = entries.get(scene.scene)
        if entry is None or not entry.file_key:
            raise MissingAssetsError(f"Scene '{scene.scene}' has no acquired asset.")
        kind: Literal["image", "video"] = (
            "image" if PurePosixPath(entry.file_key).suffix.lower() in _IMAGE_EXTS else "video"
        )

        opts = scene.render_options
        ost_text = opts.on_screen_text_overlay.text if opts and opts.on_screen_text_overlay else None
        ost_text = ost_text or scene.on_screen_text
        end_s = offset_s + scene.duration_s
        text = None
        if ost_text:
            ost_type = (
                opts.on_screen_text_overlay.type
                if opts and opts.on_screen_text_overlay and opts.on_screen_text_overlay.text
                else scene.on_screen_text_type
            )
            text = TimelineText(
                text=ost_text, type=ost_type,
                start_ms=round((offset_s + OST_APPEAR_DELAY_S) * 1000), end_ms=round(end_s * 1000),
            )

        sfx_key = sfx_path = sfx_delay = None
        if scene.sfx and scene.sfx.lower() != "silence":
            sfx_key = scene.sfx
            sfx_path = f"sfx/{scene.sfx}.mp3"
            sfx_delay = max(0, int((offset_s + _sfx_delay_within_scene_s(scene)) * 1000))

        timeline_scenes.append(TimelineScene(
            scene_id=scene.scene, index=i,
            start_ms=round(offset_s * 1000), end_ms=round(end_s * 1000), duration_s=scene.duration_s,
            asset_key=entry.file_key, asset_path=relative_asset_path(run_id, entry.file_key),
            asset_kind=kind, asset_source=entry.source,
            motion_effect=normalize_motion_effect(scene.motion_effect, scene.clip_type) if kind == "image" else None,
            text=text, sfx_key=sfx_key, sfx_path=sfx_path, sfx_delay_ms=sfx_delay,
        ))
        offset_s = end_s

    caption_words: list[TimelineCaptionWord] = []
    for i, words in enumerate(scene_words or [], 1):
        caption_words.extend(
            TimelineCaptionWord(
                scene_index=i, word=w.word, start_ms=w.start_ms, end_ms=w.end_ms,
                display=spell_out_numbers(w.word),
            )
            for w in words
        )

    audio: AudioSettings = video.audio
    return Timeline(
        run_id=run_id,
        format_track=settings.format_track,
        aspect_ratio="16:9" if settings.format_track == "landscape" else "9:16",
        width=out_w, height=out_h,
        duration_ms=round(offset_s * 1000),
        scenes=timeline_scenes,
        captions_enabled=settings.captions and video.subtitles != "none",
        captions_source="alignment" if scene_words is not None else "script",
        caption_style=settings.caption_style,
        subtitle_style=video.subtitles,
        caption_words=caption_words,
        voiceover_key=settings.voiceover_key or None,
        voiceover_path=relative_asset_path(run_id, settings.voiceover_key) if settings.voiceover_key else None,
        voiceover_duration_s=voiceover_duration_s,
        music_key=settings.music_key or None,
        music_path=relative_asset_path(run_id, settings.music_key) if settings.music_key else None,
        music_volume=audio.music_volume,
        music_ducking=audio.ducking_enabled,
        music_playback_mode=audio.playback_mode,
    )


def build_timeline(
    storyboard: Storyboard,
    manifest: AssetManifest,
    voice_alignment: VoiceAlignmentArtifact | None,
    settings: TimelineSettings,
) -> Timeline:
    """Resolve a finalized run into a Timeline. Pure (D040): no I/O, no globals.

    The one place scene timing is resolved for rendering. Raises MissingAssetsError
    (with the operator-facing message) while any scene has no file.
    """
    blocked = missing_assets_message(storyboard, manifest)
    if blocked:
        raise MissingAssetsError(blocked)
    scenes, scene_words = resolve_scene_timing(storyboard, voice_alignment)
    return assemble_timeline(
        manifest.run_id, scenes, manifest, scene_words, settings,
        voiceover_duration_s=voice_alignment.total_duration_s if voice_alignment else None,
    )


# ── Reading the timeline back for a renderer ─────────────────────────────────


def scenes_with_timeline_durations(storyboard: Storyboard, timeline: Timeline) -> list[StoryboardScene]:
    """Return the storyboard's scenes carrying the timeline's resolved durations.

    The scene lists must line up one to one; a timeline built for a different
    storyboard version is refused rather than rendered with shifted timing.
    """
    if [s.scene for s in storyboard.scenes] != [t.scene_id for t in timeline.scenes]:
        raise ValueError("Timeline does not match the storyboard's scenes — rebuild the timeline.")
    return [
        scene.model_copy(update={"duration_s": ts.duration_s})
        for scene, ts in zip(storyboard.scenes, timeline.scenes)
    ]


def scene_words_from_timeline(timeline: Timeline) -> list[list[WordTimestamp]] | None:
    """Rebuild the per-scene caption word lists, or None when captions come from the script."""
    if timeline.captions_source != "alignment":
        return None
    per_scene: list[list[WordTimestamp]] = [[] for _ in timeline.scenes]
    for w in timeline.caption_words:
        per_scene[w.scene_index - 1].append(
            WordTimestamp(word=w.word, start_ms=w.start_ms, end_ms=w.end_ms, confidence=1.0)
        )
    return per_scene


def audio_settings_from_timeline(timeline: Timeline) -> AudioSettings:
    """Return the AudioSettings the timeline's music fields describe."""
    return AudioSettings(
        music_volume=timeline.music_volume,
        ducking_enabled=timeline.music_ducking,
        playback_mode=timeline.music_playback_mode,
    )


def is_audio_key(key: str) -> bool:
    """True for a key the render treats as an audio file (mp3 / wav / m4a)."""
    return key.lower().endswith(_AUDIO_EXTS)


# ── Reading a run's inputs from storage ──────────────────────────────────────


async def resolve_audio_keys(
    storage, run_id: str, alignment: VoiceAlignmentArtifact | None
) -> tuple[str | None, str | None]:
    """Return (voiceover_key, music_key) for a run, as the render script will find them.

    The voiceover is the alignment's file when it names one, otherwise the first audio
    file in the run's voiceover folder (an operator upload). The music is the first
    audio file in the run's music folder, in the script's glob order (mp3, wav, m4a).
    """
    voiceover_key = alignment.mp3_r2_key if alignment and alignment.mp3_r2_key else None
    if voiceover_key is None:
        voiceover_key = _first_audio_key(await storage.list_keys(f"runs/{run_id}/voiceover/"))
    music_key = _first_audio_key(await storage.list_keys(f"runs/{run_id}/music/"))
    return voiceover_key, music_key


def _first_audio_key(keys: list[str]) -> str | None:
    """Pick the first key by extension priority mp3 > wav > m4a, then by name (the script's glob order)."""
    for ext in _AUDIO_EXTS:
        matches = sorted(k for k in keys if k.lower().endswith(ext))
        if matches:
            return matches[0]
    return None


async def build_run_timeline(
    storage,
    run_id: str,
    storyboard: Storyboard,
    manifest: AssetManifest,
    alignment: VoiceAlignmentArtifact | None,
    *,
    format_track: str = "landscape",
    captions: bool = True,
    caption_style: str = "standard",
) -> Timeline:
    """Build a run's Timeline: resolve the voiceover / music files from storage, then build_timeline.

    An alignment that cannot be resolved (a malformed artifact) is logged and the
    timeline falls back to the storyboard's own durations, as the render always has.
    """
    voiceover_key, music_key = await resolve_audio_keys(storage, run_id, alignment)
    settings = TimelineSettings(
        format_track=format_track, captions=captions, caption_style=caption_style,
        voiceover_key=voiceover_key, music_key=music_key,
    )
    try:
        return build_timeline(storyboard, manifest, alignment, settings)
    except MissingAssetsError:
        raise
    except Exception as exc:
        logger.warning("Timeline: could not resolve voice alignment for run %s: %s", run_id, exc)
        return build_timeline(storyboard, manifest, None, settings)
