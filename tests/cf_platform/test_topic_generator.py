"""Tests for the topic generator worker (P4-S1).

Covers:
- Happy path: signals artifact in storage → topics returned
- Invalid JSON from Claude → ValueError raised
- Missing discovery key in state → KeyError raised
- Registration pins model, prompt version, and prompt content
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, Signal, StageState
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.topic_generator import (
    TOPIC_GENERATOR_REGISTRATION,
    CandidateTopicsArtifact,
    build_topic_generator_worker,
)


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="discovery",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(UTC),
    )


async def _seed_signals(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    signals: list[Signal] | None = None,
) -> str:
    """Write a SignalsArtifact to storage and return its r2_key."""
    body = SignalsArtifact(
        niche="starter homes",
        generated_at=datetime.now(UTC),
        signals=signals
        if signals is not None
        else [
            Signal(source="youtube", title="Why Americans Can't Find Starter Homes", score=1_000_000.0),
            Signal(source="reddit", title="Priced out of every market", score=5_000.0),
        ],
    )
    artifact = await write_artifact(
        storage,
        body,
        name="discovery",
        stage="niche_to_ideas",
        run_id=run_id,
        user_id=user_id,
        lineage=_lineage(run_id),
    )
    return artifact.r2_key


def _mock_anthropic_client(response_text: str) -> MagicMock:
    """Build a mock AsyncAnthropic client returning response_text as the message body."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


class TestTopicGeneratorWorker:
    """build_topic_generator_worker produces CandidateTopicsArtifact from signals."""

    @pytest.mark.asyncio
    async def test_generates_candidate_topics_from_signals(self):
        storage = InMemoryArtifactStorage()
        signals_key = await _seed_signals(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"discovery": signals_key},
        )
        topics_json = json.dumps([
            {"title": "Why Starter Homes Disappeared", "angle": "Show the supply gap."},
            {"title": "The 2024 Housing Squeeze", "angle": "Compare affordability across cities."},
        ])
        mock_client = _mock_anthropic_client(topics_json)

        with patch("cf_platform.workers.topic_generator.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_topic_generator_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, CandidateTopicsArtifact)
        assert output.artifact.niche == "starter homes"
        assert len(output.artifact.topics) == 2
        assert output.artifact.topics[0].title == "Why Starter Homes Disappeared"
        assert output.artifact.topics[1].angle == "Compare affordability across cities."
        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_passes_niche_and_signals_to_claude(self):
        storage = InMemoryArtifactStorage()
        signals_key = await _seed_signals(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"discovery": signals_key},
        )
        mock_client = _mock_anthropic_client(json.dumps([
            {"title": "T", "angle": "A"}
        ]))

        with patch("cf_platform.workers.topic_generator.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_topic_generator_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "starter homes" in user_content
        assert "YouTube" in user_content or "youtube" in user_content.lower()
        assert "Why Americans Can't Find Starter Homes" in user_content

    @pytest.mark.asyncio
    async def test_invalid_json_from_claude_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        signals_key = await _seed_signals(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"discovery": signals_key},
        )
        mock_client = _mock_anthropic_client("Sorry, I cannot help with that.")

        with patch("cf_platform.workers.topic_generator.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_topic_generator_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="invalid JSON"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_missing_discovery_key_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={},
        )
        worker = build_topic_generator_worker(storage, anthropic_api_key="test-key")

        with pytest.raises(KeyError, match="discovery"):
            await worker(state)

    @pytest.mark.asyncio
    async def test_empty_signals_list_still_calls_claude(self):
        storage = InMemoryArtifactStorage()
        signals_key = await _seed_signals(storage, signals=[])
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "starter homes"},
            artifacts={"discovery": signals_key},
        )
        mock_client = _mock_anthropic_client(json.dumps([
            {"title": "General housing topic", "angle": "Broad overview."}
        ]))

        with patch("cf_platform.workers.topic_generator.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_topic_generator_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, CandidateTopicsArtifact)
        assert len(output.artifact.topics) == 1
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "(no signals)" in call_kwargs["messages"][0]["content"]


class TestTopicGeneratorRegistration:
    """TOPIC_GENERATOR_REGISTRATION pins model, prompt version, and worker version."""

    def test_model_is_sonnet(self):
        assert TOPIC_GENERATOR_REGISTRATION.model == "claude-sonnet-4-6"

    def test_prompt_version_is_v2(self):
        assert TOPIC_GENERATOR_REGISTRATION.prompt_version == "v2"

    def test_worker_version_is_set(self):
        assert TOPIC_GENERATOR_REGISTRATION.worker_version == "1.1.0"

    def test_prompt_is_non_empty(self):
        assert len(TOPIC_GENERATOR_REGISTRATION.prompt) > 50

    def test_prompt_has_no_hardcoded_channel(self):
        prompt = TOPIC_GENERATOR_REGISTRATION.prompt
        assert "Housing Equation" not in prompt
        assert "american housing economics" not in prompt.lower()
