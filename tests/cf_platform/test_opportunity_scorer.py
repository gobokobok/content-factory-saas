"""Tests for the opportunity scorer worker (P4-S2).

Covers:
- Happy path: candidate_topics artifact in storage → scored_topics returned
- Adaptive thinking: response with ThinkingBlock + TextBlock → TextBlock extracted
- Invalid JSON from Claude → ValueError raised
- No text block in response → ValueError raised
- Missing candidate_topics key in state → KeyError raised
- Niche and topic titles passed to Claude
- Registration pins model, prompt version, worker version, and prompt content
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.opportunity_scorer import (
    OPPORTUNITY_SCORER_REGISTRATION,
    ScoredTopicsArtifact,
    build_opportunity_scorer_worker,
)
from cf_platform.workers.topic_generator import CandidateTopic, CandidateTopicsArtifact


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="topic_generator",
        worker_version="1.0.0",
        prompt_version="v1",
        model="claude-sonnet-4-6",
        created_at=datetime.now(timezone.utc),
    )


async def _seed_candidate_topics(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    topics: Optional[list[CandidateTopic]] = None,
) -> str:
    """Write a CandidateTopicsArtifact to storage and return its r2_key."""
    if topics is None:
        topics = [
            CandidateTopic(
                title="Why Starter Homes Disappeared",
                angle="Show how 1980s builder incentives shifted from entry-level to luxury.",
            ),
            CandidateTopic(
                title="The 2024 Housing Squeeze",
                angle="Compare affordability across 10 cities using real income-to-price ratios.",
            ),
        ]
    body = CandidateTopicsArtifact(
        niche="starter homes",
        generated_at=datetime.now(timezone.utc),
        topics=topics,
    )
    artifact = await write_artifact(
        storage,
        body,
        name="candidate_topics",
        stage="niche_to_ideas",
        run_id=run_id,
        user_id=user_id,
        lineage=_lineage(run_id),
    )
    return artifact.r2_key


def _text_block(text: str) -> MagicMock:
    """Build a mock TextBlock (type='text')."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _thinking_block() -> MagicMock:
    """Build a mock ThinkingBlock (type='thinking')."""
    block = MagicMock()
    block.type = "thinking"
    block.thinking = "Let me reason through the scores for each topic carefully..."
    return block


def _mock_anthropic_client(content_blocks: list[MagicMock]) -> MagicMock:
    """Build a mock AsyncAnthropic client returning the given content blocks."""
    mock_message = MagicMock()
    mock_message.content = content_blocks
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


def _scored_topics_json(topics: Optional[list[dict]] = None) -> str:
    if topics is None:
        topics = [
            {
                "title": "Why Starter Homes Disappeared",
                "angle": "Show how 1980s builder incentives shifted from entry-level to luxury.",
                "novelty": 8.5,
                "audience_relevance": 9.0,
                "emotional_trigger": 7.5,
                "search_demand": 8.0,
                "competition": 5.0,
                "evergreen_potential": 7.0,
                "monetization_relevance": 6.0,
                "final_score": 7.8,
            },
            {
                "title": "The 2024 Housing Squeeze",
                "angle": "Compare affordability across 10 cities using real income-to-price ratios.",
                "novelty": 7.0,
                "audience_relevance": 8.5,
                "emotional_trigger": 8.0,
                "search_demand": 7.5,
                "competition": 4.5,
                "evergreen_potential": 6.0,
                "monetization_relevance": 7.0,
                "final_score": 7.2,
            },
        ]
    return json.dumps(topics)


