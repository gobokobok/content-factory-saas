"""Tests for cf_platform/workers/hook_selector.py (P5-S6).

Covers:
- Happy path: 3 hooks + blueprint → SelectedHookArtifact with the chosen hook
- Single-hook fast path: skips LLM call entirely
- selected_hook is one of the candidates
- Graceful fallback to hooks[0] when Claude response is unparseable
- Missing hook_variants artifact ref → KeyError
- Missing merged_blueprint artifact ref → KeyError
- Registration: model='claude-haiku-4-5', worker_version='1.0.0'
- build_hook_selector_worker returns a callable
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    HookVariantsArtifact,
    Section,
    SelectedHookArtifact,
)
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.hook_selector import (
    HOOK_SELECTOR_REGISTRATION,
    build_hook_selector_worker,
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

_HOOKS = [
    "In 1980, you could afford a home in three years.",
    "The starter home is extinct — here is why.",
    "Builders stopped building small homes, and this is the price.",
]


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


def _make_hook_variants(hooks: Optional[list] = None) -> HookVariantsArtifact:
    return HookVariantsArtifact(hooks=hooks or _HOOKS, generated_at=_NOW)


def _make_mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


async def _run_worker(
    storage: InMemoryArtifactStorage,
    hook_variants: Optional[HookVariantsArtifact],
    blueprint: Optional[Blueprint],
    claude_response_text: str = json.dumps({"hook": _HOOKS[1]}),
):
    artifacts: dict = {}
    if hook_variants is not None:
        a = await write_artifact(
            storage, hook_variants, name="hook_variants", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["hook_variants"] = a.r2_key
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

        worker = build_hook_selector_worker(storage, "fake-key")
        return await worker(state)


# ── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_selected_hook():
    """Worker returns SelectedHookArtifact on valid Claude response."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_hook_variants(), _make_blueprint())
    assert isinstance(output.artifact, SelectedHookArtifact)


@pytest.mark.asyncio
async def test_selected_hook_matches_llm_choice():
    """Selected hook matches the 'hook' key from the Claude response."""
    storage = InMemoryArtifactStorage()
    response_text = json.dumps({"hook": _HOOKS[1]})
    output = await _run_worker(storage, _make_hook_variants(), _make_blueprint(), response_text)
    assert output.artifact.hook == _HOOKS[1]


@pytest.mark.asyncio
async def test_selected_hook_is_a_string():
    storage = InMemoryArtifactStorage()
    output = await _run_worker(storage, _make_hook_variants(), _make_blueprint())
    assert isinstance(output.artifact.hook, str)
    assert len(output.artifact.hook) > 0


# ── Single-hook fast path ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_hook_skips_llm():
    """When only one hook is present, no LLM call is made and that hook is selected."""
    storage = InMemoryArtifactStorage()
    single = _make_hook_variants(hooks=[_HOOKS[0]])

    with patch("anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        a = await write_artifact(
            storage, single, name="hook_variants", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        b = await write_artifact(
            storage, _make_blueprint(), name="merged_blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        state = StageState(
            run_id="run-001", user_id="operator",
            inputs={}, artifacts={"hook_variants": a.r2_key, "merged_blueprint": b.r2_key},
        )
        worker = build_hook_selector_worker(storage, "fake-key")
        output = await worker(state)

    mock_client.messages.create.assert_not_called()
    assert output.artifact.hook == _HOOKS[0]


# ── Fallback on unparseable response ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unparseable_response_falls_back_to_first_hook():
    """Graceful fallback to hooks[0] when Claude returns non-JSON."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(
        storage, _make_hook_variants(), _make_blueprint(),
        claude_response_text="not json at all",
    )
    assert output.artifact.hook == _HOOKS[0]


@pytest.mark.asyncio
async def test_missing_hook_key_falls_back_to_first_hook():
    """Graceful fallback to hooks[0] when Claude JSON has no 'hook' key."""
    storage = InMemoryArtifactStorage()
    output = await _run_worker(
        storage, _make_hook_variants(), _make_blueprint(),
        claude_response_text=json.dumps({"other_key": "value"}),
    )
    assert output.artifact.hook == _HOOKS[0]


# ── Error cases ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_hook_variants_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError):
        await _run_worker(storage, None, _make_blueprint())


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError):
        await _run_worker(storage, _make_hook_variants(), None)


# ── Registration ──────────────────────────────────────────────────────────


def test_registration_model():
    assert HOOK_SELECTOR_REGISTRATION.model == "claude-haiku-4-5"


def test_registration_worker_version():
    assert HOOK_SELECTOR_REGISTRATION.worker_version == "1.0.0"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_hook_selector_worker(storage, "fake-key")
    assert callable(worker)
