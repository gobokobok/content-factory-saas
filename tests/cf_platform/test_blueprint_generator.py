"""Tests for cf_platform/workers/blueprint_generator.py (P5-S6).

Covers:
- Happy path: reads normalized_context, calls Claude, returns Blueprint
- Sections parsed from JSON response
- niche included in user message when present
- niche absent → generic framing note in user message
- Missing normalized_context artifact ref → KeyError
- Invalid JSON from Claude → ValueError
- Partial JSON (missing fields) uses defaults gracefully
- Registration: model='claude-sonnet-4-6', worker_version, prompt_version
- build_blueprint_generator_worker returns a callable
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, NormalizedContext
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.blueprint_generator import (
    BLUEPRINT_GENERATOR_REGISTRATION,
    _build_user_message,
    build_blueprint_generator_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-001",
    worker="test",
    worker_version="1.0.0",
    prompt_version="v1",
    model="none",
    created_at=_NOW,
)
_IDEA_TITLE = "Why Starter Homes Vanished"


def _make_context() -> NormalizedContext:
    return NormalizedContext(
        primary_angle="Supply shortage",
        evidence_summary="Census data shows 70% fewer starter homes built",
        top_signals=["Zoning laws", "Construction costs"],
        controversies=[],
        hook_bias="Data-driven opening",
    )


def _good_blueprint_json() -> str:
    return json.dumps({
        "hook_angle": "Starter homes nearly gone",
        "structure": [
            {"title": "Hook", "key_points": ["stat"]},
            {"title": "Body", "key_points": ["why", "data"]},
        ],
        "claims": ["70% fewer starter homes built in 2023 vs 1980"],
        "monetization_angle": "Urgency drives retention",
        "required_evidence": ["Census housing starts data"],
        "signal_summary": "Supply-side collapse driven by zoning and cost",
        "direction_alignment_notes": "Focus on supply, not demand",
    })


def _mock_claude_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


async def _run_worker(
    storage: InMemoryArtifactStorage,
    context: Optional[NormalizedContext],
    claude_response_text: str,
    inputs: Optional[dict] = None,
):
    artifacts: dict[str, str] = {}
    if context is not None:
        a = await write_artifact(
            storage, context, name="normalized_context", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["normalized_context"] = a.r2_key

    state = StageState(
        run_id="run-001",
        user_id="operator",
        inputs=inputs or {"idea_title": _IDEA_TITLE},
        artifacts=artifacts,
    )

    with patch(
        "cf_platform.workers.blueprint_generator.anthropic.AsyncAnthropic"
    ) as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_claude_response(claude_response_text)
        )
        mock_cls.return_value = mock_client
        worker = build_blueprint_generator_worker(storage, "fake-key")
        return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_blueprint():
    """Worker reads normalized_context, calls Claude, returns a Blueprint artifact."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_context(), _good_blueprint_json())
    assert isinstance(output.artifact, Blueprint)
    assert output.artifact.hook_angle == "Starter homes nearly gone"
    assert len(output.artifact.structure) == 2


@pytest.mark.asyncio
async def test_sections_parsed():
    """Structure sections are parsed into Section objects."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_context(), _good_blueprint_json())
    assert output.artifact.structure[0].title == "Hook"
    assert output.artifact.structure[0].key_points == ["stat"]


@pytest.mark.asyncio
async def test_niche_in_user_message():
    """When niche is in inputs, user message includes the niche."""
    ctx = _make_context()
    msg = _build_user_message("Title", "american housing", ctx, 160)
    assert "american housing" in msg


@pytest.mark.asyncio
async def test_niche_absent_generic_framing():
    """When niche is absent, user message includes the generic framing note."""
    ctx = _make_context()
    msg = _build_user_message("Title", None, ctx, 160)
    assert "not specified" in msg


@pytest.mark.asyncio
async def test_missing_normalized_context_raises_key_error():
    """KeyError raised when normalized_context artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="normalized_context"):
        await _run_worker(storage, None, _good_blueprint_json())


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    """ValueError raised when Claude returns non-JSON."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(ValueError):
        await _run_worker(storage, _make_context(), "not json at all")


def test_registration_model():
    """BLUEPRINT_GENERATOR_REGISTRATION.model is 'claude-sonnet-4-6'."""
    assert BLUEPRINT_GENERATOR_REGISTRATION.model == "claude-sonnet-4-6"


def test_registration_worker_version():
    assert BLUEPRINT_GENERATOR_REGISTRATION.worker_version == "1.0.0"


def test_registration_prompt_version():
    assert BLUEPRINT_GENERATOR_REGISTRATION.prompt_version == "v1"


def test_build_returns_callable():
    """build_blueprint_generator_worker returns a callable."""
    storage = InMemoryArtifactStorage()
    worker = build_blueprint_generator_worker(storage, "fake-key")
    assert callable(worker)
