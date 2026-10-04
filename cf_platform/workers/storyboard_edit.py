"""Storyboard boundary edits (P13-S2, P13-S4) — split, merge, replace all boundaries.

Scene boundaries are word indices into the normalised Deepgram word list (P9-S9).
Every edit here is expressed as a new list of scene start words and goes through
one function, replace_boundaries, which recomputes timing with the same
_reify_scene the StoryboardWorker uses, renumbers the scenes, rebuilds
render_options through _apply_patches_and_render_options, and keeps the asset
manifest aligned with the renumbered scenes.

One rule decides what a scene keeps (operator decisions, 2026-10-03):

- a scene whose start word is unchanged is the same scene: it keeps all its
  fields and its asset, even if its end moved;
- a scene that starts at a new word was cut from the scene that contained that
  word: it inherits the visual fields, starts with no on-screen text and no SFX,
  and needs an asset;
- a scene whose start word disappears was merged into the one before it: its
  on-screen text and SFX are dropped, and so is its manifest entry.

Voiceover text is never changed here (D095): changing words forces re-voicing.
Pure functions — no storage, no HTTP (D040).
"""

import os
import re
from dataclasses import dataclass, field

from cf_platform.workers.acquisition_worker import entry_has_asset, manifest_entry_for_scene
from cf_platform.workers.storyboard_worker import (
    _apply_patches_and_render_options,
    _reify_scene,
    apply_asset_strategy,
    rederive_scene_visual_contract,
)
from cf_platform.workers.voice_production import VoiceWordTimestamp
from src.models import (
    AWAITING_UPLOAD_STATUS,
    OPERATOR_SUPPLIED_STRATEGIES,
    AssetManifest,
    ManifestEntry,
    Storyboard,
    StoryboardScene,
)

# Fields a newly cut scene copies from the scene it was cut from. person_name /
# person_title are deliberately absent: _apply_patches_and_render_options turns a
# Character scene's person_name into its on-screen text, and a cut scene starts
# with none.
_INHERITED_FIELDS = (
    "segment_type", "primary_stk", "context_stk", "concept_stk", "visual_prompts",
    "historic", "semantic_context", "asset_strategy", "asset_mode",
)

# Fields _reify_scene owns; cleared before it runs so nothing stale survives.
_REIFIED_FIELDS = (
    "voiceover_line", "duration_s", "scene_start_ms", "scene_end_ms",
    "asset_tier", "clip_type", "motion_effect",
)

_CHANGE_TEXT_HINT = (
    "The text differs from the voiceover by more than paragraph breaks. "
    "Change the wording in the Script stage — it forces re-voicing."
)


class StoryboardEditError(ValueError):
    """A boundary edit was rejected; the message is safe to show the operator."""


class LastSceneMergeError(StoryboardEditError):
    """Merge was requested on the last scene, which has no next scene."""


@dataclass
class BoundaryEdit:
    """Result of a boundary edit: the new storyboard, the realigned manifest, and a summary."""

    storyboard: Storyboard
    # None when the run has no acquired manifest yet — there is nothing to realign.
    manifest: AssetManifest | None
    scenes_before: int
    scenes_after: int
    # Old scenes that were merged away with on-screen text or SFX: {scene, on_screen_text, sfx}.
    dropped: list[dict] = field(default_factory=list)
    # New scene ids without an acquired asset. Empty when manifest is None.
    needs_acquisition: list[str] = field(default_factory=list)


def scene_start_words(storyboard: Storyboard) -> list[int]:
    """Return every scene's start word, in order. Raises if the storyboard has none.

    Storyboards generated without voice timestamps (prompt v0.12) carry no word
    indices and cannot be edited by boundary.
    """
    starts: list[int] = []
    for scene in storyboard.scenes:
        if scene.start_word is None:
            raise StoryboardEditError(
                "This storyboard has no word boundaries (it was generated without "
                "voice timestamps). Regenerate the storyboard after the Voice stage."
            )
        starts.append(scene.start_word)
    return sorted(starts)


def _has_sfx(scene: StoryboardScene) -> bool:
    """True when the scene carries a real sound effect (not empty, not 'silence')."""
    return bool(scene.sfx) and scene.sfx.lower() != "silence"


def _is_video_file(file_key: str) -> bool:
    """True when an asset key is footage — anything that is not an image (D089)."""
    from src.ffmpeg_builder import _IMAGE_EXTS

    return os.path.splitext(file_key)[1].lower() not in _IMAGE_EXTS


