"""Tests for P7-S1 — Idea selection flow.

Covers:
  - parse_pick_command: valid, malformed, out-of-range inputs
  - format_pick_usage / format_pick_running: Telegram formatters
  - format_ranked_ideas: updated to show numbered 1–5 with run_id + pick CTA
  - format_unrecognized_command: updated to mention /pick
  - PipelineState.idea_title: field present and defaults to None
  - PipelineState idea_title override: orchestrator routes START → idea_to_script
  - _run_pick_and_reply: happy path, no ranked_ideas artifact, idea_number out of range
  - /pick webhook branch: schedules background task
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cf_platform.interfaces.telegram import (
    format_pick_running,
    format_pick_usage,
    format_ranked_ideas,
    format_unrecognized_command,
    parse_pick_command,
)
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.opportunity_scorer import TopicScore

_RUN_ID = "run-p7s1-test"


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_topic_score(title: str, score: float = 7.5) -> TopicScore:
    return TopicScore(
        title=title,
        angle=f"Angle for {title}",
        novelty=score,
        audience_relevance=score,
        emotional_trigger=score,
        search_demand=score,
        competition=score,
        evergreen_potential=score,
        monetization_relevance=score,
        final_score=score,
    )


def _make_ranked_ideas(n_alternatives: int = 4) -> RankedIdeasArtifact:
    """Return a RankedIdeasArtifact with a selected idea and n_alternatives alternatives."""
    return RankedIdeasArtifact(
        niche="american housing economics",
        generated_at=datetime.now(timezone.utc),
        selected=_make_topic_score("Why Starter Homes Vanished", 9.0),
        alternatives=[_make_topic_score(f"Alt Idea {i}", 8.0 - i * 0.5) for i in range(n_alternatives)],
        mode="top_n",
    )


# ── parse_pick_command ────────────────────────────────────────────────────────


def test_parse_pick_command_valid() -> None:
    """/pick <run_id> <n> returns (run_id, n, default_duration) for valid in-range n."""
    result = parse_pick_command("/pick abc-123 1")
    assert result == ("abc-123", 1, 60)


def test_parse_pick_command_valid_n5() -> None:
    """n=5 is the maximum valid index."""
    result = parse_pick_command("/pick run-xyz 5")
    assert result == ("run-xyz", 5, 60)


def test_parse_pick_command_with_duration_flag() -> None:
    """/pick with --duration extracts duration into the third element."""
    result = parse_pick_command("/pick abc-123 2 --duration 45")
    assert result == ("abc-123", 2, 45)


def test_parse_pick_command_with_zero_duration_defaults() -> None:
    """--duration 0 is invalid; falls back to default 60 s."""
    result = parse_pick_command("/pick abc-123 3 --duration 0")
    assert result is not None
    assert result[2] == 60


def test_parse_pick_command_n_zero_returns_none() -> None:
    """n=0 is out of range — returns None."""
    assert parse_pick_command("/pick abc-123 0") is None


def test_parse_pick_command_n_six_returns_none() -> None:
    """n > _IDEAS_TOP_N returns None."""
    assert parse_pick_command("/pick abc-123 6") is None


def test_parse_pick_command_non_integer_n_returns_none() -> None:
    """Non-integer n returns None."""
    assert parse_pick_command("/pick abc-123 two") is None


def test_parse_pick_command_missing_n_returns_none() -> None:
    """Only run_id provided — returns None."""
    assert parse_pick_command("/pick abc-123") is None


def test_parse_pick_command_extra_args_returns_none() -> None:
    """Extra tokens (not a --duration flag) after <n> return None."""
    assert parse_pick_command("/pick abc-123 2 extra") is None


def test_parse_pick_command_non_pick_command_returns_none() -> None:
    """Non-/pick text returns None."""
    assert parse_pick_command("/ideas housing") is None
    assert parse_pick_command("pick abc-123 1") is None


# ── format_pick_usage / format_pick_running ───────────────────────────────────


def test_format_pick_usage_contains_example() -> None:
    """format_pick_usage mentions the command syntax."""
    text = format_pick_usage()
    assert "/pick" in text
    assert "<run_id>" in text


def test_format_pick_running_contains_idea_title() -> None:
    """format_pick_running includes the idea title."""
    text = format_pick_running(_RUN_ID, "Why Starter Homes Vanished")
    assert "Why Starter Homes Vanished" in text


def test_format_pick_running_contains_run_id_suffix() -> None:
    """format_pick_running uses the last 4 chars of run_id for brevity."""
    text = format_pick_running("abcdefgh", "Some Idea")
    assert "efgh" in text


# ── format_ranked_ideas (updated) ────────────────────────────────────────────


def test_format_ranked_ideas_shows_five_numbered_ideas() -> None:
    """format_ranked_ideas lists 5 ideas numbered 1–5."""
    ranked = _make_ranked_ideas(n_alternatives=4)
    text = format_ranked_ideas("housing", _RUN_ID, "key", ranked)
    for n in range(1, 6):
        assert f"{n}." in text


def test_format_ranked_ideas_selected_is_number_one() -> None:
    """The selected idea appears as idea #1."""
    ranked = _make_ranked_ideas()
    text = format_ranked_ideas("housing", _RUN_ID, "key", ranked)
    lines = text.splitlines()
    # Find the "1." line and check it contains the selected title.
    numbered_1 = next(l for l in lines if l.startswith("1."))
    assert "Why Starter Homes Vanished" in numbered_1