class TestOpportunityScorerWorker:
    """build_opportunity_scorer_worker produces ScoredTopicsArtifact from candidate topics."""

    @pytest.mark.asyncio
    async def test_scores_candidate_topics_happy_path(self):
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        mock_client = _mock_anthropic_client([_text_block(_scored_topics_json())])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, ScoredTopicsArtifact)
        assert output.artifact.niche == "starter homes"
        assert len(output.artifact.scored_topics) == 2
        assert output.artifact.scored_topics[0].title == "Why Starter Homes Disappeared"
        assert output.artifact.scored_topics[0].novelty == 8.5
        assert output.artifact.scored_topics[0].final_score == 7.8
        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_extracts_text_block_when_thinking_block_present(self):
        """Adaptive thinking may prepend a ThinkingBlock; text block must be found."""
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        # Simulate adaptive thinking response: ThinkingBlock then TextBlock
        mock_client = _mock_anthropic_client([
            _thinking_block(),
            _text_block(_scored_topics_json()),
        ])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, ScoredTopicsArtifact)
        assert len(output.artifact.scored_topics) == 2

    @pytest.mark.asyncio
    async def test_passes_niche_and_topic_titles_to_claude(self):
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        mock_client = _mock_anthropic_client([_text_block(_scored_topics_json())])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "starter homes" in user_content
        assert "Why Starter Homes Disappeared" in user_content
        assert "The 2024 Housing Squeeze" in user_content

    @pytest.mark.asyncio
    async def test_passes_thinking_param_to_claude(self):
        """Worker must pass thinking={type: adaptive} to the API call."""
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        mock_client = _mock_anthropic_client([_text_block(_scored_topics_json())])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs.get("thinking") == {"type": "adaptive"}

    @pytest.mark.asyncio
    async def test_invalid_json_from_claude_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        mock_client = _mock_anthropic_client([_text_block("Sorry, I cannot help with that.")])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="invalid JSON"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_no_text_block_in_response_raises_value_error(self):
        """If Claude returns only ThinkingBlock(s) and no TextBlock, raise ValueError."""
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        mock_client = _mock_anthropic_client([_thinking_block()])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="no text block"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_missing_candidate_topics_key_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={},
        )
        worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")

        with pytest.raises(KeyError, match="candidate_topics"):
            await worker(state)

    @pytest.mark.asyncio
    async def test_all_seven_axes_present_in_output(self):
        storage = InMemoryArtifactStorage()
        topics_key = await _seed_candidate_topics(
            storage,
            topics=[CandidateTopic(title="Single Topic", angle="One angle.")],
        )
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"candidate_topics": topics_key},
        )
        single_score = _scored_topics_json([{
            "title": "Single Topic",
            "angle": "One angle.",
            "novelty": 7.0,
            "audience_relevance": 8.0,
            "emotional_trigger": 6.5,
            "search_demand": 7.5,
            "competition": 6.0,
            "evergreen_potential": 8.0,
            "monetization_relevance": 5.0,
            "final_score": 7.1,
        }])
        mock_client = _mock_anthropic_client([_text_block(single_score)])

        with patch(
            "cf_platform.workers.opportunity_scorer.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_opportunity_scorer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        score = output.artifact.scored_topics[0]
        assert score.novelty == 7.0
        assert score.audience_relevance == 8.0
        assert score.emotional_trigger == 6.5
        assert score.search_demand == 7.5
        assert score.competition == 6.0
        assert score.evergreen_potential == 8.0
        assert score.monetization_relevance == 5.0
        assert score.final_score == 7.1


class TestOpportunityScorerRegistration:
    """OPPORTUNITY_SCORER_REGISTRATION pins model, prompt version, and worker version."""

    def test_model_is_sonnet(self):
        assert OPPORTUNITY_SCORER_REGISTRATION.model == "claude-sonnet-4-6"

    def test_prompt_version_is_v1(self):
        assert OPPORTUNITY_SCORER_REGISTRATION.prompt_version == "v1"

    def test_worker_version_is_set(self):
        assert OPPORTUNITY_SCORER_REGISTRATION.worker_version == "1.0.0"

    def test_prompt_is_non_empty(self):
        assert len(OPPORTUNITY_SCORER_REGISTRATION.prompt) > 50

    def test_sampling_params_include_adaptive_thinking(self):
        assert OPPORTUNITY_SCORER_REGISTRATION.sampling_params.get("thinking") == {
            "type": "adaptive"
        }
