"""Tests for cf_platform/workers/hook_generator.py (P5-S6).

Covers:
- Happy path: reads merged_blueprint, calls Claude Haiku, returns HookVariantsArtifact with 3 hooks
- hooks list has the correct length
- user_message includes hook_angle and signal_summary
- Missing merged_blueprint artifact ref → KeyError
- Invalid JSON from Claude → ValueError
- Registration: model='claude-haiku-4-5', worker_version='1.0.0'
- build_hook_generator_worker returns a callable
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, HookVariantsArtifact, Section
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.hook_generator import (
    HOOK_GENERATOR_REGISTRATION,
    _build_user_message,
    build_hook_generator_worker,
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

_HOOKS_RESPONSE = json.dumps([
    "In 1980, you could afford a home in three years of savings.",
    "The starter home is extinct — here is why.",
    "Builders stopped building small homes, and this is the price.",
])


def _make_blueprint() -> Blueprint:
    return Blueprint(
        hook_angle="Supply shortage destroyed starter homes",
        structure=[Section(title="S1", key_points=["kp1"])],
        claims=["Claim 1"],
        monetization_angle="Monetize",
        required_evidence=["Evidence 1"],
        signal_summary="Key signals about housing supply",
        direction_alignment_notes="Focus on supply side",
    )


def _make_mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


async def _run_worker(
    storage: InMemoryArtifactStorage,
    blueprint: Blueprint | None,
    claude_response_text: str,
):
    artifacts: dict = {}
    if blueprint is not None:
        a = await write_artifact(
            storage, blueprint, name="merged_blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["merged_blueprint"] = a.r2_key

    state = StageState(
        run_id="run-001",
        user_id="operator",
        inputs={"idea_title": "Why Starter Homes Vanished"},
        artifacts=artifacts,
    )

    with patch("anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(claude_response_text))

        worker = build_hook_generator_worker(storage, "fake-key")
        return await worker(state)


# ── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_hook_variants():
    """Worker returns HookVariantsArtifact on valid Claude response."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _HOOKS_RESPONSE)
    assert isinstance(output.artifact, HookVariantsArtifact)


@pytest.mark.asyncio
async def test_hooks_list_has_three_items():
    """HookVariantsArtifact.hooks has 3 entries from the Claude response."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _HOOKS_RESPONSE)
    assert len(output.artifact.hooks) == 3


@pytest.mark.asyncio
async def test_hooks_are_strings():
    """All hook items are strings."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_blueprint(), _HOOKS_RESPONSE)
    for h in output.artifact.hooks:
        assert isinstance(h, str)


# ── User message ──────────────────────────────────────────────────────────


def test_build_user_message_includes_hook_angle():
    bp = _make_blueprint()
    msg = _build_user_message(bp)
    assert "Supply shortage destroyed starter homes" in msg


def test_build_user_message_includes_signal_summary():
    bp = _make_blueprint()
    msg = _build_user_message(bp)
    assert "Key signals about housing supply" in msg


# ── Error cases ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    """KeyError raised when merged_blueprint artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError):
        await _run_worker(storage, None, _HOOKS_RESPONSE)


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    """ValueError raised when Claude returns non-JSON."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(ValueError):
        await _run_worker(storage, _make_blueprint(), "not json at all")


# ── Registration ──────────────────────────────────────────────────────────


def test_registration_model():
    assert HOOK_GENERATOR_REGISTRATION.model == "claude-haiku-4-5"


def test_registration_worker_version():
    assert HOOK_GENERATOR_REGISTRATION.worker_version == "1.0.0"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_hook_generator_worker(storage, "fake-key")
    assert callable(worker)
