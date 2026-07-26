"""Patch Applier worker (P5-S6) — `generated_script + patches → generated_script (v+1)`.

Node [9] in the Blueprint IR pipeline (D058). Pure deterministic function —
zero LLM calls. Applies each Patch from PatchSetArtifact to the current script
text via string operations. The artifact manager writes the result as a new
version of `generated_script` (e.g. @v2), so the original is preserved.

Pure worker per D040/D056.
"""

from datetime import UTC, datetime

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import (
    GeneratedScriptArtifact,
    Patch,
    PatchSetArtifact,
)
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

PATCH_APPLIER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",  # no LLM prompt — deterministic node
    model="none",
    sampling_params={},
)


def build_patch_applier_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a patch applier WorkerNode bound to storage.

    Reads:
      state.artifacts['generated_script'] → GeneratedScriptArtifact
      state.artifacts['patches']          → PatchSetArtifact

    Applies patches in order; skips any patch whose `target` is not found in the
    current script text (safe no-op). Emits a new GeneratedScriptArtifact with the
    patched script.

    Raises KeyError if either artifact reference is absent.
    """

    async def patch_applier(state: StageState) -> WorkerOutput:
        """Apply patches to the generated script; return updated GeneratedScriptArtifact."""
        script_key = state.artifacts.get("generated_script")
        if not script_key:
            raise KeyError(
                "state.artifacts['generated_script'] missing — "
                "script_generation must run before apply_patch"
            )
        patches_key = state.artifacts.get("patches")
        if not patches_key:
            raise KeyError(
                "state.artifacts['patches'] missing — "
                "patch_generation must run before apply_patch"
            )

        _, script_body = await read_artifact(storage, script_key)
        script_artifact = GeneratedScriptArtifact.model_validate(script_body)

        _, patches_body = await read_artifact(storage, patches_key)
        patch_set = PatchSetArtifact.model_validate(patches_body)

        patched_script = apply_patches(script_artifact.script, patch_set.patches)
        word_count = len(patched_script.split())

        artifact = GeneratedScriptArtifact(
            idea_title=script_artifact.idea_title,
            niche=script_artifact.niche,
            script=patched_script,
            word_count=word_count,
            target_duration_seconds=script_artifact.target_duration_seconds,
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact)

    return patch_applier


def apply_patches(script: str, patches: list[Patch]) -> str:
    """Apply a list of Patch objects to `script` sequentially; return the result.

    Each patch is applied exactly once (first occurrence). Patches whose `target`
    is not found are silently skipped. This is intentional: if a prior patch
    already removed the target, skipping is the correct behaviour.
    """
    result = script
    for patch in patches:
        result = _apply_one(result, patch)
    return result


def _apply_one(script: str, patch: Patch) -> str:
    """Apply a single Patch to script; return the (potentially unchanged) result."""
    if patch.target not in script:
        return script  # target not found — safe no-op

    if patch.operation == "replace":
        return script.replace(patch.target, patch.replacement or "", 1)
    elif patch.operation == "delete":
        return script.replace(patch.target, "", 1)
    elif patch.operation == "insert":
        idx = script.find(patch.target)
        insert_pos = idx + len(patch.target)
        return script[:insert_pos] + (patch.replacement or "") + script[insert_pos:]
    return script
