"""Tests for cf_platform/workers/patch_applier.py (P5-S6).

Covers:
- apply_patches: replace operation replaces first occurrence only
- apply_patches: delete operation removes target text
- apply_patches: insert operation inserts replacement after target
- apply_patches: missing target is a no-op (safe)
- apply_patches: multiple patches applied sequentially
- apply_patches: empty patches list returns script unchanged
- apply_patches: patch whose target was removed by prior patch is skipped
- Worker: happy path reads generated_script + patches, emits new GeneratedScriptArtifact
- Worker: empty patch set leaves script unchanged
- Worker: missing generated_script raises KeyError
- Worker: missing patches raises KeyError
- word_count updated after patching
- Registration: model='none'
- build_patch_applier_worker returns a callable
"""

from datetime import UTC, datetime

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import GeneratedScriptArtifact, Patch, PatchSetArtifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.patch_applier import (
    PATCH_APPLIER_REGISTRATION,
    apply_patches,
    build_patch_applier_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=UTC)
_LINEAGE = LineageEnvelope(
    run_id="run-001",
    worker="test",
    worker_version="1.0.0",
    prompt_version="v1",
    model="none",
    created_at=_NOW,
)


# ── Pure function tests (apply_patches) ────────────────────────────────


def test_replace_operation():
    result = apply_patches("Hello world", [Patch(operation="replace", target="Hello", replacement="Hi")])
    assert result == "Hi world"


def test_delete_operation():
    result = apply_patches("Hello bad world", [Patch(operation="delete", target=" bad")])
    assert result == "Hello world"


def test_insert_operation():
    result = apply_patches(
        "Hello world",
        [Patch(operation="insert", target="Hello", replacement=" beautiful")],
    )
    assert result == "Hello beautiful world"


def test_missing_target_is_no_op():
    result = apply_patches("Hello world", [Patch(operation="replace", target="xyz", replacement="abc")])
    assert result == "Hello world"


def test_multiple_patches_applied_sequentially():
    patches = [
        Patch(operation="replace", target="Hello", replacement="Hi"),
        Patch(operation="replace", target="world", replacement="there"),
    ]
    result = apply_patches("Hello world", patches)
    assert result == "Hi there"


def test_empty_patch_list_unchanged():
    result = apply_patches("Hello world", [])
    assert result == "Hello world"


def test_replace_only_first_occurrence():
    result = apply_patches(
        "bad bad good",
        [Patch(operation="replace", target="bad", replacement="ok")],
    )
    assert result == "ok bad good"


def test_prior_patch_removes_target_for_later_patch():
    """If a prior patch removes the target of a later patch, later patch is skipped safely."""
    patches = [
        Patch(operation="delete", target=" bad phrase"),
        Patch(operation="replace", target=" bad phrase", replacement="x"),  # target gone
    ]
    result = apply_patches("Text with bad phrase end", patches)
    assert result == "Text with end"


# ── Worker tests ────────────────────────────────────────────────────────


def _make_script_artifact(script: str = "In 1980 homes were affordable.") -> GeneratedScriptArtifact:
    return GeneratedScriptArtifact(
        idea_title="Why Starter Homes Vanished",
        niche="housing",
        script=script,
        word_count=len(script.split()),
        target_duration_seconds=60,
        generated_at=_NOW,
    )


def _make_patches_artifact(patches: list[Patch]) -> PatchSetArtifact:
    return PatchSetArtifact(patches=patches, generated_at=_NOW)


async def _run_applier(
    storage: InMemoryArtifactStorage,
    script_artifact: GeneratedScriptArtifact | None,
    patch_artifact: PatchSetArtifact | None,
):
    artifacts: dict[str, str] = {}
    if script_artifact is not None:
        a = await write_artifact(
            storage, script_artifact, name="generated_script", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["generated_script"] = a.r2_key
    if patch_artifact is not None:
        a = await write_artifact(
            storage, patch_artifact, name="patches", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["patches"] = a.r2_key

    state = StageState(run_id="run-001", user_id="operator", inputs={}, artifacts=artifacts)
    worker = build_patch_applier_worker(storage)
    return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_applies_patch():
    """Worker replaces text in the script and returns a new GeneratedScriptArtifact."""
    storage = InMemoryArtifactStorage()
    script = "In 1980 homes were affordable."
    patch = Patch(operation="replace", target="1980", replacement="1970")
    output = await _run_applier(
        storage,
        _make_script_artifact(script),
        _make_patches_artifact([patch]),
    )
    assert isinstance(output.artifact, GeneratedScriptArtifact)
    assert "1970" in output.artifact.script


@pytest.mark.asyncio
async def test_empty_patches_script_unchanged():
    """Empty patch list leaves the script text unchanged."""
    storage = InMemoryArtifactStorage()
    script = "Original script text."
    output = await _run_applier(storage, _make_script_artifact(script), _make_patches_artifact([]))
    assert output.artifact.script == script


@pytest.mark.asyncio
async def test_word_count_updated_after_patch():
    """word_count in the output artifact reflects the patched script length."""
    storage = InMemoryArtifactStorage()
    script = "short script"
    patch = Patch(operation="replace", target="short", replacement="much longer")
    output = await _run_applier(
        storage, _make_script_artifact(script), _make_patches_artifact([patch])
    )
    expected = len("much longer script".split())
    assert output.artifact.word_count == expected


@pytest.mark.asyncio
async def test_missing_generated_script_raises_key_error():
    """KeyError raised when generated_script artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="generated_script"):
        await _run_applier(storage, None, _make_patches_artifact([]))


@pytest.mark.asyncio
async def test_missing_patches_raises_key_error():
    """KeyError raised when patches artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="patches"):
        await _run_applier(storage, _make_script_artifact(), None)


def test_registration_model_none():
    """PATCH_APPLIER_REGISTRATION.model is 'none' — no LLM call."""
    assert PATCH_APPLIER_REGISTRATION.model == "none"


def test_build_returns_callable():
    """build_patch_applier_worker returns a callable."""
    storage = InMemoryArtifactStorage()
    worker = build_patch_applier_worker(storage)
    assert callable(worker)
