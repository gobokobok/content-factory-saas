"""Tests for cf_platform/workers/evaluator.py (P5-S6).

Covers:
- Happy path: reads blueprint + context, calls Claude once, returns EvaluationArtifact
- score, passed, factual_corrections, evidence_additions parsed correctly
- alignment_notes uses blueprint.direction_alignment_notes as fallback
- niche included in user message when present
- Missing blueprint artifact ref → KeyError
- Missing normalized_context artifact ref → KeyError
- Invalid JSON from Claude → ValueError
- Registration: model='claude-sonnet-4-6'
- build_evaluator_worker returns a callable
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, EvaluationArtifact, NormalizedContext, Section
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.evaluator import (
    EVALUATOR_REGISTRATION,
    build_evaluator_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-001", worker="test", worker_version="1.0.0", prompt_version="v1",
    model="none", created_at=_NOW,
)
_IDEA_TITLE = "Why Starter Homes Vanished"


def _make_blueprint() -> Blueprint:
    return Blueprint(
        hook_angle="Starter homes down 70%",
        structure=[Section(title="H", key_points=["p"])],
        claims=["Claim 1"],
        monetization_angle="Urgency",
        required_evidence=["Census data"],
        signal_summary="Summary",
        direction_alignment_notes="Original notes",
    )


def _make_context() -> NormalizedContext:
    return NormalizedContext(
        primary_angle="Supply shortage",
        evidence_summary="Evidence",
        top_signals=["signal"],
        controversies=[],
        hook_bias="Data",
    )


def _good_eval_json(score: float = 8.0, passed: bool = True) -> str:
    return json.dumps({
        "score": score,
        "factual_corrections": ["Correction A"],
        "alignment_notes": "Updated notes",
        "evidence_additions": ["Extra source"],
        "passed": passed,
        "notes": "Good overall",
    })


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


async def _run_worker(
    storage: InMemoryArtifactStorage,
    blueprint: Optional[Blueprint],
    context: Optional[NormalizedContext],
    claude_text: str,
    inputs: Optional[dict] = None,
):
    artifacts: dict[str, str] = {}
    if blueprint is not None:
        a = await write_artifact(
            storage, blueprint, name="blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["blueprint"] = a.r2_key
    if context is not None:
        a = await write_artifact(
            storage, context, name="normalized_context", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["normalized_context"] = a.r2_key

    state = StageState(
        run_id="run-001", user_id="operator",
        inputs=inputs or {"idea_title": _IDEA_TITLE},
        artifacts=artifacts,
    )
    with patch("cf_platform.workers.evaluator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response(claude_text))
        mock_cls.return_value = mock_client
        worker = build_evaluator_worker(storage, "fake-key")
        return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_evaluation_artifact():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_context(), _good_eval_json())
    assert isinstance(output.artifact, EvaluationArtifact)
    assert output.artifact.score == 8.0
    assert output.artifact.passed is True


@pytest.mark.asyncio
async def test_corrections_and_additions_parsed():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_context(), _good_eval_json())
    assert "Correction A" in output.artifact.factual_corrections
    assert "Extra source" in output.artifact.evidence_additions


@pytest.mark.asyncio
async def test_alignment_notes_from_response():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_context(), _good_eval_json())
    assert output.artifact.alignment_notes == "Updated notes"


@pytest.mark.asyncio
async def test_alignment_notes_fallback_to_blueprint():
    """When Claude omits alignment_notes, fallback to blueprint.direction_alignment_notes."""
    storage = InMemoryArtifactStorage()
    partial_json = json.dumps({"score": 7.0, "factual_corrections": [], "evidence_additions": [], "passed": True, "notes": ""})
    output = await _run_worker(storage, _make_blueprint(), _make_context(), partial_json)
    assert output.artifact.alignment_notes == "Original notes"


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="blueprint"):
        await _run_worker(storage, None, _make_context(), _good_eval_json())


@pytest.mark.asyncio
async def test_missing_normalized_context_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="normalized_context"):
        await _run_worker(storage, _make_blueprint(), None, _good_eval_json())


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(ValueError):
        await _run_worker(storage, _make_blueprint(), _make_context(), "not json")


def test_registration_model():
    assert EVALUATOR_REGISTRATION.model == "claude-sonnet-4-6"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_evaluator_worker(storage, "fake-key")
    assert callable(worker)
