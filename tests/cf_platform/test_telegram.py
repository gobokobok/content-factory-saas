"""Tests for cf_platform/interfaces/telegram.py (P3-S1, D049)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.schemas import Signal
from cf_platform.interfaces.telegram import (
    TelegramClient,
    format_ideas_usage,
    format_script_reply,
    format_script_running,
    format_script_usage,
    format_signals_summary,
    format_unrecognized_command,
    is_chat_allowed,
    parse_ideas_command,
    parse_script_command,
)


class TestParseIdeasCommand:
    """parse_ideas_command extracts the niche from /ideas <niche>, per D049 (no business logic here)."""

    def test_parses_niche(self):
        """A normal /ideas <niche> command returns the niche text."""
        assert parse_ideas_command("/ideas starter homes") == "starter homes"

    def test_strips_surrounding_whitespace(self):
        """Leading/trailing whitespace around the command and niche is stripped."""
        assert parse_ideas_command("  /ideas   starter homes  ") == "starter homes"

    def test_bare_command_returns_empty_string(self):
        """/ideas with no niche returns an empty string (distinct from 'not a match')."""
        assert parse_ideas_command("/ideas") == ""

    def test_unrelated_text_returns_none(self):
        """Text that isn't an /ideas command returns None."""
        assert parse_ideas_command("hello there") is None

    def test_other_slash_command_returns_none(self):
        """A different slash command is not mistaken for /ideas."""
        assert parse_ideas_command("/ideasomethingelse foo") is None
        assert parse_ideas_command("/script foo") is None


class TestFormatters:
    """format_*() helpers never serialize internal schemas — only plain strings (D049)."""

    def test_format_signals_summary_lists_top_signals(self):
        """The summary includes the niche, run_id, artifact key, and each signal's source/title."""
        signals = [
            Signal(source="reddit", title="Starter homes are back", score=120.0),
            Signal(source="youtube", title="Why starter homes vanished", score=98000.0),
        ]

        reply = format_signals_summary("starter homes", "run-123", "users/operator/runs/run-123/discovery/discovery@v1.json", signals)

        assert "starter homes" in reply
        assert "run-123" in reply
        assert "users/operator/runs/run-123/discovery/discovery@v1.json" in reply
        assert "Why starter homes vanished" in reply
        assert "Starter homes are back" in reply
        assert isinstance(reply, str)

    def test_format_signals_summary_orders_by_score_descending(self):
        """Higher-scoring signals appear before lower-scoring ones."""
        signals = [
            Signal(source="reddit", title="low score", score=1.0),
            Signal(source="youtube", title="high score", score=999.0),
        ]

        reply = format_signals_summary("starter homes", "run-123", "key", signals)

        assert reply.index("high score") < reply.index("low score")

    def test_format_signals_summary_empty_signals(self):
        """An empty signals list produces a plain 'no signals found' message, not an empty list."""
        reply = format_signals_summary("starter homes", "run-123", "key", [])

        assert "starter homes" in reply
        assert "run-123" in reply
        assert "No signals found" in reply

    def test_format_ideas_usage_mentions_command(self):
        """The usage reply mentions the /ideas command shape."""
        assert "/ideas" in format_ideas_usage()

    def test_format_unrecognized_command(self):
        """The unrecognized-command reply is a plain string suggesting /ideas."""
        reply = format_unrecognized_command("gibberish")

        assert "/ideas" in reply


class TestIsChatAllowed:
    """is_chat_allowed enforces the temporary TELEGRAM_ALLOWED_CHAT_IDS allowlist (ahead of S19)."""

    def test_empty_allowlist_allows_any_chat(self):
        """An empty TELEGRAM_ALLOWED_CHAT_IDS means unrestricted access."""
        assert is_chat_allowed(111000111, "") is True
        assert is_chat_allowed(123, "") is True

    def test_single_id_allows_matching_chat(self):
        """A single configured chat id is allowed."""
        assert is_chat_allowed(111000111, "111000111") is True

    def test_single_id_rejects_other_chat(self):
        """A chat id not in the allowlist is rejected."""
        assert is_chat_allowed(123, "111000111") is False

    def test_comma_separated_list_allows_any_listed_id(self):
        """Any chat id present in a comma-separated allowlist is allowed."""
        assert is_chat_allowed(123, "111000111,123,456") is True
        assert is_chat_allowed(456, "111000111,123,456") is True

    def test_comma_separated_list_rejects_unlisted_id(self):
        """A chat id absent from a comma-separated allowlist is rejected."""
        assert is_chat_allowed(789, "111000111,123,456") is False

    def test_whitespace_around_ids_is_ignored(self):
        """Whitespace around ids/commas in the allowlist is stripped before comparison."""
        assert is_chat_allowed(111000111, " 111000111 , 123 ") is True
        assert is_chat_allowed(123, " 111000111 , 123 ") is True


