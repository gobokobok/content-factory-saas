"""Edits to an Animation storyboard's continuity bible (P-AN1-S4, D108).

The bible is the list of recurring characters, props and settings whose
descriptions are appended to the image prompt of every scene that uses them.
Editing a description therefore changes what those scenes' images should look
like: scenes that use the entry and already have an image are flagged
`image_out_of_date` so the operator can regenerate exactly those.

Pure functions — no storage, no HTTP (D040).
"""

from cf_platform.workers.animation_storyboard_worker import normalize_entity_id
from cf_platform.workers.scene_images import scene_has_image
from src.models import (
    CONTINUITY_KINDS,
    SCENE_FLAG_IMAGE_STALE,
    AssetManifest,
    ContinuityEntry,
    Storyboard,
    StoryboardScene,
)


class ContinuityEditError(ValueError):
    """Raised when a bible edit cannot be applied; the message is safe to show the operator."""


class ContinuityEntryNotFoundError(ContinuityEditError):
    """Raised when the bible has no entry with the given id."""


class ContinuityEntryInUseError(ContinuityEditError):
    """Raised when an entry that scenes still use is removed."""


def _entry(storyboard: Storyboard, entry_id: str) -> ContinuityEntry:
    """Return the bible entry with this id, or raise ContinuityEntryNotFoundError."""
    for entry in storyboard.continuity:
        if entry.id == entry_id:
            return entry
    raise ContinuityEntryNotFoundError(f"No continuity entry {entry_id!r}.")


def scenes_using(storyboard: Storyboard, entry_id: str) -> list[str]:
    """Ids of the scenes that list this bible entry, in storyboard order."""
    return [str(s.scene) for s in storyboard.scenes if entry_id in s.entities]


def _mark_stale(scene: StoryboardScene) -> StoryboardScene:
    """Return the scene flagged as having an out-of-date image (once)."""
    if SCENE_FLAG_IMAGE_STALE in scene.flags:
        return scene
    return scene.model_copy(update={"flags": [*scene.flags, SCENE_FLAG_IMAGE_STALE]})


def _validated_kind(kind: str) -> str:
    """Return a valid continuity kind or raise ContinuityEditError."""
    if kind not in CONTINUITY_KINDS:
        raise ContinuityEditError(f"Kind must be one of {list(CONTINUITY_KINDS)}.")
    return kind


def edit_entry(
    storyboard: Storyboard,
    manifest: AssetManifest | None,
    entry_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    kind: str | None = None,
) -> tuple[Storyboard, list[str]]:
    """Change a bible entry; returns the storyboard and the scenes whose image is now out of date.

    Only the fields given change. A changed name or description alters the prompt
    of every scene using the entry, so those that already have an image are
    flagged. A changed kind alone alters nothing that is sent to the model.
    """
    entry = _entry(storyboard, entry_id)
    update: dict[str, str] = {}
    if name is not None:
        if not name.strip():
            raise ContinuityEditError("An entry needs a name.")
        update["name"] = name.strip()
    if description is not None:
        if not description.strip():
            raise ContinuityEditError("An entry needs a description — it is what keeps the subject the same.")
        update["description"] = description.strip()
    if kind is not None:
        update["kind"] = _validated_kind(kind)
    changed_prompt = any(update.get(f) not in (None, getattr(entry, f)) for f in ("name", "description"))
    continuity = [e.model_copy(update=update) if e.id == entry_id else e for e in storyboard.continuity]

    stale: list[str] = []
    scenes = list(storyboard.scenes)
    if changed_prompt:
        for i, scene in enumerate(scenes):
            if entry_id in scene.entities and scene_has_image(scene, manifest):
                scenes[i] = _mark_stale(scene)
                stale.append(str(scene.scene))
    return storyboard.model_copy(update={"continuity": continuity, "scenes": scenes}), stale


def add_entry(storyboard: Storyboard, *, kind: str, name: str, description: str) -> tuple[Storyboard, ContinuityEntry]:
    """Add a bible entry; its id is derived from the name and made unique."""
    if not name.strip():
        raise ContinuityEditError("An entry needs a name.")
    if not description.strip():
        raise ContinuityEditError("An entry needs a description — it is what keeps the subject the same.")
    base = normalize_entity_id(name) or "entry"
    taken = {e.id for e in storyboard.continuity}
    entry_id, n = base, 2
    while entry_id in taken:
        entry_id, n = f"{base}_{n}", n + 1
    entry = ContinuityEntry(id=entry_id, kind=_validated_kind(kind), name=name.strip(), description=description.strip())
    return storyboard.model_copy(update={"continuity": [*storyboard.continuity, entry]}), entry


def remove_entry(storyboard: Storyboard, entry_id: str) -> Storyboard:
    """Remove a bible entry no scene uses; ContinuityEntryInUseError names the scenes otherwise."""
    _entry(storyboard, entry_id)
    used = scenes_using(storyboard, entry_id)
    if used:
        raise ContinuityEntryInUseError(
            f"Scene{'s' if len(used) != 1 else ''} {', '.join(used)} still use{'s' if len(used) == 1 else ''} "
            "this entry — take it off those scenes first."
        )
    return storyboard.model_copy(update={"continuity": [e for e in storyboard.continuity if e.id != entry_id]})


def set_scene_entities(
    storyboard: Storyboard, manifest: AssetManifest | None, scene_id: str, entity_ids: list[str]
) -> tuple[Storyboard, bool]:
    """Set which bible entries a scene uses; returns the storyboard and whether its image went out of date.

    Unknown ids are refused. Changing the list changes the scene's prompt, so a
    scene that already has an image is flagged.
    """
    known = {e.id for e in storyboard.continuity}
    unknown = [e for e in entity_ids if e not in known]
    if unknown:
        raise ContinuityEntryNotFoundError(f"No continuity entry {unknown[0]!r}.")
    wanted = list(dict.fromkeys(entity_ids))
    stale = False
    scenes = list(storyboard.scenes)
    for i, scene in enumerate(scenes):
        if str(scene.scene) != scene_id or scene.entities == wanted:
            continue
        scene = scene.model_copy(update={"entities": wanted})
        if scene_has_image(scene, manifest):
            scene, stale = _mark_stale(scene), True
        scenes[i] = scene
    return storyboard.model_copy(update={"scenes": scenes}), stale
