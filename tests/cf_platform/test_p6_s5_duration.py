"""Tests for P6-S5 — target_duration_seconds parameter (run-level → script writer).

Covers:
- IdeaToScriptState.target_duration_seconds typed field (default 60, settable)
- parse_script_duration_args: no flag, --duration N, --duration 0, whitespace
- ScriptArtifact.length_ok: within tolerance (True), over 20% (False), under 20% (False)
- script_packager sets length_ok based on generated_script.word_count vs target_words
- REST route passes target_duration_seconds from request body to IdeaToScriptState
- Telegram /script title --duration N: ack uses parsed title (no flag text); duration flows in
"""

from datetime import datetime, timezone
from typing import Optional

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import GeneratedScriptArtifact
from cf_platform.core.schemas import IdeaToScriptState, LineageEnvelope
from cf_platform.interfaces.telegram import parse_script_duration_args
from cf_platform.workers.script_packager import ScriptArtifact, build_script_packager_worker

# ── Helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-dur",
    worker="test",
    worker_version="1.0.0",
    prompt_version="v1",
    model="none",
    created_at=_NOW,
)


def _make_generated(word_count: int, target_duration_seconds: int = 60) -> GeneratedScriptArtifact:
    """Build a GeneratedScriptArtifact with a synthetic script of `word_count` words."""
    script = " ".join("word" for _ in range(word_count))
    return GeneratedScriptArtifact(
        idea_title="Test idea",
        niche=None,
        script=script,
        word_count=word_count,
        target_duration_seconds=target_duration_seconds,
        generated_at=_NOW,
    )


async def _run_packager(
    generated: GeneratedScriptArtifact,
) -> ScriptArtifact:
    """Write `generated` to in-memory storage and run the packager."""
    storage = InMemoryArtifactStorage()
    art = await write_artifact(
        storage,
        generated,
        name="generated_script",
        stage="idea_to_script",
        run_id="run-dur",
        user_id="operator",
        lineage=_LINEAGE,
    )
    state = IdeaToScriptState(
        run_id="run-dur",
        user_id="operator",
        inputs={},
        artifacts={"generated_script": art.r2_key},
    )
    worker = build_script_packager_worker(storage)
    output = await worker(state)
    assert isinstance(output.artifact, ScriptArtifact)
    return output.artifact


# ── IdeaToScriptState typed field ─────────────────────────────────────────────


def test_state_target_duration_default():
    """IdeaToScriptState.target_duration_seconds defaults to 60."""
    state = IdeaToScriptState(run_id="r", user_id="u", inputs={})
    assert state.target_duration_seconds == 60


def test_state_target_duration_settable():
    """IdeaToScriptState.target_duration_seconds can be set at construction."""
    state = IdeaToScriptState(run_id="r", user_id="u", inputs={}, target_duration_seconds=45)
    assert state.target_duration_seconds == 45


# ── parse_script_duration_args ─────────────────────────────────────────────────


def test_parse_no_flag():
    """No --duration flag returns (title, 60)."""
    title, duration = parse_script_duration_args("Why starter homes vanished")
    assert title == "Why starter homes vanished"
    assert duration == 60


def test_parse_duration_flag_end():
    """--duration N at the end extracts the value and strips it from the title."""
    title, duration = parse_script_duration_args("Why starter homes vanished --duration 45")
    assert title == "Why starter homes vanished"
    assert duration == 45


def test_parse_duration_flag_whitespace():
    """Extra whitespace around title is stripped."""
    title, duration = parse_script_duration_args("  My Topic  --duration 30")
    assert title == "My Topic"
    assert duration == 30


def test_parse_duration_zero_falls_back():
    """--duration 0 is not a valid duration; defaults back to 60."""
    title, duration = parse_script_duration_args("My Topic --duration 0")
    assert title == "My Topic"
    assert duration == 60


def test_parse_duration_bare_title_stripped():
    """Title with no flag returns with surrounding whitespace removed."""
    title, duration = parse_script_duration_args("  bare title  ")
    assert title == "bare title"
    assert duration == 60


def test_parse_duration_different_value():
    """--duration accepts any positive integer."""
    _, duration = parse_script_duration_args("Some idea --duration 90")
    assert duration == 90


# ── script_packager length_ok ──────────────────────────────────────────────────
# target_duration_seconds=60 → target_words = round(60 * 160/60) = 160
# 20% tolerance: valid range [128, 192]


@pytest.mark.asyncio
async def test_length_ok_true_when_within_tolerance():
    """length_ok=True when word_count is within 20% of target_words."""
    # 170 words for 60s target (target_words=160): |170-160|/160=6.25% — within tolerance
    artifact = await _run_packager(_make_generated(word_count=170, target_duration_seconds=60))
    assert artifact.length_ok is True


@pytest.mark.asyncio
async def test_length_ok_false_when_over_20_percent():
    """length_ok=False when word_count is >20% over target_words."""
    # 200 words for 60s target (target_words=160): |200-160|/160=25% — over tolerance
    artifact = await _run_packager(_make_generated(word_count=200, target_duration_seconds=60))
    assert artifact.length_ok is False


@pytest.mark.asyncio
async def test_length_ok_false_when_under_20_percent():
    """length_ok=False when word_count is >20% under target_words."""
    # 100 words for 60s target (target_words=160): |100-160|/160=37.5% — under tolerance
    artifact = await _run_packager(_make_generated(word_count=100, target_duration_seconds=60))
    assert artifact.length_ok is False


