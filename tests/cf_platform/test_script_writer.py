"""Tests for the Script Writer worker (P5-S1).

Covers:
- Full pipeline path: ranked_ideas artifact → title/niche/angle extracted
- Direct entry path: state.inputs["idea_title"] only (no ranked_ideas artifact)
- supporting_points auto-extracted from discovery artifact (top 5 by score)
- state.inputs["supporting_points"] overrides discovery signals
- Angle is optional in both paths
- N drafts count respected (default 3, overridable via state.max_iterations)
- Invalid JSON from Claude → ValueError raised
- Missing both ranked_ideas AND idea_title → KeyError raised
- Registration pins model, prompt version, worker version, prompt content
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, Signal, StageState
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.script_writer import (
    SCRIPT_WRITER_REGISTRATION,
    ScriptDraft,
    ScriptDraftsArtifact,
    build_script_writer_worker,
)
from cf_platform.workers.topic_selector import RankedIdeasArtifact

# ── helpers ────────────────────────────────────────────────────────────────


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="topic_selector",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(UTC),
    )


def _topic_score(
    title: str = "Why Starter Homes Disappeared",
    angle: str = "Supply gap narrative",
) -> TopicScore:
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
    body = RankedIdeasArtifact(
        niche=niche,
        generated_at=datetime.now(UTC),
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


async def _seed_discovery(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    niche: str = "starter homes",
) -> str:
    body = SignalsArtifact(
        niche=niche,
        generated_at=datetime.now(UTC),
        signals=[
            Signal(source="reddit", title="Why can't millennials afford homes?", score=9500.0),
            Signal(source="youtube", title="Housing crash 2024 explained", score=8200.0),
            Signal(source="google_trends", title="starter home shortage", score=7100.0),
            Signal(source="reddit", title="The real reason builders stopped making small homes", score=6800.0),
            Signal(source="youtube", title="30-year mortgage trap", score=5400.0),
            Signal(source="reddit", title="Low priority signal", score=100.0),
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


# ── full pipeline path (ranked_ideas artifact) ────────────────────────────


class TestScriptWriterFullPipelinePath:
    """Worker reads title/niche/angle from ranked_ideas artifact."""

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


# ── direct entry path (state.inputs only) ────────────────────────────────


class TestScriptWriterDirectEntryPath:
    """Worker falls back to state.inputs when no ranked_ideas artifact."""

    @pytest.mark.asyncio
    async def test_direct_entry_with_idea_title_in_inputs(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"idea_title": "Why starter homes disappeared"},
            artifacts={},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.idea_title == "Why starter homes disappeared"
        assert output.artifact.niche is None
        assert output.artifact.idea_angle is None

    @pytest.mark.asyncio
    async def test_direct_entry_title_appears_in_prompt(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"idea_title": "The mortgage rate trap"},
            artifacts={},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "The mortgage rate trap" in call_kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_direct_entry_with_optional_niche_and_angle(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={
                "idea_title": "The mortgage rate trap",
                "niche": "mortgage rates",
                "angle": "Lock-in effect narrative",
            },
            artifacts={},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "mortgage rates" in user_content
        assert "Lock-in effect narrative" in user_content

    @pytest.mark.asyncio
    async def test_missing_both_ranked_ideas_and_idea_title_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={},
        )
        worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
        with pytest.raises(KeyError, match="idea_title"):
            await worker(state)


# ── supporting points ─────────────────────────────────────────────────────


class TestScriptWriterSupportingPoints:
    """Supporting points from discovery artifact and inputs override."""

    @pytest.mark.asyncio
    async def test_discovery_signals_appear_in_prompt(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        discovery_key = await _seed_discovery(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key, "discovery": discovery_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Source signals" in user_content
        assert "millennials" in user_content  # top signal title
        assert "Low priority signal" not in user_content  # 6th signal dropped

    @pytest.mark.asyncio
    async def test_discovery_signals_capped_at_five(self):
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        discovery_key = await _seed_discovery(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts={"ranked_ideas": ranked_key, "discovery": discovery_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        # 6 signals seeded, only 5 should appear (lowest score dropped)
        bullet_count = user_content.count("\n-")
        assert bullet_count <= 5

    @pytest.mark.asyncio
    async def test_inputs_supporting_points_used_in_direct_entry(self):
        storage = InMemoryArtifactStorage()
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={
                "idea_title": "The mortgage rate trap",
                "supporting_points": ["Rates hit 8% in Oct 2023", "Lock-in effect froze 2M listings"],
            },
            artifacts={},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Rates hit 8% in Oct 2023" in user_content
        assert "Lock-in effect froze 2M listings" in user_content

    @pytest.mark.asyncio
    async def test_inputs_supporting_points_override_discovery(self):
        """state.inputs["supporting_points"] takes priority over discovery artifact."""
        storage = InMemoryArtifactStorage()
        ranked_key = await _seed_ranked_ideas(storage)
        discovery_key = await _seed_discovery(storage)
        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"supporting_points": ["Custom curated fact"]},
            artifacts={"ranked_ideas": ranked_key, "discovery": discovery_key},
        )
        mock_client = _mock_anthropic_client(_drafts_json(3))

        with patch("cf_platform.workers.script_writer.anthropic.AsyncAnthropic", return_value=mock_client):
            worker = build_script_writer_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        user_content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Custom curated fact" in user_content
        assert "millennials" not in user_content  # discovery signals suppressed


# ── error handling ────────────────────────────────────────────────────────


class TestScriptWriterErrors:

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


# ── registration ──────────────────────────────────────────────────────────


class TestScriptWriterRegistration:
    """SCRIPT_WRITER_REGISTRATION pins model, prompt version, and worker version."""

    def test_model_is_haiku(self):
        assert SCRIPT_WRITER_REGISTRATION.model == "claude-haiku-4-5"

    def test_prompt_version_is_v3(self):
        assert SCRIPT_WRITER_REGISTRATION.prompt_version == "v3"

    def test_worker_version_is_set(self):
        assert SCRIPT_WRITER_REGISTRATION.worker_version == "1.2.0"

    def test_prompt_is_non_empty(self):
        assert len(SCRIPT_WRITER_REGISTRATION.prompt) > 50

    def test_sampling_params_default_empty(self):
        assert SCRIPT_WRITER_REGISTRATION.sampling_params == {}

    def test_prompt_has_no_hardcoded_channel(self):
        prompt = SCRIPT_WRITER_REGISTRATION.prompt
        assert "Housing Equation" not in prompt
        assert "american housing economics" not in prompt.lower()

    def test_prompt_includes_niche_inference_fallback(self):
        assert "infer" in SCRIPT_WRITER_REGISTRATION.prompt.lower()
        assert "niche" in SCRIPT_WRITER_REGISTRATION.prompt.lower()
