"""Tests for P6-S4 / P7-S1: /run and /produce Telegram commands + REST endpoint + presigned URL."""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.run_manager import InMemoryRunRepository
from cf_platform.core.schemas import PipelineState, WorkerOutput
from cf_platform.core.worker_registry import InMemoryExecutionRepository
from cf_platform.interfaces.api import (
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
)
from cf_platform.interfaces.telegram import (
    format_produce_reply,
    format_produce_running,
    format_produce_usage,
    format_run_reply,
    format_run_running,
    format_run_usage,
    format_unrecognized_command,
    parse_produce_args,
    parse_produce_command,
    parse_run_args,
    parse_run_command,
)
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from src.config import Settings, get_settings
from src.main import app

_VALID_SRC_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}

# ── helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)

_STUB_TOPIC = TopicScore(
    title="Housing Affordability",
    angle="Why first-time buyers are priced out",
    novelty=8.5,
    audience_relevance=9.0,
    emotional_trigger=7.5,
    search_demand=8.0,
    competition=5.5,
    evergreen_potential=7.0,
    monetization_relevance=8.0,
    final_score=7.86,
)
_STUB_VIDEO_R2_KEY = "runs/run-test-produce/output/final.mp4"
_STUB_VIDEO_URL = "https://fake-r2.example.com/runs/run-test-produce/output/final.mp4?expires=86400"
_STUB_NICHE = "american housing economics"
_STUB_IDEA_TITLE = "Why starter homes vanished"


# ── /run <niche> parser tests ──────────────────────────────────────────────────

class TestParseRunCommand:
    """parse_run_command returns args string or None."""

    def test_niche_extracted(self):
        assert parse_run_command("/run american housing") == "american housing"

    def test_bare_run_returns_empty_string(self):
        assert parse_run_command("/run") == ""

    def test_run_with_whitespace_stripped(self):
        assert parse_run_command("/run  coffee culture  ") == "coffee culture"

    def test_unrelated_command_returns_none(self):
        assert parse_run_command("/ideas starter homes") is None

    def test_plain_text_returns_none(self):
        assert parse_run_command("just some text") is None

    def test_run_prefix_match_only(self):
        # "/running" must not match
        assert parse_run_command("/running niche") is None

    def test_produce_command_returns_none(self):
        assert parse_run_command("/produce some niche") is None


class TestParseRunArgs:
    """parse_run_args splits niche from optional --duration and --format flags."""

    def test_niche_only(self):
        assert parse_run_args("american housing economics") == ("american housing economics", 60, "portrait")

    def test_niche_with_duration(self):
        assert parse_run_args("american housing economics --duration 45") == ("american housing economics", 45, "portrait")

    def test_zero_duration_defaults_to_60(self):
        assert parse_run_args("coffee --duration 0") == ("coffee", 60, "portrait")

    def test_negative_duration_treated_as_no_flag(self):
        _, dur, _ = parse_run_args("coffee --duration -5")
        assert dur == 60

    def test_empty_args(self):
        assert parse_run_args("") == ("", 60, "portrait")


class TestFormatRunFormatters:
    """format_run_* helpers produce correct plain-string output (D049)."""

    def test_format_run_running_contains_niche(self):
        msg = format_run_running("american housing economics")
        assert "american housing economics" in msg

    def test_format_run_usage_mentions_flag(self):
        msg = format_run_usage()
        assert "--duration" in msg
        assert "/run" in msg

    def test_format_run_reply_contains_niche_run_id_url(self):
        msg = format_run_reply("american housing", "run-abc", "https://example.com/video.mp4")
        assert "american housing" in msg
        assert "run-abc" in msg
        assert "https://example.com/video.mp4" in msg

    def test_format_run_reply_mentions_expiry(self):
        msg = format_run_reply("niche", "run-id", "https://example.com/video.mp4")
        assert "24 h" in msg

    def test_format_unrecognized_command_mentions_run(self):
        msg = format_unrecognized_command("hello")
        assert "/run" in msg


# ── /produce <idea title> parser tests ────────────────────────────────────────

class TestParseProduceCommand:
    """parse_produce_command returns args string or None (named-idea flavor, P7-S1)."""

    def test_idea_title_extracted(self):
        assert parse_produce_command("/produce Why starter homes vanished") == "Why starter homes vanished"

    def test_bare_produce_returns_empty_string(self):
        assert parse_produce_command("/produce") == ""

    def test_produce_with_whitespace_stripped(self):
        assert parse_produce_command("/produce  Why rents rose  ") == "Why rents rose"

    def test_unrelated_command_returns_none(self):
        assert parse_produce_command("/run american housing") is None

    def test_plain_text_returns_none(self):
        assert parse_produce_command("just some text") is None

    def test_run_command_returns_none(self):
        assert parse_produce_command("/run some niche") is None