class TestParseScriptCommand:
    """parse_script_command extracts the idea title from /script <title> (D049)."""

    def test_parses_idea_title(self):
        """A normal /script <title> command returns the idea title text."""
        assert parse_script_command("/script Why starter homes vanished") == "Why starter homes vanished"

    def test_strips_surrounding_whitespace(self):
        """Leading/trailing whitespace is stripped from the command and title."""
        assert parse_script_command("  /script   some title  ") == "some title"

    def test_bare_command_returns_empty_string(self):
        """/script with no title returns an empty string (distinct from 'not a match')."""
        assert parse_script_command("/script") == ""

    def test_unrelated_text_returns_none(self):
        """Text that is not a /script command returns None."""
        assert parse_script_command("hello there") is None

    def test_other_slash_command_returns_none(self):
        """A different slash command is not mistaken for /script."""
        assert parse_script_command("/ideas niche") is None


class TestScriptFormatters:
    """format_script_*() helpers for the /script command (D049, P5-S5)."""

    def _make_artifact(self, script: str = "Test script text.") -> object:
        from datetime import datetime, timezone

        from cf_platform.workers.script_packager import ScriptArtifact

        return ScriptArtifact(
            idea_title="Why Starter Homes Vanished",
            niche="US housing",
            script=script,
            draft_number=1,
            overall_score=8.5,
            generated_at=datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_format_script_reply_contains_title(self):
        """The reply includes the idea title."""
        reply = format_script_reply(self._make_artifact())
        assert "Why Starter Homes Vanished" in reply

    def test_format_script_reply_contains_score(self):
        """The reply includes the quality score."""
        reply = format_script_reply(self._make_artifact())
        assert "8.5" in reply

    def test_format_script_reply_contains_script_text(self):
        """The reply includes the script text itself."""
        reply = format_script_reply(self._make_artifact(script="Specific script content."))
        assert "Specific script content." in reply

    def test_format_script_running_contains_title(self):
        """The running ack includes the idea title."""
        reply = format_script_running("Why Starter Homes Vanished")
        assert "Why Starter Homes Vanished" in reply

    def test_format_script_usage_mentions_command(self):
        """The usage reply mentions the /script command."""
        assert "/script" in format_script_usage()

    def test_format_unrecognized_command_mentions_script(self):
        """The unrecognized-command reply now mentions /script as well as /ideas."""
        reply = format_unrecognized_command("gibberish")
        assert "/script" in reply


class TestTelegramClient:
    """TelegramClient is a thin httpx wrapper over the Telegram Bot API (D049 — no SDK)."""

    @pytest.mark.asyncio
    async def test_send_message_noop_when_token_empty(self):
        """send_message no-ops when bot_token is empty — never raises, never calls httpx."""
        client = TelegramClient(bot_token="")

        with patch("httpx.AsyncClient") as mock_async_client:
            await client.send_message(chat_id=123, text="hello")

        mock_async_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_posts_to_telegram_api(self):
        """send_message POSTs chat_id + text to the sendMessage endpoint."""
        client = TelegramClient(bot_token="test-bot-token")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post = AsyncMock(return_value=mock_response)
        mock_client_instance = MagicMock()
        mock_client_instance.post = mock_post
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            await client.send_message(chat_id=123, text="hello")

        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args
        assert "test-bot-token" in url[0]
        assert "/sendMessage" in url[0]
        assert kwargs["json"] == {"chat_id": 123, "text": "hello"}
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_webhook_posts_url_and_secret(self):
        """register_webhook POSTs the webhook URL + secret token to setWebhook."""
        client = TelegramClient(bot_token="test-bot-token")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_post = AsyncMock(return_value=mock_response)
        mock_client_instance = MagicMock()
        mock_client_instance.post = mock_post
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            result = await client.register_webhook(
                webhook_url="https://example.com/platform/telegram/webhook",
                secret_token="shh",
            )

        mock_post.assert_awaited_once()
        url, kwargs = mock_post.call_args
        assert "/setWebhook" in url[0]
        assert kwargs["json"] == {
            "url": "https://example.com/platform/telegram/webhook",
            "secret_token": "shh",
        }
        assert result == {"ok": True}
