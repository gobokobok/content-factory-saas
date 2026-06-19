"""Tests for cf_platform/workers/youtube_metadata.py (P7-S2)."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.youtube_metadata import (
    YOUTUBE_METADATA_REGISTRATION,
    YoutubeMetadataArtifact,
    _extract_json,
    build_youtube_metadata_worker,
)
from cf_platform.core.schemas import StageState

_RUN_ID = "run-p7s2-test"
_USER_ID = "operator"
_SCRIPT_R2 = "r2://script@v1.json"


def _make_script_body(
    script: str = "Housing prices hit a 40-year high last quarter.",
    idea_title: str = "Why You Cannot Afford a Starter Home",
    niche: str = "american housing",
) -> dict:
    """Build a ScriptArtifact-shaped dict for read_artifact mock returns."""
    return ScriptArtifact(
        idea_title=idea_title,
        niche=niche,
        script=script,
        word_count=len(script.split()),
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _make_state(niche: str = "american housing") -> StageState:
    """Build a StageState with script artifact ref and optional niche."""
    return StageState(
        run_id=_RUN_ID,
        user_id=_USER_ID,
        inputs={"niche": niche} if niche else {},
        artifacts={"script": _SCRIPT_R2},
    )


def _claude_response(title: str, description: str, tags: list[str]) -> MagicMock:
    """Build a mock Anthropic response object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps({"title": title, "description": description, "tags": tags}))]
    return msg


# ── _extract_json ─────────────────────────────────────────────────────────────


def test_extract_json_plain() -> None:
    """_extract_json parses a plain JSON string."""
    raw = '{"title": "T", "description": "D", "tags": ["a"]}'
    assert _extract_json(raw)["title"] == "T"


def test_extract_json_strips_markdown_fence() -> None:
    """_extract_json strips ```json ... ``` fences before parsing."""
    raw = '```json\n{"title": "T", "description": "D", "tags": []}\n```'
    assert _extract_json(raw)["title"] == "T"


def test_extract_json_raises_on_garbage() -> None:
    """_extract_json raises ValueError when no JSON object is present."""
    with pytest.raises(ValueError, match="Could not extract JSON"):
        _extract_json("this is just text, no JSON here at all")


# ── Registration pins ─────────────────────────────────────────────────────────


def test_registration_pins() -> None:
    """YOUTUBE_METADATA_REGISTRATION has expected worker_version and model."""
    assert YOUTUBE_METADATA_REGISTRATION.worker_version == "1.0.0"
    assert YOUTUBE_METADATA_REGISTRATION.prompt_version == "v1"
    assert "haiku" in YOUTUBE_METADATA_REGISTRATION.model


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_happy_path() -> None:
    """Worker reads script artifact, calls Haiku once, returns YoutubeMetadataArtifact."""
    title = "Why Starter Homes Vanished in 10 Years"
    description = "Starter homes now make up less than 10% of new builds. #HousingCrisis #RealEstate"
    tags = ["housing market", "starter homes", "real estate", "affordability"]

    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_claude_response(title, description, tags))

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        output = await worker(_make_state())

    assert isinstance(output.artifact, YoutubeMetadataArtifact)
    assert output.artifact.title == title
    assert output.artifact.description == description
    assert output.artifact.tags == tags
    assert output.control == "continue"
    mock_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_includes_niche_in_prompt() -> None:
    """Worker includes CHANNEL NICHE in the user message when niche is set."""
    captured_messages: list = []

    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()

    async def capture_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return _claude_response("T", "D", ["tag"])

    mock_client.messages.create = capture_create

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        await worker(_make_state(niche="american housing"))

    user_content = captured_messages[0]["content"]
    assert "CHANNEL NICHE: american housing" in user_content


@pytest.mark.asyncio
async def test_worker_no_niche_omits_niche_line() -> None:
    """Worker omits CHANNEL NICHE line when niche is empty."""
    captured_messages: list = []

    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()

    async def capture_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return _claude_response("T", "D", ["tag"])

    mock_client.messages.create = capture_create

    state = StageState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, artifacts={"script": _SCRIPT_R2})

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        await worker(state)

    user_content = captured_messages[0]["content"]
    assert "CHANNEL NICHE" not in user_content


# ── Constraint enforcement ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_title_truncated_at_70_chars() -> None:
    """Worker truncates title to 70 chars when Claude overshoots."""
    long_title = "A" * 100
    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_claude_response(long_title, "desc", ["tag"]))

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        output = await worker(_make_state())

    assert len(output.artifact.title) == 70


@pytest.mark.asyncio
async def test_description_truncated_at_500_chars() -> None:
    """Worker truncates description to 500 chars when Claude overshoots."""
    long_desc = "B" * 600
    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_claude_response("title", long_desc, ["tag"]))

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        output = await worker(_make_state())

    assert len(output.artifact.description) == 500


@pytest.mark.asyncio
async def test_tags_capped_at_15() -> None:
    """Worker caps tags list at 15 items when Claude returns more."""
    many_tags = [f"tag{i}" for i in range(25)]
    mock_storage = MagicMock()
    mock_read = AsyncMock(return_value=(MagicMock(), _make_script_body()))
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=_claude_response("title", "desc", many_tags))

    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", mock_read),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=mock_client),
    ):
        worker = build_youtube_metadata_worker(storage=mock_storage, anthropic_api_key="key")
        output = await worker(_make_state())

    assert len(output.artifact.tags) == 15
    assert output.artifact.tags == many_tags[:15]


# ── Missing script key ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_raises_on_missing_script_key() -> None:
    """Worker raises KeyError when the script artifact ref is absent from state."""
    state = StageState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, artifacts={})
    worker = build_youtube_metadata_worker(storage=MagicMock(), anthropic_api_key="key")
    with pytest.raises(KeyError):
        await worker(state)