def _validate_start_words(start_words: list[int], n_words: int) -> None:
    """Reject a boundary list that is not 0-based, strictly increasing and in range."""
    if not start_words:
        raise StoryboardEditError("At least one scene is required.")
    if start_words[0] != 0:
        raise StoryboardEditError("The first scene must start at word 0.")
    for prev, cur in zip(start_words, start_words[1:]):
        if cur <= prev:
            raise StoryboardEditError(
                f"Scene boundaries must be strictly increasing (got {prev} then {cur})."
            )
    if start_words[-1] >= n_words:
        raise StoryboardEditError(
            f"Scene boundary {start_words[-1]} is outside the voiceover ({n_words} words)."
        )


def replace_boundaries(
    storyboard: Storyboard,
    words: list[VoiceWordTimestamp],
    start_words: list[int],
    manifest: AssetManifest | None = None,
    min_scene_s: float = 0.0,
) -> BoundaryEdit:
    """Replace all scene boundaries at once and recompute everything that follows from them.

    start_words lists the first word of every scene; each scene ends where the
    next begins and the last ends at the final word, so the result is contiguous
    by construction. Only scenes whose word span changed are checked against
    min_scene_s — a short scene the generator produced does not block an edit
    elsewhere.
    """
    n_words = len(words)
    if n_words == 0:
        raise StoryboardEditError("No word timestamps for this run — generate the voiceover first.")
    old_starts = scene_start_words(storyboard)
    _validate_start_words(start_words, n_words)

    old_scenes = sorted(storyboard.scenes, key=lambda s: s.start_word or 0)
    old_by_start = {s.start_word: s for s in old_scenes}
    old_entries: dict[str, ManifestEntry] = (
        {e.scene_id: e for e in manifest.entries} if manifest and manifest.entries else {}
    )

    new_scenes: list[StoryboardScene] = []
    new_entries: list[ManifestEntry] = []

    for k, start in enumerate(start_words):
        end = (start_words[k + 1] - 1) if k + 1 < len(start_words) else n_words - 1
        new_id = str(k + 1)
        kept = start in old_by_start
        # The scene this one continues (same start word) or was cut from.
        source = old_by_start[start] if kept else next(
            s for s in reversed(old_scenes) if (s.start_word or 0) <= start
        )
        span_changed = not kept or source.end_word != end

        if span_changed:
            span_s = (words[end].end_ms - words[start].start_ms) / 1000
            if span_s < min_scene_s:
                line = " ".join(w.word for w in words[start : end + 1])
                raise StoryboardEditError(
                    f"Scene {new_id} (“{line}”) would last {span_s:.2f}s — "
                    f"shorter than the {min_scene_s:g}s minimum."
                )

        if kept:
            raw = source.model_dump(by_alias=True, mode="json")
        else:
            full = source.model_dump(by_alias=True, mode="json")
            raw = {name: full.get(name) for name in _INHERITED_FIELDS}
        for name in _REIFIED_FIELDS:
            raw.pop(name, None)
        raw.pop("render_options", None)
        raw.update(scene=new_id, start_word=start, end_word=end)
        _reify_scene(raw, words, k)
        scene = StoryboardScene.model_validate(raw)

        old_entry = old_entries.get(source.scene) if kept else None
        if kept and not span_changed:
            # Untouched scene: keeps every field exactly as it was.
            scene = scene.model_copy(update={
                "asset_tier": source.asset_tier,
                "clip_type": source.clip_type,
                "motion_effect": source.motion_effect,
            })
        elif entry_has_asset(old_entry):
            # Kept asset, new length: the file on disk decides how it renders (D089).
            tier, clip_type, effect = rederive_scene_visual_contract(
                scene.duration_s, _is_video_file(old_entry.file_key), source.motion_effect
            )
            scene = scene.model_copy(update={
                "asset_tier": tier, "clip_type": clip_type, "motion_effect": effect,
            })
        elif scene.asset_strategy in ("stock_image", "stock_video", "ai_image"):
            if kept:
                scene = scene.model_copy(update={"motion_effect": source.motion_effect})
            scene = apply_asset_strategy(scene, scene.asset_strategy)
        elif kept and source.motion_effect and scene.clip_type == "still_with_motion":
            scene = scene.model_copy(update={"motion_effect": source.motion_effect})
        new_scenes.append(scene)

        if old_entries:
            if old_entry is not None:
                entry = old_entry.model_copy(update={
                    "scene_id": new_id,
                    "duration_s": scene.duration_s,
                    "clip_type": scene.clip_type,
                    "asset_tier": scene.asset_tier,
                    "asset_strategy": scene.asset_strategy,
                })
            else:
                entry = manifest_entry_for_scene(scene)
                if scene.asset_strategy in OPERATOR_SUPPLIED_STRATEGIES:
                    entry.status = AWAITING_UPLOAD_STATUS
            new_entries.append(entry)

    new_start_set = set(start_words)
    dropped = [
        {"scene": s.scene, "on_screen_text": s.on_screen_text, "sfx": s.sfx if _has_sfx(s) else None}
        for s in old_scenes
        if s.start_word not in new_start_set and (s.on_screen_text or _has_sfx(s))
    ]

    clip_abbrs = {"hard_cut": "HC", "still_with_motion": "SM", "animated": "AN"}
    rhythm = " / ".join(clip_abbrs.get(s.clip_type, "?") for s in new_scenes[:8])
    if len(new_scenes) > 8:
        rhythm += " …"
    summary = storyboard.summary.model_copy(update={
        "total_scenes": len(new_scenes),
        "total_duration_s": round(sum(s.duration_s for s in new_scenes), 3),
        "rhythm": rhythm,
    })
    edited = _apply_patches_and_render_options(
        storyboard.model_copy(update={"scenes": new_scenes, "summary": summary}), []
    )

    new_manifest = (
        AssetManifest(run_id=manifest.run_id, entries=new_entries)
        if manifest is not None and old_entries else None
    )
    return BoundaryEdit(
        storyboard=edited,
        manifest=new_manifest,
        scenes_before=len(old_starts),
        scenes_after=len(new_scenes),
        dropped=dropped,
        needs_acquisition=[e.scene_id for e in new_entries if not entry_has_asset(e)],
    )


