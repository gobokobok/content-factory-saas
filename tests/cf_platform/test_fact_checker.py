"""Tests for the Fact Checker worker (P5-S3).

Covers:
- Happy path: script_drafts artifact → FactcheckReportArtifact with per-claim verdicts
- idea_title propagated from ScriptDraftsArtifact
- draft_number in artifact matches first draft's draft_number
- verified/refuted/unverifiable counts computed correctly
- idea_title and script text sent in user message to Claude
- web_search_20260209 tool passed to Claude (D053)
- Mixed content blocks handled: only text blocks used for JSON extraction
- Control "continue" when unverified_ratio <= unverified_threshold (default 0.3)
- Control "retry" when unverified_ratio > unverified_threshold
- Refuted claims count toward unverified ratio
- Control "continue" when no claims found (ratio = 0.0)
- unverified_threshold read from state attribute when present
- Missing script_drafts artifact → KeyError
- No text block in response → ValueError
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
from cf_platform.workers.fact_checker import (
    FACT_CHECKER_REGISTRATION,
    ClaimVerification,
    FactcheckReportArtifact,
    build_fact_checker_worker,
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


def _claims_json(
    verdicts: Optional[List[str]] = None,
) -> str:
    """Build a mock fact-check JSON response. verdicts defaults to one supported claim."""
    if verdicts is None:
        verdicts = ["supported"]
    claims = []
    for i, verdict in enumerate(verdicts):
        claims.append({
            "claim": f"Claim {i + 1}: housing prices rose by X%",
            "verdict": verdict,
            "source": "https://fred.stlouisfed.org/" if verdict != "unverifiable" else "",
            "note": f"Evidence {'found' if verdict == 'supported' else 'not found'}.",
        })
    return json.dumps({"claims": claims})


async def _seed_script_drafts(
    storage: InMemoryArtifactStorage,
    run_id: str = "run-1",
    user_id: str = "user-1",
    idea_title: str = "Why Starter Homes Disappeared",
    n_drafts: int = 3,
    first_draft_number: int = 1,
) -> str:
    """Write a ScriptDraftsArtifact to storage and return its r2_key."""
    body = ScriptDraftsArtifact(
        niche="starter homes",
        idea_title=idea_title,
        idea_angle="Supply gap narrative",
        drafts=[
            ScriptDraft(
                draft_number=first_draft_number + i,
                script=f"Draft {first_draft_number + i}: In 1980 a home cost 3 years of savings...",
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
    """Mock client where response has a single text block (type='text')."""
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = response_text
    mock_message = MagicMock()
    mock_message.content = [mock_text_block]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


def _mock_anthropic_client_mixed(response_text: str) -> MagicMock:
    """Mock client with mixed content blocks (server_tool_use + web_search_result + text)."""
    search_block = MagicMock()
    search_block.type = "server_tool_use"
    result_block = MagicMock()
    result_block.type = "web_search_result"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = response_text
    mock_message = MagicMock()
    mock_message.content = [search_block, result_block, text_block]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


def _mock_anthropic_client_no_text() -> MagicMock:
    """Mock client whose response contains no text blocks."""
    non_text_block = MagicMock()
    non_text_block.type = "server_tool_use"
    mock_message = MagicMock()
    mock_message.content = [non_text_block]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)
    return mock_client


# ── happy path ────────────────────────────────────────────────────────────


class TestFactCheckerHappyPath:
    """Worker reads script_drafts, verifies claims, emits FactcheckReportArtifact."""

    @pytest.mark.asyncio
    async def test_returns_factcheck_report_artifact(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(_claims_json(["supported", "supported"]))

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, FactcheckReportArtifact)
        assert len(output.artifact.claims) == 2

    @pytest.mark.asyncio
    async def test_idea_title_propagated_to_artifact(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, idea_title="The Mortgage Rate Trap")
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(_claims_json())

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.idea_title == "The Mortgage Rate Trap"

    @pytest.mark.asyncio
    async def test_draft_number_matches_first_draft(self):
        """draft_number in the artifact must be the first draft's draft_number, not hardcoded."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, n_drafts=3, first_draft_number=1)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(_claims_json())

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.draft_number == 1

    @pytest.mark.asyncio
    async def test_claim_counts_computed_correctly(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(
            _claims_json(["supported", "refuted", "unverifiable", "supported"])
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.verified_count == 2
        assert output.artifact.refuted_count == 1
        assert output.artifact.unverifiable_count == 1

    @pytest.mark.asyncio
    async def test_idea_title_and_script_sent_in_user_message(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage, idea_title="Why Starter Homes Disappeared")
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(_claims_json())

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "Why Starter Homes Disappeared" in user_content
        assert "Draft 1" in user_content


# ── web search tool ───────────────────────────────────────────────────────


class TestFactCheckerWebSearchTool:
    """web_search_20260209 tool is passed to Claude; mixed content handled correctly."""

    @pytest.mark.asyncio
    async def test_web_search_tool_passed_to_claude(self):
        """tools list must include the web_search_20260209 server-side tool (D053)."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(_claims_json())

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            await worker(state)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]

    @pytest.mark.asyncio
    async def test_mixed_content_blocks_uses_last_text_block(self):
        """When response includes server_tool_use + web_search_result + text blocks,
        the last text block is used for JSON extraction."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client_mixed(_claims_json(["supported"]))

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert isinstance(output.artifact, FactcheckReportArtifact)
        assert output.artifact.verified_count == 1


# ── control signal ────────────────────────────────────────────────────────


class TestFactCheckerControlSignal:
    """Control signal derived from unverified_ratio vs unverified_threshold."""

    @pytest.mark.asyncio
    async def test_control_continue_when_all_claims_supported(self):
        """0 / 3 unverified = 0.0 <= default 0.3 → continue."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(
            _claims_json(["supported", "supported", "supported"])
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_control_retry_when_unverified_ratio_exceeds_threshold(self):
        """2 / 3 unverified = 0.67 > default 0.3 → retry."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(
            _claims_json(["supported", "refuted", "unverifiable"])
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "retry"

    @pytest.mark.asyncio
    async def test_refuted_claims_count_toward_unverified_ratio(self):
        """A single refuted claim in 4 total = 0.25 <= 0.3 → continue (not retry)."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(
            _claims_json(["supported", "supported", "supported", "refuted"])
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.refuted_count == 1
        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_control_continue_when_no_claims_found(self):
        """Empty claims list → ratio = 0.0 → continue (no facts to refute)."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        mock_client = _mock_anthropic_client(json.dumps({"claims": []}))

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.artifact.verified_count == 0
        assert output.control == "continue"

    @pytest.mark.asyncio
    async def test_unverified_threshold_read_from_state_attribute(self):
        """When state has unverified_threshold attribute it overrides the default 0.3."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)

        class FakeState(StageState):
            unverified_threshold: float = 0.1

        state = FakeState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        # 1 / 4 = 0.25 > 0.10 → retry (would be continue at default 0.3)
        mock_client = _mock_anthropic_client(
            _claims_json(["supported", "supported", "supported", "unverifiable"])
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        assert output.control == "retry"


# ── error handling ────────────────────────────────────────────────────────


class TestFactCheckerErrors:

    @pytest.mark.asyncio
    async def test_missing_script_drafts_artifact_raises_key_error(self):
        storage = InMemoryArtifactStorage()
        state = StageState(run_id="run-1", user_id="user-1", inputs={}, artifacts={})
        worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
        with pytest.raises(KeyError, match="script_drafts"):
            await worker(state)

    @pytest.mark.asyncio
    async def test_no_text_block_in_response_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=_mock_anthropic_client_no_text(),
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="no text block"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_invalid_json_from_claude_raises_value_error(self):
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        # Completely unparseable text (no JSON object at all)
        mock_client = _mock_anthropic_client("All claims check out — the script looks great!")

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            with pytest.raises(ValueError, match="invalid JSON"):
                await worker(state)

    @pytest.mark.asyncio
    async def test_json_with_trailing_prose_is_parsed(self):
        """Regression: Claude adds text after the closing } — extra data must be stripped."""
        storage = InMemoryArtifactStorage()
        drafts_key = await _seed_script_drafts(storage)
        state = StageState(
            run_id="run-1", user_id="user-1", inputs={}, artifacts={"script_drafts": drafts_key}
        )
        # Simulate Claude adding a preamble sentence and a trailing comment around valid JSON
        json_with_prose = (
            'Here is my fact-check analysis:\n\n'
            '{"claims": [{"claim": "Starbucks closed 900 stores", "verdict": "supported",'
            ' "source": "https://example.com", "note": "Confirmed by press release."}]}\n\n'
            'I have verified each claim using authoritative sources.'
        )
        mock_client = _mock_anthropic_client(json_with_prose)

        with patch(
            "cf_platform.workers.fact_checker.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            worker = build_fact_checker_worker(storage, anthropic_api_key="test-key")
            output = await worker(state)

        report = output.artifact
        assert len(report.claims) == 1  # type: ignore[union-attr]
        assert report.claims[0].verdict == "supported"  # type: ignore[union-attr]


# ── registration ──────────────────────────────────────────────────────────


class TestFactCheckerRegistration:
    """FACT_CHECKER_REGISTRATION pins model, prompt_version, worker_version."""

    def test_model_is_sonnet(self):
        assert FACT_CHECKER_REGISTRATION.model == "claude-sonnet-4-6"

    def test_prompt_version_is_v1(self):
        assert FACT_CHECKER_REGISTRATION.prompt_version == "v1"

    def test_worker_version_is_set(self):
        assert FACT_CHECKER_REGISTRATION.worker_version == "1.0.0"

    def test_prompt_is_non_empty(self):
        assert len(FACT_CHECKER_REGISTRATION.prompt) > 50

    def test_prompt_instructs_json_output(self):
        assert "claims" in FACT_CHECKER_REGISTRATION.prompt
        assert "verdict" in FACT_CHECKER_REGISTRATION.prompt
