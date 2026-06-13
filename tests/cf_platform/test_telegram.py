"""Tests for cf_platform/interfaces/telegram.py (P3-S1, D049)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.interfaces.telegram import (
    TelegramClient,
    format_ideas_ack,
    format_ideas_usage,
    format_unrecognized_command,
    is_chat_allowed,
    parse_ideas_command,
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

    def test_format_ideas_ack_includes_niche(self):
        """The ack reply echoes back the requested niche."""
        reply = format_ideas_ack("starter homes")

        assert "starter homes" in reply
        assert isinstance(reply, str)

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
        assert is_chat_allowed(968448961, "") is True
        assert is_chat_allowed(123, "") is True

    def test_single_id_allows_matching_chat(self):
        """A single configured chat id is allowed."""
        assert is_chat_allowed(968448961, "968448961") is True

    def test_single_id_rejects_other_chat(self):
        """A chat id not in the allowlist is rejected."""
        assert is_chat_allowed(123, "968448961") is False

    def test_comma_separated_list_allows_any_listed_id(self):
        """Any chat id present in a comma-separated allowlist is allowed."""
        assert is_chat_allowed(123, "968448961,123,456") is True
        assert is_chat_allowed(456, "968448961,123,456") is True

    def test_comma_separated_list_rejects_unlisted_id(self):
        """A chat id absent from a comma-separated allowlist is rejected."""
        assert is_chat_allowed(789, "968448961,123,456") is False

    def test_whitespace_around_ids_is_ignored(self):
        """Whitespace around ids/commas in the allowlist is stripped before comparison."""
        assert is_chat_allowed(968448961, " 968448961 , 123 ") is True
        assert is_chat_allowed(123, " 968448961 , 123 ") is True


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
