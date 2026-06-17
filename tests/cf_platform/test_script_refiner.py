"""Tests for the Script Refiner worker (P5-S4).

Covers:
- Happy path: reads drafts + scores + factcheck report, calls Claude, returns ScriptDraftsArtifact
- Best draft selection: picks the draft matching best_draft_number; falls back to drafts[0]
- Score formatting: all five axes present in user message sent to Claude
- Claims formatting: supported/refuted/unverifiable all appear in user message
- Empty claims: "(no factual claims identified)" in user message
- Invalid JSON response raises ValueError
- Missing script_drafts key raises KeyError
- Missing script_scores key raises KeyError
- Missing factcheck_report key raises KeyError
- Registration pins: model, prompt_version, worker_version, prompt non-empty
- Control signal is always "continue"
- Idea title and niche preserved from original drafts artifact
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import StageState
from cf_platform.workers.fact_checker import ClaimVerification, FactcheckReportArtifact
from cf_platform.workers.script_quality_scorer import ScriptDraftScore, ScriptScoresArtifact
from cf_platform.workers.script_refiner import (
    SCRIPT_REFINER_REGISTRATION,
    build_script_refiner_worker,
)
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)

_IDEA_TITLE = "Why Starter Homes Vanished"


# ── Fixtures & helpers ─────────────────────────────────────────────────


def _make_drafts_artifact(n_drafts: int = 3) -> ScriptDraftsArtifact:
    return ScriptDraftsArtifact(
        niche="housing",
        idea_title=_IDEA_TITLE,
        idea_angle="economic squeeze",
        drafts=[
            ScriptDraft(draft_number=i + 1, script=f"Draft {i + 1} script text.")
            for i in range(n_drafts)
        ],
        generated_at=_NOW,
    )


def _make_scores_artifact(best_draft_number: int = 2, overall_score: float = 7.0) -> ScriptScoresArtifact:
    scored = [
        ScriptDraftScore(
            draft_number=i + 1,
            hook_strength=6.0,
            data_quality=7.0,
            narrative_flow=6.5,
            virality_potential=7.5,
            overall_score=overall_score if i + 1 == best_draft_number else 5.0,
        )
        for i in range(3)
    ]
    return ScriptScoresArtifact(
        idea_title=_IDEA_TITLE,
        scored_drafts=scored,
        best_draft_number=best_draft_number,
        best_score=overall_score,
        generated_at=_NOW,
    )


def _make_factcheck_artifact(
    include_refuted: bool = True, include_unverifiable: bool = True
) -> FactcheckReportArtifact:
    claims = [
        ClaimVerification(
            claim="Starter homes are 3x more expensive than in 1980",
            verdict="refuted" if include_refuted else "supported",
            source="https://example.com",
            note="Actual increase is closer to 2x when adjusted.",
        ),
        ClaimVerification(
            claim="HUD defines affordability at 30% income",
            verdict="supported",
            source="https://hud.gov",
            note="Confirmed by HUD guidelines.",
        ),
    ]
    if include_unverifiable:
        claims.append(
            ClaimVerification(
                claim="Builders avoid small homes due to labor costs",
                verdict="unverifiable",
                source="",
                note="No authoritative source found.",
            )
        )
    return FactcheckReportArtifact(
        idea_title=_IDEA_TITLE,
        draft_number=1,
        claims=claims,
        verified_count=1,
        refuted_count=1 if include_refuted else 0,
        unverifiable_count=1 if include_unverifiable else 0,
        checked_at=_NOW,
    )


async def _write_artifact_to_storage(
    storage: InMemoryArtifactStorage, artifact_body, key_name: str, run_id: str
) -> str:
    """Write a Pydantic artifact body to storage and return its r2_key."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    lineage = LineageEnvelope(
        run_id=run_id,
        worker="test",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=_NOW,
    )
    artifact = await write_artifact(
        storage,
        artifact_body,
        name=key_name,
        stage=key_name,
        run_id=run_id,
        user_id="operator",
        lineage=lineage,
    )
    return artifact.r2_key


def _make_state(artifacts: dict, run_id: str = "run-001") -> StageState:
    return StageState(
        run_id=run_id,
        user_id="operator",
        inputs={"idea_title": _IDEA_TITLE},
        artifacts=artifacts,
    )


def _mock_claude_response(refined_script: str = "Refined draft text.") -> MagicMock:
    """Build a mock anthropic response with one draft JSON in the text block."""
    text_block = MagicMock()
    text_block.text = json.dumps([{"draft_number": 1, "script": refined_script}])
    response = MagicMock()
    response.content = [text_block]
    return response


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_script_drafts_artifact():
    storage = InMemoryArtifactStorage()
    run_id = "run-001"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key}
    )

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response("Improved script."))

        worker = build_script_refiner_worker(storage, "fake-key")
        output = await worker(state)

    assert isinstance(output.artifact, ScriptDraftsArtifact)
    assert len(output.artifact.drafts) == 1
    assert output.artifact.drafts[0].script == "Improved script."


@pytest.mark.asyncio
async def test_control_signal_is_always_continue():
    storage = InMemoryArtifactStorage()
    run_id = "run-002"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())

        worker = build_script_refiner_worker(storage, "fake-key")
        output = await worker(state)

    assert output.control == "continue"


