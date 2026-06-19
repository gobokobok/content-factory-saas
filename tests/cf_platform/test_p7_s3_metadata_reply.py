"""Tests for P7-S3 — Produce → metadata reply.

Covers:
  - format_youtube_metadata_block: formats title, description, tags correctly
  - format_produce_reply: backward compat without metadata; metadata block appended when present
  - _run_pipeline_and_reply: reads youtube_metadata artifact and includes in reply
  - _run_pipeline_and_reply: graceful when youtube_metadata absent from result
  - _run_pipeline_and_reply: graceful when youtube_metadata read raises an exception
"""

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.interfaces.telegram import (
    format_produce_reply,
    format_youtube_metadata_block,
)
from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

_RUN_ID = "run-p7s3-test"
_VIDEO_KEY = f"runs/{_RUN_ID}/output/final.mp4"
_VIDEO_URL = f"https://r2.example.com/{_VIDEO_KEY}?sig=x"
_META_KEY = f"runs/{_RUN_ID}/youtube_metadata/youtube_metadata@v1.json"
_IDEA_TITLE = "Why Starter Homes Vanished"


def _make_metadata(
    title: str = "Why Starter Homes Vanished in America",
    description: str = "Starter homes once made up 40% of the market. Now they're almost gone. #Housing #RealEstate",
    tags: Optional[list] = None,
) -> YoutubeMetadataArtifact:
    """Build a YoutubeMetadataArtifact for tests."""
    return YoutubeMetadataArtifact(
        title=title,
        description=description,
        tags=tags or ["housing", "real estate", "starter homes"],
        generated_at=datetime.now(timezone.utc),
    )


def _make_mock_settings() -> MagicMock:
    """Return a minimal PlatformSettings mock for _run_pipeline_and_reply."""
    settings = MagicMock()
    settings.TELEGRAM_BOT_TOKEN = "test-token"
    settings.ANTHROPIC_API_KEY = "test-key"
    settings.GEMINI_API_KEY = "gkey"
    settings.GEMINI_TTS_VOICE = "Kore"
    settings.DEEPGRAM_API_KEY = ""
    return settings


def _make_result_state(
    video_key: str = _VIDEO_KEY,
    meta_key: Optional[str] = _META_KEY,
) -> MagicMock:
    """Return a mock run_graph result with the given artifact keys."""
    state = MagicMock()
    state.artifacts = {"video": video_key}
    if meta_key is not None:
        state.artifacts["youtube_metadata"] = meta_key
    return state


# ── format_youtube_metadata_block ─────────────────────────────────────────────


def test_format_youtube_metadata_block_contains_title() -> None:
    """Formatted block includes the title."""
    metadata = _make_metadata(title="Why Starter Homes Vanished in America")
    text = format_youtube_metadata_block(metadata)
    assert "Why Starter Homes Vanished in America" in text


def test_format_youtube_metadata_block_contains_description() -> None:
    """Formatted block includes the description."""
    metadata = _make_metadata(description="A data-driven look at housing costs. #Housing")
    text = format_youtube_metadata_block(metadata)
    assert "A data-driven look at housing costs. #Housing" in text


def test_format_youtube_metadata_block_tags_comma_separated() -> None:
    """Tags are joined as a comma-separated line."""
    metadata = _make_metadata(tags=["housing", "real estate", "starter homes"])
    text = format_youtube_metadata_block(metadata)
    assert "housing, real estate, starter homes" in text


def test_format_youtube_metadata_block_section_header_present() -> None:
    """Formatted block includes a YouTube Metadata section header."""
    text = format_youtube_metadata_block(_make_metadata())
    assert "YouTube Metadata" in text


# ── format_produce_reply ──────────────────────────────────────────────────────


def test_format_produce_reply_without_metadata_backward_compat() -> None:
    """format_produce_reply without metadata is unchanged from P7-S1 (backward compat)."""
    text = format_produce_reply(_IDEA_TITLE, _RUN_ID, _VIDEO_URL)
    assert _IDEA_TITLE in text
    assert _RUN_ID in text
    assert _VIDEO_URL in text
    assert "YouTube" not in text


def test_format_produce_reply_none_metadata_same_as_no_arg() -> None:
    """Explicitly passing metadata=None produces the same output as omitting it."""
    without = format_produce_reply(_IDEA_TITLE, _RUN_ID, _VIDEO_URL)
    with_none = format_produce_reply(_IDEA_TITLE, _RUN_ID, _VIDEO_URL, metadata=None)
    assert without == with_none


def test_format_produce_reply_with_metadata_appends_block() -> None:
    """format_produce_reply with metadata appends the YouTube metadata block."""
    metadata = _make_metadata()
    text = format_produce_reply(_IDEA_TITLE, _RUN_ID, _VIDEO_URL, metadata=metadata)
    assert _VIDEO_URL in text
    assert metadata.title in text
    assert metadata.description in text
    assert "YouTube Metadata" in text