def test_format_ranked_ideas_contains_run_id() -> None:
    """format_ranked_ideas includes the run_id so the operator knows which run to /pick from."""
    ranked = _make_ranked_ideas()
    text = format_ranked_ideas("housing", _RUN_ID, "key", ranked)
    assert _RUN_ID in text


def test_format_ranked_ideas_contains_pick_cta() -> None:
    """format_ranked_ideas ends with a /pick call-to-action."""
    ranked = _make_ranked_ideas()
    text = format_ranked_ideas("housing", _RUN_ID, "key", ranked)
    assert "/pick" in text
    assert _RUN_ID in text


def test_format_ranked_ideas_fewer_than_five_alternatives_shows_all() -> None:
    """When fewer than 5 total ideas exist, only available ones are shown."""
    ranked = _make_ranked_ideas(n_alternatives=2)  # selected + 2 alts = 3 total
    text = format_ranked_ideas("housing", _RUN_ID, "key", ranked)
    assert "1." in text
    assert "2." in text
    assert "3." in text
    assert "4." not in text.split("Pick")[0]  # 4. should not appear before CTA


def test_format_unrecognized_command_mentions_pick() -> None:
    """format_unrecognized_command now lists /pick as a known command."""
    text = format_unrecognized_command("/blah")
    assert "/pick" in text


# ── PipelineState.idea_title ──────────────────────────────────────────────────


def test_pipeline_state_idea_title_defaults_to_none() -> None:
    """PipelineState.idea_title is Optional[str] and defaults to None."""
    from cf_platform.core.schemas import PipelineState

    state = PipelineState(run_id="r", user_id="u", inputs={})
    assert state.idea_title is None


def test_pipeline_state_idea_title_can_be_set() -> None:
    """PipelineState.idea_title can be set to a string."""
    from cf_platform.core.schemas import PipelineState

    state = PipelineState(run_id="r", user_id="u", inputs={}, idea_title="My Idea")
    assert state.idea_title == "My Idea"


# ── full_pipeline: START routing with idea_title ──────────────────────────────