def _find_scene(storyboard: Storyboard, scene_id: str) -> tuple[int, StoryboardScene]:
    """Return (position, scene) for a scene id among the scenes ordered by start word."""
    scene_start_words(storyboard)  # raises when the storyboard has no word boundaries
    ordered = sorted(storyboard.scenes, key=lambda s: s.start_word or 0)
    for i, scene in enumerate(ordered):
        if str(scene.scene) == scene_id:
            return i, scene
    raise KeyError(scene_id)


def split_scene(
    storyboard: Storyboard,
    words: list[VoiceWordTimestamp],
    scene_id: str,
    at_word: int,
    manifest: AssetManifest | None = None,
    min_scene_s: float = 0.0,
) -> BoundaryEdit:
    """Split one scene in two; at_word becomes the first word of the new second scene.

    Raises KeyError for an unknown scene, StoryboardEditError unless
    start_word < at_word <= end_word.
    """
    _, scene = _find_scene(storyboard, scene_id)
    start, end = scene.start_word, scene.end_word
    if start is None or end is None or not (start < at_word <= end):
        raise StoryboardEditError(
            f"Scene {scene_id} covers words {start}–{end}; a split point must be "
            f"after its first word and no later than its last (got {at_word})."
        )
    starts = sorted([*scene_start_words(storyboard), at_word])
    return replace_boundaries(storyboard, words, starts, manifest, min_scene_s)


def merge_scene(
    storyboard: Storyboard,
    words: list[VoiceWordTimestamp],
    scene_id: str,
    manifest: AssetManifest | None = None,
    min_scene_s: float = 0.0,
) -> BoundaryEdit:
    """Merge a scene with the one after it; the first scene's fields and asset win.

    Raises KeyError for an unknown scene, LastSceneMergeError on the last scene.
    """
    position, _ = _find_scene(storyboard, scene_id)
    starts = scene_start_words(storyboard)
    if position >= len(starts) - 1:
        raise LastSceneMergeError(f"Scene {scene_id} is the last scene — there is nothing to merge it with.")
    del starts[position + 1]
    return replace_boundaries(storyboard, words, starts, manifest, min_scene_s)


def start_words_from_text(words: list[VoiceWordTimestamp], text: str) -> list[int]:
    """Turn script-view text (one paragraph per scene) into scene start words.

    Paragraphs are separated by blank lines. The words themselves must be exactly
    the voiceover's words in order — only the paragraph breaks may differ.
    """
    paragraphs = [p.split() for p in re.split(r"\n\s*\n", text.strip())]
    paragraphs = [p for p in paragraphs if p]
    typed = [token for paragraph in paragraphs for token in paragraph]
    spoken = [token for w in words for token in w.word.split()]
    if typed != spoken:
        raise StoryboardEditError(_CHANGE_TEXT_HINT)

    starts: list[int] = []
    position = 0
    for paragraph in paragraphs:
        starts.append(position)
        position += len(paragraph)
    return starts