class TestParseProduceArgs:
    """parse_produce_args splits idea title from optional --duration and --format flags (P7-S1, P9-S6)."""

    def test_title_only(self):
        assert parse_produce_args("Why starter homes vanished") == ("Why starter homes vanished", 60, "portrait")

    def test_title_with_duration(self):
        assert parse_produce_args("Why starter homes vanished --duration 45") == ("Why starter homes vanished", 45, "portrait")

    def test_zero_duration_defaults_to_60(self):
        assert parse_produce_args("Some title --duration 0") == ("Some title", 60, "portrait")

    def test_negative_duration_treated_as_no_flag(self):
        _, dur, _ = parse_produce_args("Some title --duration -5")
        assert dur == 60

    def test_empty_args(self):
        assert parse_produce_args("") == ("", 60, "portrait")


class TestFormatProduceFormatters:
    """format_produce_* helpers for named-idea production (D049, P7-S1)."""

    def test_format_produce_running_contains_idea_title(self):
        msg = format_produce_running("Why starter homes vanished")
        assert "Why starter homes vanished" in msg

    def test_format_produce_usage_mentions_flag(self):
        msg = format_produce_usage()
        assert "--duration" in msg
        assert "/produce" in msg

    def test_format_produce_reply_contains_title_run_id_url(self):
        msg = format_produce_reply("Why starter homes vanished", "run-abc", "https://example.com/video.mp4")
        assert "Why starter homes vanished" in msg
        assert "run-abc" in msg
        assert "https://example.com/video.mp4" in msg

    def test_format_produce_reply_mentions_expiry(self):
        msg = format_produce_reply("Some title", "run-id", "https://example.com/video.mp4")
        assert "24 h" in msg

    def test_format_unrecognized_command_mentions_produce(self):
        msg = format_unrecognized_command("hello")
        assert "/produce" in msg


# ── InMemoryArtifactStorage.generate_presigned_url ────────────────────────────

