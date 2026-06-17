"""Tests for the Script Quality Scorer worker (P5-S2).

Covers:
- Happy path: script_drafts artifact → ScriptScoresArtifact with per-draft scores
- idea_title propagated from ScriptDraftsArtifact
- All four scoring axes present in each ScriptDraftScore
- best_draft_number and best_score reflect highest overall_score
- Control "continue" when best_score / 10.0 >= quality_threshold (default 0.8)
- Control "retry" when best_score / 10.0 < quality_threshold
- quality_threshold read from state attribute when present
- Draft scripts and idea_title sent in user message to Claude
- Missing script_drafts artifact → KeyError
- Invalid JSON from Claude → ValueError
- Registration pins model, prompt_version, worker_version, prompt content
"""

import json
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact
from cf_platform.workers.script_quality_scorer import (
    SCRIPT_QUALITY_SCORER_REGISTRATION,
    ScriptDraftScore,
    ScriptScoresArtifact,
    build_script_quality_scorer_worker,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="script_writer",
        worker_version="1.1.0",
        prompt_version="v2",
        model="claude-haiku-4-5",
        created_at=datetime.now(timezone.utc),
    )


def _scores_json(
    n: int = 3,
    overall_scores: Optional[List[float]] = None,
) -> str:
    """Build a mock JSON response for n drafts. overall_scores overrides per-draft."""
    if overall_scores is None:
        overall_scores = [6.0 + i * 0.5 for i in range(n)]
    return json.dumps([
        {
            "draft_number": i + 1,
            "hook_strength": 7.0,
            "data_quality": 7.5,
            "narrative_flow": 6.5,
            "virality_potential": 8.0,
            "overall_score": overall_scores[i],
        }
        for i in range(n)
    ])


async def _seed_script_drafts(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    idea_title: str = "Why Starter Homes Disappeared",
    n_drafts: int = 3,
) -> str:
    body = ScriptDraftsArtifact(
        niche="starter homes",
        idea_title=idea_title,
        idea_angle="Supply gap narrative",
        drafts=[
            ScriptDraft(
                draft_number=i + 1,
                script=f"Draft {i + 1}: In 1980 a home cost three years of savings...",
            )
            for i in range(n_drafts)
        ],
        generated_at=datetime.now(timezone.utc),
    )
    artifact = await write_artifact(
        storage,
        body,
        name="script_drafts",
        stage="idea_to_script",
        run_id=run_id,
        user_id=user_id,
        lineage=_lineage(run_id),
    )
    return artifact.r2_key


def _mock_anthropic_client(response_text: str) -> MagicMock:
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


# ── happy path ────────────────────────────────────────────────────────────


class TestScriptQualityScorerHappyPath:
    """Worker reads script_drafts, scores drafts, emits ScriptScoresArtifact."""

    @pytest.mark.asyncio
    async def test_returns_script_scores_artifact(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=3)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(3))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, ScriptScoresArtifact)
        assert len(output.artifact.scored_drafts) == 3

    @pytest.mark.asyncio
    async def test_idea_title_propagated_to_artifact(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, idea_title="The Mortgage Rate Trap")
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(3))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.idea_title == "The Mortgage Rate Trap"

    @pytest.mark.asyncio
    async def test_all_four_axes_present_in_each_scored_draft(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=2)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(2))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        for scored in output.artifact.scored_drafts:
            assert isinstance(scored, ScriptDraftScore)
            assert hasattr(scored, "hook_strength")
            assert hasattr(scored, "data_quality")
            assert hasattr(scored, "narrative_flow")
            assert hasattr(scored, "virality_potential")
            assert hasattr(scored, "overall_score")

    @pytest.mark.asyncio
    async def test_best_draft_number_reflects_highest_overall_score(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=3)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        # Draft 2 has the highest score
        mock_client = _mock_anthropic_client(_scores_json(3, overall_scores=[6.0, 9.5, 7.0]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.best_draft_number == 2
        assert output.artifact.best_score == 9.5

    @pytest.mark.asyncio
    async def test_idea_title_and_draft_scripts_sent_to_claude(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(
            storage, idea_title="Why Starter Homes Disappeared"
        )
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(3))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "Why Starter Homes Disappeared" in user_content
        assert "Draft 1" in user_content


# ── control signal ────────────────────────────────────────────────────────


class TestScriptQualityScorerControlSignal:
    """Control signal derived from best_score vs quality_threshold."""

    @pytest.mark.asyncio
    async def test_control_continue_when_best_score_meets_threshold(self):
        """Score 8.0/10 = 0.80 >= default threshold 0.80 → continue."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=1)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(1, overall_scores=[8.0]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_control_retry_when_best_score_below_threshold(self):
        """Score 7.9/10 = 0.79 < default threshold 0.80 → retry."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=1)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(1, overall_scores=[7.9]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "retry"

    @pytest.mark.asyncio
    async def test_control_uses_best_score_across_multiple_drafts(self):
        """Threshold comparison uses the highest overall_score, not the first draft."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=3)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        # Draft 3 hits 9.0 → continue; drafts 1 and 2 would retry
        mock_client = _mock_anthropic_client(_scores_json(3, overall_scores=[5.0, 6.0, 9.0]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_quality_threshold_read_from_state_attribute(self):
        """When state has a quality_threshold attribute it overrides the default 0.8."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=1)

        class FakeState(StageState):
            quality_threshold: float = 0.95

        state = FakeState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        # 9.0/10 = 0.90 < 0.95 → retry
        mock_client = _mock_anthropic_client(_scores_json(1, overall_scores=[9.0]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "retry"

    @pytest.mark.asyncio
    async def test_control_continue_when_score_exactly_equals_threshold(self):
        """Exactly at threshold (0.8 == 0.8) should be "continue" (>=)."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=1)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client(_scores_json(1, overall_scores=[8.0]))

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "continue"


# ── error handling ────────────────────────────────────────────────────────


class TestScriptQualityScorerErrors:

    @pytest.mark.asyncio
    async def test_missing_script_drafts_artifact_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={},
        )
        worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
        with pytest.raises(KeyError, match="script_drafts"):
            await worker(state)

    @pytest.mark.asyncio
    async def test_invalid_json_from_claude_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"script_drafts": drafts_key},
        )
        mock_client = _mock_anthropic_client("Here are the scores for your drafts!")

        with patch(
            "cf_platform.workers.script_quality_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_script_quality_scorer_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="invalid JSON"):
                await worker(state)


# ── registration ──────────────────────────────────────────────────────────


class TestScriptQualityScorerRegistration:
    """SCRIPT_QUALITY_SCORER_REGISTRATION pins model, prompt_version, worker_version."""

    def test_model_is_sonnet(self):
        assert SCRIPT_QUALITY_SCORER_REGISTRATION.model == "claude-sonnet-4-6"

    def test_prompt_version_is_v1(self):
        assert SCRIPT_QUALITY_SCORER_REGISTRATION.prompt_version == "v1"

    def test_worker_version_is_set(self):
        assert SCRIPT_QUALITY_SCORER_REGISTRATION.worker_version == "1.0.0"

    def test_prompt_is_non_empty(self):
        assert len(SCRIPT_QUALITY_SCORER_REGISTRATION.prompt) > 50

    def test_prompt_contains_all_four_axes(self):
        prompt = SCRIPT_QUALITY_SCORER_REGISTRATION.prompt
        assert "hook_strength" in prompt
        assert "data_quality" in prompt
        assert "narrative_flow" in prompt
        assert "virality_potential" in prompt
        assert "overall_score" in prompt
