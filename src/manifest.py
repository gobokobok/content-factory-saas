"""Asset manifest builder — pure transformation from storyboard scenes to asset query entries."""

import logging

from pydantic import ValidationError

from src.exceptions import ManifestError
from src.models import AssetManifest, ManifestEntry, Storyboard
from src.storage import R2Client

logger = logging.getLogger(__name__)

# Only these fields may be updated via patch_manifest_entry.
_PATCHABLE_MANIFEST_FIELDS = {"asset_mode"}

# All clip types default to stock acquisition.  Operators can override
# per-scene via the manifest patch endpoint or the storyboard asset_mode field.
_STOCK_CLIP_TYPES = {"hard_cut", "still_with_motion", "animated"}


def _default_asset_mode(clip_type: str) -> str:
    """Return the default asset_mode for a given clip_type (always 'stock')."""
    return "stock" if clip_type in _STOCK_CLIP_TYPES else "ai_generated"


def build_manifest(run_id: str, storyboard_data: dict) -> AssetManifest:
    """
    Parse storyboard_data and produce an AssetManifest with one entry per scene.

    Maps visual prompt hierarchy:
      primary_stk   → primary_query
      fallback_stk  → fallback_query
      ai_generate   → ai_generate_prompt

    asset_mode is taken from scene.asset_mode when the operator has set it,
    otherwise falls back to "stock" for all clip types (hard_cut,
    still_with_motion, animated).  Operators can override per-scene.

    Raises ManifestError if storyboard_data does not conform to the Storyboard schema.
    """
    try:
        storyboard = Storyboard.model_validate(storyboard_data)
    except ValidationError as exc:
        raise ManifestError(f"Invalid storyboard data: {exc}") from exc

    entries = [
        ManifestEntry(
            scene_id=scene.scene,
            clip_type=scene.clip_type,
            primary_query=scene.visual_prompts.primary_stk,
            fallback_query=scene.visual_prompts.fallback_stk,
            ai_generate_prompt=scene.visual_prompts.ai_generate,
            historic=scene.historic,
            asset_mode=scene.asset_mode or _default_asset_mode(scene.clip_type),
            person_name=scene.person_name,
            person_title=scene.person_title,
            duration_s=scene.duration_s,
        )
        for scene in storyboard.scenes
    ]

    logger.info("Built manifest for run '%s': %d scenes", run_id, len(entries))
    return AssetManifest(run_id=run_id, entries=entries)


def patch_manifest_entry(
    run_id: str,
    scene_id: str,
    field: str,
    value: str,
    storage: R2Client,
) -> AssetManifest:
    """Update a single patchable field on one manifest entry and persist to R2.

    Only fields in _PATCHABLE_MANIFEST_FIELDS may be updated. asset_mode must be
    one of the allowed Literal values.

    Raises ValueError for unknown field or invalid value.
    Raises ManifestError if the scene_id is not found.
    Propagates StorageError on R2 read/write failure.
    """
    if field not in _PATCHABLE_MANIFEST_FIELDS:
        raise ValueError(f"Field '{field}' is not patchable. Allowed: {_PATCHABLE_MANIFEST_FIELDS}")


    manifest_key = f"runs/{run_id}/asset_manifest.json"
    manifest_data = storage.get_json(manifest_key)
    manifest = AssetManifest.model_validate(manifest_data)

    entry = next((e for e in manifest.entries if e.scene_id == scene_id), None)
    if entry is None:
        raise ManifestError(f"Scene '{scene_id}' not found in manifest for run '{run_id}'")

    if field == "asset_mode":
        allowed = {"stock", "ai_generated"}
        if value not in allowed:
            raise ValueError(f"Invalid asset_mode '{value}'. Allowed: {allowed}")
        entry.asset_mode = value  # type: ignore[assignment]

    storage.upload_json(manifest_key, manifest.model_dump(mode="json"))
    return manifest


def clip_type_breakdown(manifest: AssetManifest) -> dict[str, int]:
    """Return a count of entries grouped by clip_type."""
    counts: dict[str, int] = {}
    for entry in manifest.entries:
        counts[entry.clip_type] = counts.get(entry.clip_type, 0) + 1
    return counts