@pytest.mark.asyncio
async def test_length_ok_true_at_exact_target():
    """length_ok=True when word_count equals target_words exactly."""
    # 160 words for 60s target (target_words=160): 0% deviation
    artifact = await _run_packager(_make_generated(word_count=160, target_duration_seconds=60))
    assert artifact.length_ok is True


@pytest.mark.asyncio
async def test_length_ok_respects_custom_duration():
    """length_ok uses target_words derived from generated.target_duration_seconds, not a hardcoded value."""
    # 45s target → target_words = round(45 * 160/60) = 120
    # 150 words: |150-120|/120 = 25% → over tolerance → length_ok=False
    artifact = await _run_packager(_make_generated(word_count=150, target_duration_seconds=45))
    assert artifact.length_ok is False


@pytest.mark.asyncio
async def test_length_ok_within_tolerance_custom_duration():
    """length_ok=True with a custom duration when the word_count is within range."""
    # 45s target → target_words = 120; 115 words: |115-120|/120=4.2% → ok
    artifact = await _run_packager(_make_generated(word_count=115, target_duration_seconds=45))
    assert artifact.length_ok is True


# ── REST body passes target_duration_seconds ───────────────────────────────────


def test_idea_to_script_request_default_duration():
    """IdeaToScriptRequest.target_duration_seconds defaults to 60."""
    from cf_platform.interfaces.api import IdeaToScriptRequest

    req = IdeaToScriptRequest(idea_title="My Idea")
    assert req.target_duration_seconds == 60


def test_idea_to_script_request_custom_duration():
    """IdeaToScriptRequest.target_duration_seconds accepts a custom value."""
    from cf_platform.interfaces.api import IdeaToScriptRequest

    req = IdeaToScriptRequest(idea_title="My Idea", target_duration_seconds=45)
    assert req.target_duration_seconds == 45


# ── Telegram webhook parses --duration ─────────────────────────────────────────


class TestTelegramScriptDurationFlag:
    """Telegram /script title --duration N → ack uses parsed title; duration flows in."""

    def _client(self):
        """Return a TestClient with the minimal settings needed to process a /script command."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.config import PlatformSettings
        from cf_platform.interfaces.api import (
            get_artifact_storage,
            get_graph_checkpointer,
            get_platform_settings,
        )
        from src.main import app

        settings = PlatformSettings(
            TELEGRAM_WEBHOOK_SECRET="test-secret",
            TELEGRAM_ALLOWED_CHAT_IDS="42",
        )
        app.dependency_overrides[get_platform_settings] = lambda: settings
        app.dependency_overrides[get_artifact_storage] = lambda: InMemoryArtifactStorage()

        from langgraph.checkpoint.memory import MemorySaver

        app.dependency_overrides[get_graph_checkpointer] = lambda: MemorySaver()
        return TestClient(app, raise_server_exceptions=False)

    def test_ack_contains_parsed_title_not_flag(self):
        """Ack message uses the parsed title (without --duration flag text)."""
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.config import PlatformSettings
        from cf_platform.interfaces.api import (
            get_artifact_storage,
            get_graph_checkpointer,
            get_platform_settings,
        )
        from src.main import app

        settings = PlatformSettings(
            TELEGRAM_WEBHOOK_SECRET="test-secret",
            TELEGRAM_ALLOWED_CHAT_IDS="42",
        )
        app.dependency_overrides[get_platform_settings] = lambda: settings

        from langgraph.checkpoint.memory import MemorySaver

        app.dependency_overrides[get_graph_checkpointer] = lambda: MemorySaver()

        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send, patch(
            "cf_platform.interfaces.api._run_script_and_reply", new_callable=AsyncMock
        ):
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/script My Topic --duration 45"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_send.assert_awaited_once()
        ack_text = mock_send.call_args[0][1]
        assert "My Topic" in ack_text
        assert "--duration" not in ack_text

    def test_script_command_with_duration_passes_value_to_background(self):
        """background_tasks.add_task is called with the parsed target_duration_seconds."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from cf_platform.core.config import PlatformSettings
        from cf_platform.interfaces.api import (
            get_graph_checkpointer,
            get_platform_settings,
        )
        from src.main import app

        settings = PlatformSettings(
            TELEGRAM_WEBHOOK_SECRET="test-secret",
            TELEGRAM_ALLOWED_CHAT_IDS="42",
        )
        app.dependency_overrides[get_platform_settings] = lambda: settings

        from langgraph.checkpoint.memory import MemorySaver

        app.dependency_overrides[get_graph_checkpointer] = lambda: MemorySaver()

        client = TestClient(app, raise_server_exceptions=False)

        captured: dict = {}

        real_add_task = None

        def _spy_add_task(func, **kwargs):
            """Capture the kwargs passed when _run_script_and_reply is scheduled."""
            from cf_platform.interfaces.api import _run_script_and_reply as _orig

            if func is _mock_reply or func.__name__ == "_run_script_and_reply":
                captured.update(kwargs)
            # Don't actually add the task (prevents asyncio issues in tests)

        _mock_reply = MagicMock()

        with patch("cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock), patch(
            "cf_platform.interfaces.api._run_script_and_reply", _mock_reply
        ), patch(
            "starlette.background.BackgroundTasks.add_task", side_effect=_spy_add_task
        ):
            client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/script My Topic --duration 45"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert captured.get("target_duration_seconds") == 45
        assert captured.get("idea_title") == "My Topic"