class TestInMemoryStoragePresignedUrl:
    """InMemoryArtifactStorage.generate_presigned_url returns a deterministic fake URL."""

    @pytest.mark.asyncio
    async def test_returns_url_containing_key(self):
        storage = InMemoryArtifactStorage()
        url = await storage.generate_presigned_url("runs/run-test/output/final.mp4")
        assert "runs/run-test/output/final.mp4" in url

    @pytest.mark.asyncio
    async def test_expiry_in_url(self):
        storage = InMemoryArtifactStorage()
        url = await storage.generate_presigned_url("some/key", expires_in=3600)
        assert "3600" in url


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Reset dependency_overrides after each test."""
    yield
    app.dependency_overrides.clear()


# ── REST endpoint tests ────────────────────────────────────────────────────────

def _make_test_client() -> TestClient:
    """Build a TestClient with all repos overridden to in-memory."""
    from langgraph.checkpoint.memory import MemorySaver

    _storage = InMemoryArtifactStorage()
    _runs = InMemoryRunRepository()
    _execs = InMemoryExecutionRepository()
    _artifacts = InMemoryArtifactRepository()
    _checkpointer = MemorySaver()
    _settings = PlatformSettings(
        ANTHROPIC_API_KEY="test-key",
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_WEBHOOK_SECRET="test-secret",
        TELEGRAM_ALLOWED_CHAT_IDS="",
    )

    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_SRC_ENV)
    app.dependency_overrides[get_artifact_storage] = lambda: _storage
    app.dependency_overrides[get_run_repository] = lambda: _runs
    app.dependency_overrides[get_execution_repository] = lambda: _execs
    app.dependency_overrides[get_artifact_repository] = lambda: _artifacts
    app.dependency_overrides[get_graph_checkpointer] = lambda: _checkpointer
    app.dependency_overrides[get_platform_settings] = lambda: _settings
    app.dependency_overrides[get_discovery_adapters] = lambda: []

    return TestClient(app)


@contextmanager
def _stub_full_pipeline(video_r2_key: str = _STUB_VIDEO_R2_KEY):
    """Patch build_full_pipeline_graph to return a minimal mock graph that writes a video ref."""

    async def _fake_run_graph(graph, state, *, thread_id, **kwargs):
        """Simulate a pipeline run — write a video ref directly into the state."""
        state_copy = state.model_copy()
        state_copy.artifacts["video"] = video_r2_key
        return state_copy

    with patch(
        "cf_platform.interfaces.api.build_full_pipeline_graph",
        return_value=MagicMock(),
    ) as mock_build, patch(
        "cf_platform.interfaces.api.run_graph",
        side_effect=_fake_run_graph,
    ):
        yield mock_build


class TestProduceRoute:
    """POST /platform/pipeline/produce returns a run_id, r2_key, and presigned URL."""

    def test_produce_returns_200_with_video_url(self):
        client = _make_test_client()
        with _stub_full_pipeline():
            response = client.post(
                "/platform/pipeline/produce",
                json={"niche": _STUB_NICHE},
            )
        assert response.status_code == 200
        body = response.json()
        assert "run_id" in body
        assert body["video_r2_key"] == _STUB_VIDEO_R2_KEY
        assert _STUB_VIDEO_R2_KEY in body["video_url"]

    def test_produce_passes_target_duration_to_pipeline_state(self):
        client = _make_test_client()
        captured_state: list = []

        async def _capture_run_graph(graph, state, *, thread_id, **kwargs):
            captured_state.append(state)
            state_copy = state.model_copy()
            state_copy.artifacts["video"] = _STUB_VIDEO_R2_KEY
            return state_copy

        with patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=MagicMock()), \
             patch("cf_platform.interfaces.api.run_graph", side_effect=_capture_run_graph):
            response = client.post(
                "/platform/pipeline/produce",
                json={"niche": _STUB_NICHE, "target_duration_seconds": 45},
            )
        assert response.status_code == 200
        assert captured_state[0].target_duration_seconds == 45

    def test_produce_niche_in_pipeline_state_inputs(self):
        client = _make_test_client()
        captured_state: list = []

        async def _capture_run_graph(graph, state, *, thread_id, **kwargs):
            captured_state.append(state)
            state_copy = state.model_copy()
            state_copy.artifacts["video"] = _STUB_VIDEO_R2_KEY
            return state_copy

        with patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=MagicMock()), \
             patch("cf_platform.interfaces.api.run_graph", side_effect=_capture_run_graph):
            client.post("/platform/pipeline/produce", json={"niche": _STUB_NICHE})
        assert captured_state[0].inputs.get("niche") == _STUB_NICHE


# ── Telegram webhook /run tests ────────────────────────────────────────────────

_WEBHOOK_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}


def _telegram_payload(text: str, chat_id: int = 12345) -> dict:
    """Build a minimal Telegram webhook update payload."""
    return {"message": {"chat": {"id": chat_id}, "text": text}}


class TestTelegramWebhookRun:
    """/run command wires _run_pipeline_and_reply as a BackgroundTask."""

    def test_run_command_sends_ack_and_schedules_background(self):
        client = _make_test_client()
        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/run {_STUB_NICHE}"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_bare_run_sends_usage_reply(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload("/run"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200
        assert any("/run" in m for m in sent_messages)

    def test_run_ack_message_contains_niche(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/run {_STUB_NICHE}"),
                headers=_WEBHOOK_HEADERS,
            )
        ack = next((m for m in sent_messages if _STUB_NICHE in m), None)
        assert ack is not None, f"Expected ack containing niche; got: {sent_messages}"

    def test_run_with_duration_flag_schedules_background(self):
        client = _make_test_client()
        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/run {_STUB_NICHE} --duration 45"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200


# ── Telegram webhook /produce <idea title> tests ───────────────────────────────

class TestTelegramWebhookProduce:
    """/produce <idea title> command wires _run_pipeline_and_reply with idea_title set (P7-S1)."""

    def test_produce_command_sends_ack_and_schedules_background(self):
        client = _make_test_client()
        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/produce {_STUB_IDEA_TITLE}"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_bare_produce_sends_usage_reply(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload("/produce"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200
        assert any("/produce" in m for m in sent_messages)

    def test_produce_ack_message_contains_idea_title(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/produce {_STUB_IDEA_TITLE}"),
                headers=_WEBHOOK_HEADERS,
            )
        ack = next((m for m in sent_messages if _STUB_IDEA_TITLE in m), None)
        assert ack is not None, f"Expected ack containing idea title; got: {sent_messages}"

    def test_produce_with_duration_flag_schedules_background(self):
        client = _make_test_client()
        with patch("cf_platform.interfaces.api._run_pipeline_and_reply", new_callable=AsyncMock), \
             patch("cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock):
            response = client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload(f"/produce {_STUB_IDEA_TITLE} --duration 45"),
                headers=_WEBHOOK_HEADERS,
            )
        assert response.status_code == 200


class TestTelegramWebhookUnrecognized:
    """Unrecognized commands fall through to format_unrecognized_command."""

    def test_unrecognized_command_mentions_produce(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload("hello"),
                headers=_WEBHOOK_HEADERS,
            )
        assert any("/produce" in m for m in sent_messages)

    def test_unrecognized_command_mentions_run(self):
        client = _make_test_client()
        sent_messages: list[str] = []

        async def _fake_send(chat_id, text):
            sent_messages.append(text)

        with patch("cf_platform.interfaces.api.TelegramClient.send_message", side_effect=_fake_send):
            client.post(
                "/platform/telegram/webhook",
                json=_telegram_payload("hello"),
                headers=_WEBHOOK_HEADERS,
            )
        assert any("/run" in m for m in sent_messages)
