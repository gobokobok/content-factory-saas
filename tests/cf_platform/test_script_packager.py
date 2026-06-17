"""Tests for cf_platform/workers/script_packager.py (P5-S5).

Covers:
- Happy path: reads script_drafts + script_scores, picks best draft, emits ScriptArtifact
- idea_title propagated from ScriptDraftsArtifact
- niche propagated (Optional[str] — None on direct entry)
- draft_number matches best_draft_number from ScriptScoresArtifact
- overall_score matches best_score from ScriptScoresArtifact
- Picks the correct draft when multiple drafts are present
- Missing script_drafts artifact → KeyError
- Missing script_scores artifact → KeyError
- best_draft_number not found in drafts → ValueError
- Registration pin: model="none"
- Registration pin: worker_version and prompt_version
- build_script_packager_worker returns a callable
"""

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.schemas import IdeaToScriptState, StageState, WorkerOutput
from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerRegistry, WorkerRegistration, wrap
from cf_platform.workers.script_packager import (
    SCRIPT_PACKAGER_REGISTRATION,
    ScriptArtifact,
    build_script_packager_worker,
)
from cf_platform.workers.script_quality_scorer import ScriptDraftScore, ScriptScoresArtifact
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
_IDEA_TITLE = "Why Starter Homes Vanished"
_NICHE = "US housing"


def _make_drafts_artifact(drafts: list[ScriptDraft], niche: Optional[str] = _NICHE) -> ScriptDraftsArtifact:
    return ScriptDraftsArtifact(
        idea_title=_IDEA_TITLE,
        niche=niche,
        idea_angle=None,
        drafts=drafts,
        generated_at=_NOW,
    )


def _make_scores_artifact(best_draft_number: int = 1, best_score: float = 8.5) -> ScriptScoresArtifact:
    return ScriptScoresArtifact(
        idea_title=_IDEA_TITLE,
        scored_drafts=[
            ScriptDraftScore(
                draft_number=best_draft_number,
                hook_strength=8.0,
                data_quality=8.0,
                narrative_flow=8.0,
                virality_potential=9.0,
                overall_score=best_score,
            )
        ],
        best_draft_number=best_draft_number,
        best_score=best_score,
        generated_at=_NOW,
    )


async def _run_packager(
    storage: InMemoryArtifactStorage,
    drafts_artifact: Optional[ScriptDraftsArtifact],
    scores_artifact: Optional[ScriptScoresArtifact],
) -> WorkerOutput:
    """Helper: write artifacts to storage, build state, call packager, return WorkerOutput."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    lineage = LineageEnvelope(
        run_id="run-001",
        worker="test",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=_NOW,
    )

    artifacts: dict[str, str] = {}
    if drafts_artifact is not None:
        a = await write_artifact(
            storage, drafts_artifact, name="script_drafts", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=lineage,
        )
        artifacts["script_drafts"] = a.r2_key
    if scores_artifact is not None:
        a = await write_artifact(
            storage, scores_artifact, name="script_scores", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=lineage,
        )
        artifacts["script_scores"] = a.r2_key

    state = StageState(run_id="run-001", user_id="operator", inputs={}, artifacts=artifacts)
    worker = build_script_packager_worker(storage)
    return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_script_artifact():
    """Packager reads both artifacts and emits a ScriptArtifact."""
    storage = InMemoryArtifactStorage()
    draft = ScriptDraft(draft_number=1, script="In 1980 the average family could save for a home in 3 years.")
    output = await _run_packager(
        storage,
        _make_drafts_artifact([draft]),
        _make_scores_artifact(best_draft_number=1, best_score=8.5),
    )
    assert isinstance(output.artifact, ScriptArtifact)
    artifact = output.artifact
    assert artifact.script == draft.script
    assert artifact.draft_number == 1
    assert artifact.overall_score == 8.5


@pytest.mark.asyncio
async def test_idea_title_propagated():
    """ScriptArtifact.idea_title matches the drafts artifact."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage,
        _make_drafts_artifact([ScriptDraft(draft_number=1, script="s")]),
        _make_scores_artifact(),
    )
    assert output.artifact.idea_title == _IDEA_TITLE  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_niche_propagated():
    """ScriptArtifact.niche matches the drafts artifact niche."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage,
        _make_drafts_artifact([ScriptDraft(draft_number=1, script="s")], niche=_NICHE),
        _make_scores_artifact(),
    )
    assert output.artifact.niche == _NICHE  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_niche_none_on_direct_entry():
    """ScriptArtifact.niche is None when the drafts artifact was produced via direct entry."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage,
        _make_drafts_artifact([ScriptDraft(draft_number=1, script="s")], niche=None),
        _make_scores_artifact(),
    )
    assert output.artifact.niche is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_picks_correct_draft_from_multiple():
    """When multiple drafts are present, picks the one matching best_draft_number."""
    storage = InMemoryArtifactStorage()
    drafts = [
        ScriptDraft(draft_number=1, script="Draft one."),
        ScriptDraft(draft_number=2, script="Draft two — the best."),
        ScriptDraft(draft_number=3, script="Draft three."),
    ]
    scores = ScriptScoresArtifact(
        idea_title=_IDEA_TITLE,
        scored_drafts=[
            ScriptDraftScore(draft_number=2, hook_strength=9.0, data_quality=9.0,
                             narrative_flow=9.0, virality_potential=9.0, overall_score=9.0),
        ],
        best_draft_number=2,
        best_score=9.0,
        generated_at=_NOW,
    )
    output = await _run_packager(storage, _make_drafts_artifact(drafts), scores)
    assert output.artifact.script == "Draft two — the best."  # type: ignore[union-attr]
    assert output.artifact.draft_number == 2  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_missing_script_drafts_raises_key_error():
    """KeyError is raised when script_drafts artifact is absent from state."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="script_drafts"):
        await _run_packager(storage, None, _make_scores_artifact())


@pytest.mark.asyncio
async def test_missing_script_scores_raises_key_error():
    """KeyError is raised when script_scores artifact is absent from state."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="script_scores"):
        await _run_packager(
            storage,
            _make_drafts_artifact([ScriptDraft(draft_number=1, script="s")]),
            None,
        )


@pytest.mark.asyncio
async def test_best_draft_number_not_found_raises_value_error():
    """ValueError is raised when best_draft_number has no matching draft."""
    storage = InMemoryArtifactStorage()
    # Scores say best is draft 99, but only draft 1 exists.
    with pytest.raises(ValueError, match="best_draft_number=99"):
        await _run_packager(
            storage,
            _make_drafts_artifact([ScriptDraft(draft_number=1, script="s")]),
            _make_scores_artifact(best_draft_number=99),
        )


def test_registration_model_is_none():
    """SCRIPT_PACKAGER_REGISTRATION.model is 'none' — no LLM call."""
    assert SCRIPT_PACKAGER_REGISTRATION.model == "none"


def test_registration_worker_version():
    """SCRIPT_PACKAGER_REGISTRATION pins worker_version."""
    assert SCRIPT_PACKAGER_REGISTRATION.worker_version == "1.0.0"


def test_registration_prompt_version():
    """SCRIPT_PACKAGER_REGISTRATION pins prompt_version."""
    assert SCRIPT_PACKAGER_REGISTRATION.prompt_version == "v1"


def test_build_returns_callable():
    """build_script_packager_worker returns a callable (the WorkerNode)."""
    storage = InMemoryArtifactStorage()
    worker = build_script_packager_worker(storage)
    assert callable(worker)
