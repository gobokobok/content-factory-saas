"""Asset manifest builder — pure transformation from storyboard scenes to asset query entries."""

import logging

from pydantic import ValidationError

from src.exceptions import ManifestError
from src.models import AssetManifest, ManifestEntry, Storyboard

logger = logging.getLogger(__name__)


def build_manifest(run_id: str, storyboard_data: dict) -> AssetManifest:
    """
    Parse storyboard_data and produce an AssetManifest with one entry per scene.

    Maps visual prompt hierarchy:
      primary_stk   → primary_query
      fallback_stk  → fallback_query
      ai_generate   → ai_generate_prompt

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
        )
        for scene in storyboard.scenes
    ]

    logger.info("Built manifest for run '%s': %d scenes", run_id, len(entries))
    return AssetManifest(run_id=run_id, entries=entries)


def clip_type_breakdown(manifest: AssetManifest) -> dict[str, int]:
    """Return a count of entries grouped by clip_type."""
    counts: dict[str, int] = {}
    for entry in manifest.entries:
        counts[entry.clip_type] = counts.get(entry.clip_type, 0) + 1
    return counts
