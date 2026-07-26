"""Tests for cf_platform/workers/blueprint_merger.py (P5-S6).

Covers:
- Happy path: no corrections, no additions → blueprint unchanged (structurally)
- factual_corrections appended to blueprint.claims with [correction] prefix
- evidence_additions appended to blueprint.required_evidence (no duplicates)
- alignment_notes replaces direction_alignment_notes when non-empty
- alignment_notes ignored when empty string (keeps original)
- Missing blueprint artifact ref → KeyError
- Missing evaluation artifact ref → KeyError
- Registration: model='none'
- build_blueprint_merger_worker returns a callable
- _merge is exported and testable as a pure function
"""


import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, EvaluationArtifact, Section
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.blueprint_merger import (
    BLUEPRINT_MERGER_REGISTRATION,
    _merge,
    build_blueprint_merger_worker,
)

_NOW_DT = __import__("datetime").datetime(2026, 6, 18, tzinfo=__import__("datetime").timezone.utc)

_LINEAGE = LineageEnvelope(
    run_id="run-001",
    worker="test",
    worker_version="1.0.0",
    prompt_version="v1",
    model="none",
    created_at=_NOW_DT,
)


def _make_blueprint(
    claims: list | None = None,
    required_evidence: list | None = None,
    alignment_notes: str = "Original notes",
) -> Blueprint:
    return Blueprint(
        hook_angle="Hook angle",
        structure=[Section(title="S1", key_points=["kp1"])],
        claims=claims or ["Original claim"],
        monetization_angle="Monetize",
        required_evidence=required_evidence or ["Evidence 1"],
        signal_summary="Summary",
        direction_alignment_notes=alignment_notes,
    )


def _make_evaluation(
    corrections: list | None = None,
    alignment_notes: str = "",
    evidence_additions: list | None = None,
) -> EvaluationArtifact:
    return EvaluationArtifact(
        score=8.0,
        factual_corrections=corrections or [],
        alignment_notes=alignment_notes,
        evidence_additions=evidence_additions or [],
        passed=True,
        notes="",
    )


# ── Pure function tests (_merge) ────────────────────────────────────────


def test_merge_no_changes():
    """No corrections or additions → blueprint fields preserved."""
    bp = _make_blueprint()
    ev = _make_evaluation()
    merged = _merge(bp, ev)
    assert merged.claims == ["Original claim"]
    assert merged.required_evidence == ["Evidence 1"]
    assert merged.direction_alignment_notes == "Original notes"


def test_merge_factual_corrections_appended():
    """Corrections are appended with '[correction]' prefix."""
    bp = _make_blueprint(claims=["Claim A"])
    ev = _make_evaluation(corrections=["Fix B"])
    merged = _merge(bp, ev)
    assert "Claim A" in merged.claims
    assert "[correction] Fix B" in merged.claims


def test_merge_evidence_additions_appended():
    """Evidence additions are appended if not already present."""
    bp = _make_blueprint(required_evidence=["Evidence 1"])
    ev = _make_evaluation(evidence_additions=["New source", "Evidence 1"])  # dup
    merged = _merge(bp, ev)
    assert "New source" in merged.required_evidence
    # Duplicate should not be added
    assert merged.required_evidence.count("Evidence 1") == 1


def test_merge_alignment_notes_updated_when_nonempty():
    """Non-empty alignment_notes replaces direction_alignment_notes."""
    bp = _make_blueprint(alignment_notes="Original")
    ev = _make_evaluation(alignment_notes="Updated notes")
    merged = _merge(bp, ev)
    assert merged.direction_alignment_notes == "Updated notes"


def test_merge_alignment_notes_ignored_when_empty():
    """Empty alignment_notes keeps the original direction_alignment_notes."""
    bp = _make_blueprint(alignment_notes="Original")
    ev = _make_evaluation(alignment_notes="  ")  # whitespace only
    merged = _merge(bp, ev)
    assert merged.direction_alignment_notes == "Original"


def test_merge_structure_hook_angle_preserved():
    """Structure and hook_angle are copied verbatim."""
    bp = _make_blueprint()
    ev = _make_evaluation()
    merged = _merge(bp, ev)
    assert merged.hook_angle == bp.hook_angle
    assert merged.structure == bp.structure


# ── Worker tests ────────────────────────────────────────────────────────


async def _run_merger(
    storage: InMemoryArtifactStorage,
    blueprint: Blueprint | None,
    evaluation: EvaluationArtifact | None,
):
    artifacts: dict[str, str] = {}
    if blueprint is not None:
        a = await write_artifact(
            storage, blueprint, name="blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["blueprint"] = a.r2_key
    if evaluation is not None:
        a = await write_artifact(
            storage, evaluation, name="evaluation", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["evaluation"] = a.r2_key

    state = StageState(run_id="run-001", user_id="operator", inputs={}, artifacts=artifacts)
    worker = build_blueprint_merger_worker(storage)
    return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_blueprint():
    """Worker reads both artifacts and returns a Blueprint."""
    storage = InMemoryArtifactStorage()
    output = await _run_merger(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact, Blueprint)


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    """KeyError raised when blueprint artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="blueprint"):
        await _run_merger(storage, None, _make_evaluation())


@pytest.mark.asyncio
async def test_missing_evaluation_raises_key_error():
    """KeyError raised when evaluation artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="evaluation"):
        await _run_merger(storage, _make_blueprint(), None)


def test_registration_model_none():
    """BLUEPRINT_MERGER_REGISTRATION.model is 'none' — no LLM call."""
    assert BLUEPRINT_MERGER_REGISTRATION.model == "none"


def test_build_returns_callable():
    """build_blueprint_merger_worker returns a callable (the WorkerNode)."""
    storage = InMemoryArtifactStorage()
    worker = build_blueprint_merger_worker(storage)
    assert callable(worker)
