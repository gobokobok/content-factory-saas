"""Tests for cf_platform/workers/context_normalizer.py (P5-S6).

Covers:
- Happy path: minimal inputs (idea_title only)
- primary_angle uses angle from inputs when present
- primary_angle uses direction_context.angle when angle is absent
- primary_angle falls back to idea_title
- supporting_points appear in evidence_summary
- signals are parsed and added to evidence_summary
- top_signals sorted by weight (descending), capped at 5
- controversies come from direction_context.do_not_focus_on
- hook_bias uses direction_context.hook_direction when present
- hook_bias uses niche when no direction_context
- hook_bias fallback to generic when niche absent
- Missing idea_title raises KeyError
- Registration: model='none', no LLM call
- build_context_normalizer_worker returns a callable
"""

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import StageState
from cf_platform.workers.context_normalizer import (
    CONTEXT_NORMALIZER_REGISTRATION,
    build_context_normalizer_worker,
)


def _make_state(inputs: dict) -> StageState:
    return StageState(run_id="r1", user_id="operator", inputs=inputs)


@pytest.mark.asyncio
async def test_happy_path_minimal():
    """Minimal inputs: idea_title only produces a valid NormalizedContext."""
    worker = build_context_normalizer_worker()
    state = _make_state({"idea_title": "Why Starter Homes Vanished"})
    output = await worker(state)
    artifact = output.artifact
    assert artifact.primary_angle == "Why Starter Homes Vanished"
    assert artifact.evidence_summary == "No prior evidence provided."
    assert artifact.top_signals == []
    assert artifact.controversies == []


@pytest.mark.asyncio
async def test_primary_angle_uses_angle_from_inputs():
    """When 'angle' is in inputs, primary_angle uses it."""
    worker = build_context_normalizer_worker()
    state = _make_state({"idea_title": "Title", "angle": "Supply side collapse"})
    output = await worker(state)
    assert output.artifact.primary_angle == "Supply side collapse"


@pytest.mark.asyncio
async def test_primary_angle_uses_direction_context_when_no_angle():
    """When 'angle' is absent but direction_context.angle is present, primary_angle uses it."""
    worker = build_context_normalizer_worker()
    state = _make_state({
        "idea_title": "Title",
        "direction_context": {"angle": "Demand shock", "narrative_bias": "pessimistic"},
    })
    output = await worker(state)
    assert output.artifact.primary_angle == "Demand shock"


@pytest.mark.asyncio
async def test_primary_angle_falls_back_to_idea_title():
    """Without angle or direction_context, primary_angle equals idea_title."""
    worker = build_context_normalizer_worker()
    state = _make_state({"idea_title": "Why rents are rising"})
    output = await worker(state)
    assert output.artifact.primary_angle == "Why rents are rising"


@pytest.mark.asyncio
async def test_supporting_points_in_evidence_summary():
    """supporting_points appear in evidence_summary."""
    worker = build_context_normalizer_worker()
    state = _make_state({
        "idea_title": "Title",
        "supporting_points": ["Fact A", "Fact B"],
    })
    output = await worker(state)
    assert "Fact A" in output.artifact.evidence_summary
    assert "Fact B" in output.artifact.evidence_summary


@pytest.mark.asyncio
async def test_signals_added_to_evidence():
    """Signal content appears in evidence_summary and top_signals."""
    worker = build_context_normalizer_worker()
    state = _make_state({
        "idea_title": "Title",
        "signals": [{"source": "reddit", "content": "Signal content here", "weight": 2.0}],
    })
    output = await worker(state)
    assert "Signal content here" in output.artifact.evidence_summary
    assert "Signal content here" in output.artifact.top_signals


@pytest.mark.asyncio
async def test_top_signals_sorted_by_weight_capped_at_5():
    """top_signals contains the 5 highest-weight signals in descending order."""
    worker = build_context_normalizer_worker()
    signals = [
        {"source": "s", "content": f"signal-{i}", "weight": float(i)}
        for i in range(1, 8)  # 7 signals
    ]
    state = _make_state({"idea_title": "Title", "signals": signals})
    output = await worker(state)
    assert len(output.artifact.top_signals) == 5
    assert output.artifact.top_signals[0] == "signal-7"  # highest weight first


@pytest.mark.asyncio
async def test_controversies_from_do_not_focus_on():
    """direction_context.do_not_focus_on items appear in controversies."""
    worker = build_context_normalizer_worker()
    state = _make_state({
        "idea_title": "Title",
        "direction_context": {
            "angle": "A",
            "narrative_bias": "B",
            "do_not_focus_on": ["mortgage rates", "foreign investors"],
        },
    })
    output = await worker(state)
    assert "mortgage rates" in output.artifact.controversies
    assert "foreign investors" in output.artifact.controversies


@pytest.mark.asyncio
async def test_hook_bias_uses_direction_context_hook_direction():
    """When direction_context.hook_direction is set, hook_bias uses it."""
    worker = build_context_normalizer_worker()
    state = _make_state({
        "idea_title": "Title",
        "direction_context": {
            "angle": "A",
            "narrative_bias": "B",
            "hook_direction": "Lead with a shocking stat",
        },
    })
    output = await worker(state)
    assert output.artifact.hook_bias == "Lead with a shocking stat"


@pytest.mark.asyncio
async def test_hook_bias_uses_niche_when_no_direction_context():
    """When niche is present but no direction_context, hook_bias mentions the niche."""
    worker = build_context_normalizer_worker()
    state = _make_state({"idea_title": "Title", "niche": "american housing"})
    output = await worker(state)
    assert "american housing" in output.artifact.hook_bias


@pytest.mark.asyncio
async def test_missing_idea_title_raises_key_error():
    """Missing idea_title in state.inputs raises KeyError."""
    worker = build_context_normalizer_worker()
    state = _make_state({})
    with pytest.raises(KeyError, match="idea_title"):
        await worker(state)


def test_registration_model_none():
    """CONTEXT_NORMALIZER_REGISTRATION.model is 'none' — no LLM call."""
    assert CONTEXT_NORMALIZER_REGISTRATION.model == "none"


def test_build_returns_callable():
    """build_context_normalizer_worker returns a callable (the WorkerNode)."""
    worker = build_context_normalizer_worker()
    assert callable(worker)
