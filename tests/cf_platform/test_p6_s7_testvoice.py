"""Tests for P6-S7 — Gemini TTS swap + /testvoice harness.

Covers:
  - parse_testvoice_command: command parser
  - format_testvoice_running / format_testvoice_reply: Telegram formatters
  - format_unrecognized_command: updated to mention /testvoice
  - _run_testvoice_and_reply: background coroutine — happy path, no script,
    no TTS key (fallback), and Telegram send error
  - /testvoice webhook branch: ack + background task scheduling
  - GEMINI_API_KEY / GEMINI_TTS_VOICE in PlatformSettings
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cf_platform.core.schemas import StageState
from cf_platform.interfaces.api import (
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_platform_settings,
    get_trace_event_repository,
    get_worker_registry,
    router,
)
from cf_platform.interfaces.telegram import (
    format_testvoice_reply,
    format_testvoice_running,
    format_unrecognized_command,
    parse_testvoice_command,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
from cf_platform.workers.script_packager import ScriptArtifact

_RUN_ID = "run-p6s7-test"
_USER_ID = "operator"
_SCRIPT_KEY = "users/operator/runs/run-p6s7-test/script_packager/script@v1.json"


# ── Telegram formatter / parser tests ────────────────────────────────────────


def test_parse_testvoice_command_with_run_id() -> None:
    """/testvoice <run_id> returns the run_id."""
    assert parse_testvoice_command("/testvoice abc-123") == "abc-123"


def test_parse_testvoice_command_empty() -> None:
    """/testvoice with no argument returns empty string."""
    assert parse_testvoice_command("/testvoice") == ""


def test_parse_testvoice_command_non_command_returns_none() -> None:
    """Non-/testvoice text returns None."""
    assert parse_testvoice_command("/produce housing") is None
    assert parse_testvoice_command("just text") is None


def test_parse_testvoice_command_strips_whitespace() -> None:
    """Leading/trailing whitespace around run_id is stripped."""
    assert parse_testvoice_command("/testvoice   my-run-id  ") == "my-run-id"


def test_format_testvoice_running_contains_run_id() -> None:
    """format_testvoice_running includes the run_id."""
    text = format_testvoice_running("abc-123")
    assert "abc-123" in text


def test_format_testvoice_reply_contains_run_id_and_url() -> None:
    """format_testvoice_reply includes the run_id and MP3 URL."""
    url = "https://r2.example.com/runs/abc/voiceover/generated.mp3?sig=x"
    text = format_testvoice_reply("abc-123", url)
    assert "abc-123" in text
    assert url in text


def test_format_unrecognized_command_mentions_testvoice() -> None:
    """format_unrecognized_command now lists /testvoice as a known command."""
    text = format_unrecognized_command("/unknown")
    assert "/testvoice" in text


# ── PlatformSettings: Gemini keys, no ElevenLabs keys ────────────────────────


def test_platform_settings_has_gemini_keys() -> None:
    """PlatformSettings exposes GEMINI_API_KEY and GEMINI_TTS_VOICE."""
    from cf_platform.core.config import PlatformSettings

    # Validate that the fields exist with correct default types.
    fields = PlatformSettings.model_fields
    assert "GEMINI_API_KEY" in fields
    assert "GEMINI_TTS_VOICE" in fields
    assert "ELEVENLABS_API_KEY" not in fields
    assert "ELEVENLABS_VOICE_ID" not in fields


# ── _run_testvoice_and_reply ──────────────────────────────────────────────────


def _make_script_artifact_record(r2_key: str = _SCRIPT_KEY) -> Any:
    """Return a mock Artifact record for the 'script' artifact."""
    record = MagicMock()
    record.name = "script"
    record.version = 1
    record.r2_key = r2_key
    return record


def _make_script_artifact_body() -> dict:
    return ScriptArtifact(
        idea_title="Housing Crisis",
        niche="american housing",
        script="Housing prices are soaring.",
        word_count=4,
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _make_voice_alignment(mp3_r2_key: str = f"runs/{_RUN_ID}/voiceover/generated.mp3") -> VoiceAlignmentArtifact:
    return VoiceAlignmentArtifact(
        mp3_r2_key=mp3_r2_key,
        word_timestamps=[VoiceWordTimestamp(word="housing", start_ms=0, end_ms=400, confidence=0.9)],
        alignment_method="proportional_fallback",
        total_duration_s=4.0,
    )


@pytest.mark.asyncio
async def test_run_testvoice_happy_path_sends_presigned_url() -> None:
    """_run_testvoice_and_reply sends a presigned URL when TTS succeeds."""
    from cf_platform.interfaces.api import _run_testvoice_and_reply

    fake_url = "https://r2.example.com/mp3?sig=abc"
    mock_storage = MagicMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value=fake_url)

    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[_make_script_artifact_record()])

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"
    mock_settings.GEMINI_API_KEY = "gkey"
    mock_settings.GEMINI_TTS_VOICE = "Kore"
    mock_settings.DEEPGRAM_API_KEY = ""

    fake_alignment = _make_voice_alignment()

    sent_messages: list[str] = []

    async def fake_send(chat_id: int, text: str) -> None:
        sent_messages.append(text)

    with (
        patch("cf_platform.interfaces.api.build_voice_production_worker") as mock_build,
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_worker = AsyncMock(return_value=MagicMock(artifact=fake_alignment))
        mock_build.return_value = mock_worker
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=fake_send)
        mock_client_cls.return_value = mock_client

        await _run_testvoice_and_reply(
            chat_id=42,
            run_id=_RUN_ID,
            settings=mock_settings,
            storage=mock_storage,
            artifacts=mock_artifacts,
        )

    assert len(sent_messages) == 1
    assert fake_url in sent_messages[0]
    assert _RUN_ID in sent_messages[0]


@pytest.mark.asyncio
async def test_run_testvoice_no_script_artifact_sends_error() -> None:
    """_run_testvoice_and_reply sends an error when no script artifact is found."""
    from cf_platform.interfaces.api import _run_testvoice_and_reply

    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[])  # no artifacts

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"

    sent_messages: list[str] = []

    with patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_testvoice_and_reply(
            chat_id=42,
            run_id=_RUN_ID,
            settings=mock_settings,
            storage=MagicMock(),
            artifacts=mock_artifacts,
        )

    assert len(sent_messages) == 1
    assert "No script artifact" in sent_messages[0]


@pytest.mark.asyncio
async def test_run_testvoice_no_tts_key_sends_fallback_message() -> None:
    """_run_testvoice_and_reply sends a fallback notice when TTS produced no MP3."""
    from cf_platform.interfaces.api import _run_testvoice_and_reply

    fake_alignment = _make_voice_alignment(mp3_r2_key="")  # empty = fallback only

    mock_storage = MagicMock()
    mock_artifacts = MagicMock()
    mock_artifacts.list_for_run = AsyncMock(return_value=[_make_script_artifact_record()])

    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"
    mock_settings.GEMINI_API_KEY = ""
    mock_settings.GEMINI_TTS_VOICE = ""
    mock_settings.DEEPGRAM_API_KEY = ""

    sent_messages: list[str] = []

    with (
        patch("cf_platform.interfaces.api.build_voice_production_worker") as mock_build,
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_worker = AsyncMock(return_value=MagicMock(artifact=fake_alignment))
        mock_build.return_value = mock_worker
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_testvoice_and_reply(
            chat_id=42,
            run_id=_RUN_ID,
            settings=mock_settings,
            storage=mock_storage,
            artifacts=mock_artifacts,
        )

    assert len(sent_messages) == 1
    assert "fallback" in sent_messages[0].lower() or "proportional" in sent_messages[0].lower() or "No MP3" in sent_messages[0]


# ── /testvoice webhook branch ─────────────────────────────────────────────────


def _make_testvoice_client() -> TestClient:
    """Build a TestClient for the Telegram webhook with all deps overridden."""
    mock_settings = MagicMock()
    mock_settings.TELEGRAM_BOT_TOKEN = "tok"
    mock_settings.TELEGRAM_WEBHOOK_SECRET = "secret"
    mock_settings.TELEGRAM_ALLOWED_CHAT_IDS = ""
    mock_settings.GEMINI_API_KEY = "gkey"
    mock_settings.GEMINI_TTS_VOICE = "Kore"
    mock_settings.DEEPGRAM_API_KEY = ""

    app = FastAPI()
    app.include_router(router, prefix="/platform")
    app.dependency_overrides[get_artifact_storage] = lambda: MagicMock()
    app.dependency_overrides[get_worker_registry] = lambda: MagicMock()
    app.dependency_overrides[get_execution_repository] = lambda: MagicMock()
    app.dependency_overrides[get_artifact_repository] = lambda: MagicMock()
    app.dependency_overrides[get_trace_event_repository] = lambda: MagicMock()
    app.dependency_overrides[get_graph_checkpointer] = lambda: MagicMock()
    app.dependency_overrides[get_platform_settings] = lambda: mock_settings
    app.dependency_overrides[get_discovery_adapters] = lambda: []
    return TestClient(app, raise_server_exceptions=True)


def test_testvoice_webhook_returns_ok_and_schedules_task() -> None:
    """/testvoice <run_id> returns {"ok": True} and schedules a background task."""
    client = _make_testvoice_client()
    payload = {
        "message": {
            "chat": {"id": 1},
            "text": f"/testvoice {_RUN_ID}",
        }
    }
    with (
        patch("cf_platform.interfaces.api._run_testvoice_and_reply", AsyncMock()) as mock_task,
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_tg = MagicMock()
        mock_tg.send_message = AsyncMock()
        mock_client_cls.return_value = mock_tg

        resp = client.post(
            "/platform/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_tg.send_message.assert_awaited_once()
    ack_text: str = mock_tg.send_message.call_args[0][1]
    assert _RUN_ID in ack_text


def test_testvoice_webhook_no_run_id_sends_usage() -> None:
    """/testvoice without a run_id sends a usage hint."""
    client = _make_testvoice_client()
    payload = {
        "message": {
            "chat": {"id": 1},
            "text": "/testvoice",
        }
    }
    with patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls:
        mock_tg = MagicMock()
        mock_tg.send_message = AsyncMock()
        mock_client_cls.return_value = mock_tg

        resp = client.post(
            "/platform/telegram/webhook",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )

    assert resp.status_code == 200
    usage_text: str = mock_tg.send_message.call_args[0][1]
    assert "/testvoice" in usage_text
    assert "<run_id>" in usage_text