@pytest.mark.asyncio
async def test_selects_best_draft_by_best_draft_number():
    storage = InMemoryArtifactStorage()
    run_id = "run-003"
    # best_draft_number=2 means Draft 2 script should appear in the user message
    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(3), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(
        storage, _make_scores_artifact(best_draft_number=2), "script_scores", run_id
    )
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    captured_messages: list = []

    async def _capture(*args, **kwargs):
        captured_messages.append(kwargs.get("messages", []))
        return _mock_claude_response()

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = _capture

        worker = build_script_refiner_worker(storage, "fake-key")
        await worker(state)

    user_content = captured_messages[0][0]["content"]
    assert "Draft 2 script text." in user_content


@pytest.mark.asyncio
async def test_scores_axes_present_in_user_message():
    storage = InMemoryArtifactStorage()
    run_id = "run-004"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    captured: list = []

    async def _capture(*args, **kwargs):
        captured.append(kwargs.get("messages", []))
        return _mock_claude_response()

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = _capture

        worker = build_script_refiner_worker(storage, "fake-key")
        await worker(state)

    user_content = captured[0][0]["content"]
    for axis in ("hook_strength", "data_quality", "narrative_flow", "virality_potential", "overall_score"):
        assert axis in user_content


@pytest.mark.asyncio
async def test_refuted_claim_present_in_user_message():
    storage = InMemoryArtifactStorage()
    run_id = "run-005"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(include_refuted=True), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    captured: list = []

    async def _capture(*args, **kwargs):
        captured.append(kwargs.get("messages", []))
        return _mock_claude_response()

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = _capture

        worker = build_script_refiner_worker(storage, "fake-key")
        await worker(state)

    user_content = captured[0][0]["content"]
    assert "REFUTED" in user_content


@pytest.mark.asyncio
async def test_empty_claims_shows_placeholder():
    storage = InMemoryArtifactStorage()
    run_id = "run-006"

    empty_report = FactcheckReportArtifact(
        idea_title=_IDEA_TITLE,
        draft_number=1,
        claims=[],
        verified_count=0,
        refuted_count=0,
        unverifiable_count=0,
        checked_at=_NOW,
    )

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(storage, empty_report, "factcheck_report", run_id)

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    captured: list = []

    async def _capture(*args, **kwargs):
        captured.append(kwargs.get("messages", []))
        return _mock_claude_response()

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = _capture

        worker = build_script_refiner_worker(storage, "fake-key")
        await worker(state)

    assert "(no factual claims identified)" in captured[0][0]["content"]


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    storage = InMemoryArtifactStorage()
    run_id = "run-007"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="not valid json {{{")]

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=bad_response)

        worker = build_script_refiner_worker(storage, "fake-key")
        with pytest.raises(ValueError, match="invalid JSON"):
            await worker(state)


@pytest.mark.asyncio
async def test_missing_script_drafts_raises_key_error():
    storage = InMemoryArtifactStorage()
    run_id = "run-008"

    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state({"script_scores": scores_key, "factcheck_report": factcheck_key}, run_id=run_id)
    worker = build_script_refiner_worker(storage, "fake-key")

    with pytest.raises(KeyError, match="script_drafts"):
        await worker(state)


@pytest.mark.asyncio
async def test_missing_script_scores_raises_key_error():
    storage = InMemoryArtifactStorage()
    run_id = "run-009"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state({"script_drafts": drafts_key, "factcheck_report": factcheck_key}, run_id=run_id)
    worker = build_script_refiner_worker(storage, "fake-key")

    with pytest.raises(KeyError, match="script_scores"):
        await worker(state)


@pytest.mark.asyncio
async def test_missing_factcheck_report_raises_key_error():
    storage = InMemoryArtifactStorage()
    run_id = "run-010"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)

    state = _make_state({"script_drafts": drafts_key, "script_scores": scores_key}, run_id=run_id)
    worker = build_script_refiner_worker(storage, "fake-key")

    with pytest.raises(KeyError, match="factcheck_report"):
        await worker(state)


def test_registration_pins_model():
    assert SCRIPT_REFINER_REGISTRATION.model == "claude-sonnet-4-6"


def test_registration_pins_prompt_version():
    assert SCRIPT_REFINER_REGISTRATION.prompt_version == "v1"


def test_registration_pins_worker_version():
    assert SCRIPT_REFINER_REGISTRATION.worker_version == "1.0.0"


def test_registration_prompt_is_non_empty():
    assert len(SCRIPT_REFINER_REGISTRATION.prompt) > 0


@pytest.mark.asyncio
async def test_idea_title_and_niche_preserved():
    storage = InMemoryArtifactStorage()
    run_id = "run-011"

    drafts_key = await _write_artifact_to_storage(storage, _make_drafts_artifact(), "script_drafts", run_id)
    scores_key = await _write_artifact_to_storage(storage, _make_scores_artifact(), "script_scores", run_id)
    factcheck_key = await _write_artifact_to_storage(
        storage, _make_factcheck_artifact(), "factcheck_report", run_id
    )

    state = _make_state(
        {"script_drafts": drafts_key, "script_scores": scores_key, "factcheck_report": factcheck_key},
        run_id=run_id,
    )

    with patch("cf_platform.workers.script_refiner.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response())

        worker = build_script_refiner_worker(storage, "fake-key")
        output = await worker(state)

    assert isinstance(output.artifact, ScriptDraftsArtifact)
    assert output.artifact.idea_title == _IDEA_TITLE
    assert output.artifact.niche == "housing"