def test_full_pipeline_graph_compiles_with_idea_title_routing() -> None:
    """build_full_pipeline_graph compiles successfully (tests the conditional START edge)."""
    from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
    from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
    from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerRegistry
    from cf_platform.core.trace_repo import InMemoryTraceEventRepository
    from cf_platform.blocks.niche_to_ideas import register_niche_to_ideas_workers
    from cf_platform.blocks.idea_to_script import register_idea_to_script_workers

    registry = WorkerRegistry()
    register_niche_to_ideas_workers(registry)
    register_idea_to_script_workers(registry)

    # Inject a mock adapter to avoid loading src.config.Settings (requires env vars).
    mock_adapter = MagicMock()

    graph = build_full_pipeline_graph(
        storage=InMemoryArtifactStorage(),
        registry=registry,
        executions=InMemoryExecutionRepository(),
        artifact_repo=InMemoryArtifactRepository(),
        adapters=[],
        trace_repo=InMemoryTraceEventRepository(),
        anthropic_api_key="",
        legacy_adapter=mock_adapter,
    )
    assert graph is not None


# ── _run_pick_and_reply ───────────────────────────────────────────────────────


def _make_ranked_ideas_record(r2_key: str = "runs/orig/ranked_ideas@v1.json") -> Any:
    """Return a mock Artifact record for the 'ranked_ideas' artifact."""
    record = MagicMock()
    record.name = "ranked_ideas"
    record.version = 1
    record.r2_key = r2_key
    return record


def _make_ranked_ideas_body(n_alternatives: int = 4) -> dict:
    return _make_ranked_ideas(n_alternatives).model_dump(mode="json")


@pytest.mark.asyncio
async def test_run_pick_happy_path_calls_produce_and_reply() -> None:
    """_run_pick_and_reply reads the artifact, extracts idea N, and calls _run_pipeline_and_reply."""
    from cf_platform.interfaces.api import _run_pick_and_reply

    mock_storage = MagicMock()
    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[_make_ranked_ideas_record()])

    ranked_body = _make_ranked_ideas_body()
    mock_storage.read = AsyncMock(return_value=ranked_body)

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"

    sent_messages: list[str] = []

    with (
        patch("cf_platform.interfaces.api.read_artifact", new_callable=AsyncMock, return_value=("key", ranked_body)),
        patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock) as mock_produce,
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pick_and_reply(
            chat_id=42,
            original_run_id="orig-run",
            idea_number=1,
            settings=mock_settings,
            adapters=[],
            storage=mock_storage,
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=mock_artifacts,
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
        )

    # Should have sent an ack and then delegated to _run_pipeline_and_reply.
    assert len(sent_messages) == 1  # ack before delegating
    mock_produce.assert_called_once()
    call_kwargs = mock_produce.call_args.kwargs
    assert call_kwargs["idea_title"] == "Why Starter Homes Vanished"
    assert call_kwargs["niche"] == "american housing economics"
    assert call_kwargs["display_label"] == "Why Starter Homes Vanished"


@pytest.mark.asyncio
async def test_run_pick_idea_number_two_picks_first_alternative() -> None:
    """idea_number=2 selects alternatives[0]."""
    from cf_platform.interfaces.api import _run_pick_and_reply

    ranked_body = _make_ranked_ideas_body()
    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[_make_ranked_ideas_record()])

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"

    with (
        patch("cf_platform.interfaces.api.read_artifact", new_callable=AsyncMock, return_value=("key", ranked_body)),
        patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock) as mock_produce,
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock()
        mock_client_cls.return_value = mock_client

        await _run_pick_and_reply(
            chat_id=42,
            original_run_id="orig-run",
            idea_number=2,
            settings=mock_settings,
            adapters=[],
            storage=MagicMock(),
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=mock_artifacts,
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
        )

    call_kwargs = mock_produce.call_args.kwargs
    assert call_kwargs["idea_title"] == "Alt Idea 0"


