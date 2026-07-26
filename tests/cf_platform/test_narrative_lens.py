"""Tests for cf_platform/workers/narrative_lens.py (P5-S7).

Covers:
- Happy path: reads merged_blueprint + evaluation, returns NarrativeLens with all fields
- All four angle fields are non-empty strings
- story_devices is a list
- Only verified claims passed to LLM (signals/context NOT in user message)
- Missing merged_blueprint artifact ref → KeyError
- Missing evaluation artifact ref → KeyError
- Invalid JSON from Claude → ValueError
- Registration: model='claude-haiku-4-5', worker_version='1.0.0'
- build_narrative_lens_worker returns a callable
- _build_user_message includes claims and corrections, excludes signals
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, EvaluationArtifact, NarrativeLens, Section
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.narrative_lens import (
    NARRATIVE_LENS_REGISTRATION,
    _build_user_message,
    build_narrative_lens_worker,
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

_LENS_RESPONSE = json.dumps({
    "identity_angle": "Europeans often treat clothing as ownership rather than consumption.",
    "contrarian_angle": "The cheapest option can become the most expensive over time.",
    "philosophical_angle": "Buying less often means buying better.",
    "emotional_angle": "There is quiet satisfaction in owning something that lasts.",
    "story_devices": ["cost-per-wear framing", "ownership vs. consumption contrast"],
})


def _make_blueprint(claims: list | None = None) -> Blueprint:
    return Blueprint(
        hook_angle="Durable workwear is rational economics",
        structure=[Section(title="S1", key_points=["kp1"])],
        claims=claims or ["Fast fashion garments typically last under 2 years", "Workwear can last 10 years"],
        monetization_angle="Monetize",
        required_evidence=["EU durability regulation data"],
        signal_summary="Summary",
        direction_alignment_notes="Focus on economics",
    )


def _make_evaluation(corrections: list | None = None) -> EvaluationArtifact:
    return EvaluationArtifact(
        score=8.5,
        factual_corrections=corrections or [],
        alignment_notes="",
        evidence_additions=[],
        passed=True,
        notes="",
    )


def _make_mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


async def _run_worker(
    storage: InMemoryArtifactStorage,
    blueprint: Blueprint | None,
    evaluation: EvaluationArtifact | None,
    claude_response_text: str = _LENS_RESPONSE,
):
    artifacts: dict = {}
    if blueprint is not None:
        a = await write_artifact(
            storage, blueprint, name="merged_blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["merged_blueprint"] = a.r2_key
    if evaluation is not None:
        a = await write_artifact(
            storage, evaluation, name="evaluation", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["evaluation"] = a.r2_key

    state = StageState(
        run_id="run-001",
        user_id="operator",
        inputs={"idea_title": "The €200 Workwear Piece"},
        artifacts=artifacts,
    )

    with patch("anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(claude_response_text))

        worker = build_narrative_lens_worker(storage, "fake-key")
        return await worker(state)


# ── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_narrative_lens():
    """Worker returns NarrativeLens on valid Claude response."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact, NarrativeLens)


@pytest.mark.asyncio
async def test_identity_angle_is_string():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact.identity_angle, str)
    assert len(output.artifact.identity_angle) > 0


@pytest.mark.asyncio
async def test_contrarian_angle_is_string():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact.contrarian_angle, str)
    assert len(output.artifact.contrarian_angle) > 0


@pytest.mark.asyncio
async def test_philosophical_angle_is_string():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact.philosophical_angle, str)


@pytest.mark.asyncio
async def test_emotional_angle_is_string():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact.emotional_angle, str)


@pytest.mark.asyncio
async def test_story_devices_is_list():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _make_evaluation())
    assert isinstance(output.artifact.story_devices, list)


# ── Input contract: only verified claims, no signals (D059) ──────────────


def test_user_message_contains_blueprint_claims():
    """User message includes verified blueprint claims (only source material)."""
    bp = _make_blueprint(claims=["Claim A", "Claim B"])
    ev = _make_evaluation()
    msg = _build_user_message(bp, ev)
    assert "Claim A" in msg
    assert "Claim B" in msg


def test_user_message_contains_corrections():
    """User message includes evaluation corrections."""
    bp = _make_blueprint()
    ev = _make_evaluation(corrections=["Correction C"])
    msg = _build_user_message(bp, ev)
    assert "Correction C" in msg


def test_user_message_contains_required_evidence():
    """User message includes blueprint required_evidence."""
    bp = _make_blueprint()
    ev = _make_evaluation()
    msg = _build_user_message(bp, ev)
    assert "EU durability regulation data" in msg


def test_user_message_does_not_contain_signal_summary():
    """User message must NOT include signal_summary — signals are not verified facts (D059)."""
    bp = _make_blueprint()
    ev = _make_evaluation()
    msg = _build_user_message(bp, ev)
    assert bp.signal_summary not in msg


def test_user_message_does_not_contain_hook_angle():
    """User message must NOT include hook_angle — that is structural, not a verified claim."""
    bp = _make_blueprint()
    ev = _make_evaluation()
    msg = _build_user_message(bp, ev)
    assert bp.hook_angle not in msg


def test_user_message_no_corrections_section_when_empty():
    """When corrections list is empty, corrections section is omitted."""
    bp = _make_blueprint()
    ev = _make_evaluation(corrections=[])
    msg = _build_user_message(bp, ev)
    assert "CORRECTIONS" not in msg


# ── Error cases ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError):
        await _run_worker(storage, None, _make_evaluation())


@pytest.mark.asyncio
async def test_missing_evaluation_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError):
        await _run_worker(storage, _make_blueprint(), None)


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    """ValueError raised when Claude returns non-JSON."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(ValueError):
        await _run_worker(storage, _make_blueprint(), _make_evaluation(), "not json at all")


# ── Registration ──────────────────────────────────────────────────────────


def test_registration_model():
    assert NARRATIVE_LENS_REGISTRATION.model == "claude-haiku-4-5"


def test_registration_worker_version():
    assert NARRATIVE_LENS_REGISTRATION.worker_version == "1.0.0"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_narrative_lens_worker(storage, "fake-key")
    assert callable(worker)