def test_format_produce_reply_with_metadata_still_contains_video_info() -> None:
    """Video URL and run_id remain present when metadata block is appended."""
    text = format_produce_reply(_IDEA_TITLE, _RUN_ID, _VIDEO_URL, metadata=_make_metadata())
    assert _RUN_ID in text
    assert _VIDEO_URL in text


# ── _run_pipeline_and_reply ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_pipeline_and_reply_with_metadata_includes_title_in_reply() -> None:
    """_run_pipeline_and_reply includes the YouTube title in the reply when metadata is present."""
    from cf_platform.interfaces.api import _run_pipeline_and_reply

    metadata = _make_metadata(title="Why Starter Homes Vanished — 40% Fewer Listings")
    result_state = _make_result_state()
    sent_messages: list[str] = []

    mock_storage = MagicMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value=_VIDEO_URL)

    async def fake_run_graph(graph: Any, state: Any, *, thread_id: str, **kwargs: Any) -> Any:
        return result_state

    async def fake_read_artifact(storage: Any, key: str) -> tuple:
        return (key, metadata.model_dump(mode="json"))

    fake_run = MagicMock()
    fake_run.run_id = _RUN_ID

    with (
        patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=MagicMock()),
        patch("cf_platform.interfaces.api.run_graph", side_effect=fake_run_graph),
        patch("cf_platform.interfaces.api.read_artifact", side_effect=fake_read_artifact),
        patch("cf_platform.interfaces.api.create_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.transition_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pipeline_and_reply(
            chat_id=42,
            display_label=_IDEA_TITLE,
            settings=_make_mock_settings(),
            adapters=[],
            storage=mock_storage,
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=MagicMock(),
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
            idea_title=_IDEA_TITLE,
        )

    assert len(sent_messages) == 1
    assert metadata.title in sent_messages[0]
    assert _VIDEO_URL in sent_messages[0]


@pytest.mark.asyncio
async def test_run_pipeline_and_reply_without_metadata_sends_video_url_only() -> None:
    """_run_pipeline_and_reply sends video URL only when youtube_metadata is absent from result."""
    from cf_platform.interfaces.api import _run_pipeline_and_reply

    result_state = _make_result_state(meta_key=None)
    sent_messages: list[str] = []

    mock_storage = MagicMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value=_VIDEO_URL)

    async def fake_run_graph(graph: Any, state: Any, *, thread_id: str, **kwargs: Any) -> Any:
        return result_state

    fake_run = MagicMock()
    fake_run.run_id = _RUN_ID

    with (
        patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=MagicMock()),
        patch("cf_platform.interfaces.api.run_graph", side_effect=fake_run_graph),
        patch("cf_platform.interfaces.api.create_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.transition_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pipeline_and_reply(
            chat_id=42,
            display_label=_IDEA_TITLE,
            settings=_make_mock_settings(),
            adapters=[],
            storage=mock_storage,
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=MagicMock(),
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
            idea_title=_IDEA_TITLE,
        )

    assert len(sent_messages) == 1
    assert _VIDEO_URL in sent_messages[0]
    assert "YouTube Metadata" not in sent_messages[0]


@pytest.mark.asyncio
async def test_run_pipeline_and_reply_metadata_read_error_falls_back_to_video_only() -> None:
    """_run_pipeline_and_reply falls back to video URL only when the metadata artifact read fails."""
    from cf_platform.interfaces.api import _run_pipeline_and_reply

    result_state = _make_result_state()  # has meta_key
    sent_messages: list[str] = []

    mock_storage = MagicMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value=_VIDEO_URL)

    async def fake_run_graph(graph: Any, state: Any, *, thread_id: str, **kwargs: Any) -> Any:
        return result_state

    async def failing_read_artifact(storage: Any, key: str) -> tuple:
        raise RuntimeError("R2 read timeout")

    fake_run = MagicMock()
    fake_run.run_id = _RUN_ID

    with (
        patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=MagicMock()),
        patch("cf_platform.interfaces.api.run_graph", side_effect=fake_run_graph),
        patch("cf_platform.interfaces.api.read_artifact", side_effect=failing_read_artifact),
        patch("cf_platform.interfaces.api.create_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.transition_run", new_callable=AsyncMock, return_value=fake_run),
        patch("cf_platform.interfaces.api.TelegramClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.send_message = AsyncMock(side_effect=lambda cid, t: sent_messages.append(t))
        mock_client_cls.return_value = mock_client

        await _run_pipeline_and_reply(
            chat_id=42,
            display_label=_IDEA_TITLE,
            settings=_make_mock_settings(),
            adapters=[],
            storage=mock_storage,
            registry=MagicMock(),
            runs=MagicMock(),
            executions=MagicMock(),
            artifacts=MagicMock(),
            trace_events=MagicMock(),
            checkpointer=MagicMock(),
            idea_title=_IDEA_TITLE,
        )

    assert len(sent_messages) == 1
    assert _VIDEO_URL in sent_messages[0]
    assert "YouTube Metadata" not in sent_messages[0]