@pytest.mark.asyncio
async def test_run_pick_no_ranked_ideas_artifact_sends_error() -> None:
    """_run_pick_and_reply sends an error when no ranked_ideas artifact is found."""
    from cf_platform.interfaces.api import _run_pick_and_reply

    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[])  # no artifacts

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"

    sent_messages: list[str] = []

    with patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pick_and_reply(
            chat_id=42,
            original_run_id="no-ideas-run",
            idea_number=1,
            settings=mock_settings,
            adapters=[],
            storage=MagicMock(),
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=mock_artifacts,
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
        )

    assert len(sent_messages) == 1
    assert "No ideas found" in sent_messages[0]


@pytest.mark.asyncio
async def test_run_pick_idea_number_out_of_range_sends_error() -> None:
    """_run_pick_and_reply sends an error when idea_number exceeds available ideas."""
    from cf_platform.interfaces.api import _run_pick_and_reply

    # Only 2 alternatives → 3 total ideas; idea_number=4 is out of range.
    ranked_body = _make_ranked_ideas_body(n_alternatives=2)
    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[_make_ranked_ideas_record()])

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"

    sent_messages: list[str] = []

    with (
        patch("cf_platform.interfaces.api.read_artifact", new_callable=AsyncMock, return_value=("key", ranked_body)),
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pick_and_reply(
            chat_id=42,
            original_run_id="small-run",
            idea_number=4,
            settings=mock_settings,
            adapters=[],
            storage=MagicMock(),
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=mock_artifacts,
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
        )

    assert len(sent_messages) == 1
    assert "not found" in sent_messages[0] or "only has" in sent_messages[0]


# ── /pick webhook branch ──────────────────────────────────────────────────────


def _make_pick_client() -> TestClient:
    """Build a TestClient for the Telegram webhook with all deps overridden."""
    from cf_platform.interfaces.api import (
        get_artifact_repository,
        get_artifact_storage,
        get_discovery_adapters,
        get_execution_repository,
        get_graph_checkpointer,
        get_platform_settings,
        get_run_repository,
        get_trace_event_repository,
        get_worker_registry,
        router,
    )

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"
    mock_settings.TELEGRAM_WEBHOOK_SECRET = "secret"
    mock_settings.TELEGRAM_ALLOWED_CHAT_IDS = ""

    app = FastAPI()
    app.include_router(router, prefix="/platform")
    app.dependency_overrides[get_artifact_storage] = lambda: MagicMock()
    app.dependency_overrides[get_worker_registry] = lambda: MagicMock()
    app.dependency_overrides[get_run_repository] = lambda: MagicMock()
    app.dependency_overrides[get_execution_repository] = lambda: MagicMock()
    app.dependency_overrides[get_artifact_repository] = lambda: MagicMock()
    app.dependency_overrides[get_trace_event_repository] = lambda: MagicMock()
    app.dependency_overrides[get_graph_checkpointer] = lambda: MagicMock()
    app.dependency_overrides[get_platform_settings] = lambda: mock_settings
    app.dependency_overrides[get_discovery_adapters] = lambda: []
    return TestClient(app, raise_server_exceptions=True)


def test_pick_webhook_schedules_background_task() -> None:
    """/pick <run_id> <n> acks immediately and schedules _run_pick_and_reply."""
    client = _make_pick_client()

    with patch("cf_platform.interfaces.api._run_pick_and_reply", new_callable=AsyncMock):
        response = client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": f"/pick {_RUN_ID} 2"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_pick_webhook_invalid_command_falls_through_to_unrecognized() -> None:
    """/pick with bad args (non-integer n) is treated as an unrecognized command."""
    client = _make_pick_client()

    with (
        patch("cf_platform.interfaces.api._run_pick_and_reply", new_callable=AsyncMock),
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_tc = MagicMock()
        mock_tc.send_message = AsyncMock()
        mock_client_cls.return_value = mock_tc

        response = client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": "/pick bad-args notanumber"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert response.status_code == 200
    # send_message should have been called with the unrecognized-command reply.
    mock_tc.send_message.assert_called_once()
    reply_text = mock_tc.send_message.call_args[0][1]
    assert "/pick" in reply_text or "didn't understand" in reply_text
