"""Tests for the Script Writer worker (P5-S1).

Covers:
- Happy path: ranked_ideas artifact in storage → N drafts returned
- Niche, title, and angle passed to Claude in user message
- N drafts count respected (default 3, overridable via state.max_iterations)
- Invalid JSON from Claude → ValueError raised
- Missing ranked_ideas key in state → KeyError raised
- Registration pins model, prompt version, worker version, and prompt content
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.script_writer import (
    SCRIPT_WRITER_REGISTRATION,
    ScriptDraft,
    ScriptDraftsArtifact,
    build_script_writer_worker,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="topic_selector",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(timezone.utc),
    )


def _topic_score(title: str = "Why Starter Homes Disappeared", angle: str = "Supply gap narrative") -> TopicScore:
    return TopicScore(
        title=title,
        angle=angle,
        novelty=8.0,
        audience_relevance=9.0,
        emotional_trigger=7.0,
        search_demand=8.5,
        competition=6.0,
        evergreen_potential=8.0,
        monetization_relevance=7.5,
        final_score=7.8,
    )


async def _seed_ranked_ideas(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    niche: str = "starter homes",
) -> str:
    """Write a RankedIdeasArtifact to storage and return its r2_key."""
    body = RankedIdeasArtifact(
        niche=niche,
        generated_at=datetime.now(timezone.utc),
        selected=_topic_score(),
        alternatives=[_topic_score("The 2024 Housing Squeeze", "Affordability by city")],
        mode="single",
    )
    artifact = await write_artifact(
        storage,
        body,
        name="ranked_ideas",
        stage="niche_to_ideas",
        run_id=run_id,
        user_id=user_id,
        lineage=_lineage(run_id),
    )
    return artifact.r2_key


def _drafts_json(n: int = 3) -> str:
    return json.dumps([
        {"draft_number": i + 1, "script": f"Draft {i + 1}: In 1980 a home cost three years of savings..."}
        for i in range(n)
    ])


def _mock_anthropic_client(response_text: str) -> MagicMock:
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


# ── worker tests ───────────────────────────────────────────────────────────


class TestScriptWriterWorker:
    """build_script_writer_worker produces ScriptDraftsArtifact from ranked_ideas."""

    @pytest.mark.asyncio
    async def test_generates_script_drafts_from_ranked_ideas(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, ScriptDraftsArtifact)
        assert output.artifact.niche == "starter homes"
        assert output.artifact.idea_title == "Why Starter Homes Disappeared"
        assert output.artifact.idea_angle == "Supply gap narrative"
        assert len(output.artifact.drafts) == 3
        assert output.artifact.drafts[0].draft_number == 1
        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_passes_niche_title_and_angle_to_claude(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "starter homes" in user_content
        assert "Why Starter Homes Disappeared" in user_content
        assert "Supply gap narrative" in user_content

    @pytest.mark.asyncio
    async def test_default_n_drafts_is_three(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "3 draft" in call_kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_n_drafts_overridden_via_state_max_iterations(self):
        """state.max_iterations overrides the factory-level n_drafts default."""
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)

        class FakeState(StageState):
            max_iterations: int = 5

        state = FakeState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(5))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "5 draft" in call_kwargs["messages"][0]["content"]
        assert len(output.artifact.drafts) == 5

    @pytest.mark.asyncio
    async def test_invalid_json_from_claude_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client("Here are some scripts for you!")

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="invalid JSON"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_missing_ranked_ideas_key_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={},
        )
        worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
        with pytest.raises(KeyError, match="ranked_ideas"):
            await worker(state)

    @pytest.mark.asyncio
    async def test_draft_fields_are_present(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(2))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key", n_drafts=2)
            output = await worker(state)

        for i, draft in enumerate(output.artifact.drafts):
            assert isinstance(draft, ScriptDraft)
            assert draft.draft_number == i + 1
            assert len(draft.script) > 0

    @pytest.mark.asyncio
    async def test_niche_propagated_to_artifact(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage, niche="luxury condos")
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(1))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key", n_drafts=1)
            output = await worker(state)

        assert output.artifact.niche == "luxury condos"


# ── registration tests ────────────────────────────────────────────────────


class TestScriptWriterRegistration:
    """SCRIPT_WRITER_REGISTRATION pins model, prompt version, and worker version."""

    def test_model_is_haiku(self):
        assert SCRIPT_WRITER_REGISTRATION.model == "claude-haiku-4-5"

    def test_prompt_version_is_v1(self):
        assert SCRIPT_WRITER_REGISTRATION.prompt_version == "v1"

    def test_worker_version_is_set(self):
        assert SCRIPT_WRITER_REGISTRATION.worker_version == "1.0.0"

    def test_prompt_is_non_empty(self):
        assert len(SCRIPT_WRITER_REGISTRATION.prompt) > 50

    def test_sampling_params_default_empty(self):
        assert SCRIPT_WRITER_REGISTRATION.sampling_params == {}
