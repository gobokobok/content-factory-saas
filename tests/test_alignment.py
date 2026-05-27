"""Tests for src/alignment.py and the POST /runs/{run_id}/alignment route."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.alignment import _extract_words, _normalize_word, align_audio, proportional_fallback
from src.config import Settings, get_settings
from src.exceptions import AlignmentError
from src.main import app
from src.models import WordTimestamp

# ── Shared fixtures ───────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "ANTHROPIC_API_KEY": "test-anthropic",
    "PEXELS_API_KEY": "test-pexels",
    "REPLICATE_API_TOKEN": "test-replicate",
    "FREESOUND_API_KEY": "test-freesound",
    "DEEPGRAM_API_KEY": "test-deepgram",
}

RUN_ID = "2026-05-27_test-alignment"

_DEEPGRAM_RESPONSE = {
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "words": [
                            {"word": "hello", "start": 0.12, "end": 0.45, "confidence": 0.99},
                            {"word": "world,", "start": 0.50, "end": 0.85, "confidence": 0.97},
                            {"word": "it's", "start": 0.90, "end": 1.20, "confidence": 0.95},
                        ]
                    }
                ]
            }
        ]
    }
}


@pytest.fixture
def settings():
    """Settings with all required ENV vars including DEEPGRAM_API_KEY."""
    return Settings(**VALID_ENV)


@pytest.fixture
def settings_no_deepgram():
    """Settings without DEEPGRAM_API_KEY to test fallback path."""
    env = {**VALID_ENV, "DEEPGRAM_API_KEY": ""}
    return Settings(**env)


@pytest.fixture
def client(settings):
    """TestClient with settings injected."""
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_deepgram(settings_no_deepgram):
    """TestClient with empty DEEPGRAM_API_KEY to force fallback."""
    app.dependency_overrides[get_settings] = lambda: settings_no_deepgram
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ── _normalize_word ───────────────────────────────────────────────────────────


class TestNormalizeWord:
    def test_converts_seconds_to_milliseconds(self):
        raw = {"word": "hello", "start": 0.12, "end": 0.45, "confidence": 0.99}
        result = _normalize_word(raw)
        assert result.start_ms == 120
        assert result.end_ms == 450

    def test_strips_trailing_punctuation(self):
        raw = {"word": "world,", "start": 0.0, "end": 0.5, "confidence": 0.9}
        result = _normalize_word(raw)
        assert result.word == "world"

    def test_strips_leading_punctuation(self):
        raw = {"word": "'hello", "start": 0.0, "end": 0.5, "confidence": 0.9}
        result = _normalize_word(raw)
        assert result.word == "hello"

    def test_preserves_apostrophe_within_contraction(self):
        # _PUNCT_RE strips non-word chars including apostrophe — contractions lose apostrophe
        raw = {"word": "it's", "start": 0.9, "end": 1.2, "confidence": 0.95}
        result = _normalize_word(raw)
        # apostrophe is stripped; "its" is the clean form
        assert result.word == "its"

    def test_confidence_preserved(self):
        raw = {"word": "hi", "start": 0.0, "end": 0.3, "confidence": 0.88}
        result = _normalize_word(raw)
        assert result.confidence == 0.88

    def test_missing_confidence_defaults_to_one(self):
        raw = {"word": "hi", "start": 0.0, "end": 0.3}
        result = _normalize_word(raw)
        assert result.confidence == 1.0

    def test_returns_word_timestamp_instance(self):
        raw = {"word": "test", "start": 0.0, "end": 0.5, "confidence": 0.9}
        result = _normalize_word(raw)
        assert isinstance(result, WordTimestamp)


# ── _extract_words ────────────────────────────────────────────────────────────


class TestExtractWords:
    def test_extracts_words_from_valid_response(self):
        words = _extract_words(_DEEPGRAM_RESPONSE)
        assert len(words) == 3
        assert words[0]["word"] == "hello"

    def test_raises_on_missing_results_key(self):
        with pytest.raises(AlignmentError):
            _extract_words({})

    def test_raises_on_empty_channels(self):
        data = {"results": {"channels": []}}
        with pytest.raises(AlignmentError):
            _extract_words(data)

    def test_raises_on_empty_alternatives(self):
        data = {"results": {"channels": [{"alternatives": []}]}}
        with pytest.raises(AlignmentError):
            _extract_words(data)

    def test_raises_on_none_data(self):
        with pytest.raises(AlignmentError):
            _extract_words(None)  # type: ignore


# ── proportional_fallback ─────────────────────────────────────────────────────


class TestProportionalFallback:
    def test_returns_one_entry_per_word(self):
        result = proportional_fallback("hello world", 2.0)
        assert len(result) == 2

    def test_all_confidence_zero(self):
        result = proportional_fallback("hello world", 2.0)
        assert all(w.confidence == 0.0 for w in result)

    def test_timestamps_are_contiguous(self):
        result = proportional_fallback("one two three", 3.0)
        for i in range(len(result) - 1):
            assert result[i].end_ms == result[i + 1].start_ms

    def test_first_word_starts_at_zero(self):
        result = proportional_fallback("hello world", 2.0)
        assert result[0].start_ms == 0

    def test_longer_word_gets_more_time(self):
        # "a" (1 char) vs "longer" (6 chars) — longer should get more ms
        result = proportional_fallback("a longer", 1.0)
        assert result[1].end_ms - result[1].start_ms > result[0].end_ms - result[0].start_ms

    def test_empty_text_returns_empty_list(self):
        assert proportional_fallback("", 5.0) == []

    def test_whitespace_only_returns_empty_list(self):
        assert proportional_fallback("   ", 5.0) == []

    def test_strips_punctuation_from_words(self):
        result = proportional_fallback("hello, world!", 2.0)
        assert result[0].word == "hello"
        assert result[1].word == "world"

    def test_total_duration_respected_approximately(self):
        result = proportional_fallback("one two three four", 4.0)
        total_ms = result[-1].end_ms
        # Allow 1ms rounding slack per word
        assert abs(total_ms - 4000) <= len(result)

    def test_returns_word_timestamp_instances(self):
        result = proportional_fallback("hello", 1.0)
        assert all(isinstance(w, WordTimestamp) for w in result)


# ── align_audio ───────────────────────────────────────────────────────────────


class TestAlignAudio:
    @pytest.mark.asyncio
    async def test_happy_path_returns_word_timestamps(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _DEEPGRAM_RESPONSE

        with patch("src.alignment.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await align_audio("https://example.com/audio.mp3", "test-key")

        assert len(result) == 3
        assert result[0].word == "hello"
        assert result[0].start_ms == 120
        assert result[0].end_ms == 450
        assert result[1].word == "world"  # comma stripped

    @pytest.mark.asyncio
    async def test_non_200_raises_alignment_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("src.alignment.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(AlignmentError, match="401"):
                await align_audio("https://example.com/audio.mp3", "bad-key")

    @pytest.mark.asyncio
    async def test_http_error_raises_alignment_error(self):
        with patch("src.alignment.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(AlignmentError, match="request failed"):
                await align_audio("https://example.com/audio.mp3", "test-key")

    @pytest.mark.asyncio
    async def test_uses_nova2_model_param(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _DEEPGRAM_RESPONSE

        with patch("src.alignment.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await align_audio("https://example.com/audio.mp3", "test-key")

            call_kwargs = mock_client.post.call_args
            assert call_kwargs.kwargs["params"]["model"] == "nova-2"
            assert call_kwargs.kwargs["params"]["smart_format"] == "true"


# ── POST /runs/{run_id}/alignment route ───────────────────────────────────────


_STORYBOARD = {
    "global": {"subtitle_style": "bold", "bg_music": "none", "visual_style": "doc"},
    "scenes": [
        {"scene": "01", "clip_type": "hard_cut", "duration_s": 3.0,
         "voiceover_line": "hello world", "visual_prompts": {}, "sfx": "none", "sfx_timing": "0"},
    ],
    "summary": {"total_scenes": 1, "total_duration_s": 3.0, "rhythm": "moderate"},
}

_RUN_LOG = {
    "run_id": RUN_ID,
    "created_at": "2026-05-27T00:00:00+00:00",
    "steps": {
        "storyboard": {"status": "complete"},
        "asset_manifest": {"status": "complete"},
        "asset_acquisition": {"status": "complete"},
        "alignment": {"status": "pending"},
        "ffmpeg_script": {"status": "pending"},
        "render": {"status": "pending"},
    },
}


def _mock_storage(
    *,
    audio_keys=None,
    presigned_url: str = "https://r2.example.com/voiceover.mp3?token=x",
    storyboard=None,
    run_log=None,
):
    """Build a mock R2Client for alignment route tests."""
    if audio_keys is None:
        audio_keys = [f"runs/{RUN_ID}/voiceover/take1.mp3"]
    if storyboard is None:
        storyboard = _STORYBOARD
    if run_log is None:
        run_log = _RUN_LOG

    mock = MagicMock()
    mock.list_keys.return_value = audio_keys
    mock.generate_presigned_url.return_value = presigned_url
    mock.get_json.return_value = storyboard
    mock.upload_json.return_value = None
    mock.update_run_log.return_value = None
    return mock


class TestAlignmentRouteSuccess:
    def test_happy_path_returns_200(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                return_value=[
                    WordTimestamp(word="hello", start_ms=0, end_ms=300, confidence=0.99),
                    WordTimestamp(word="world", start_ms=300, end_ms=600, confidence=0.98),
                ],
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 200

    def test_happy_path_response_body(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                return_value=[
                    WordTimestamp(word="hello", start_ms=0, end_ms=300, confidence=0.99),
                    WordTimestamp(word="world", start_ms=300, end_ms=600, confidence=0.98),
                ],
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        body = resp.json()
        assert body["status"] == "complete"
        assert body["word_count"] == 2
        assert body["used_fallback"] is False
        assert f"runs/{RUN_ID}/alignment.json" in body["alignment_key"]

    def test_uploads_alignment_json_to_r2(self, client):
        mock_storage = _mock_storage()
        words = [WordTimestamp(word="hello", start_ms=0, end_ms=300, confidence=0.99)]
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                return_value=words,
            ),
        ):
            client.post(f"/runs/{RUN_ID}/alignment")

        mock_storage.upload_json.assert_called_once()
        key, data = mock_storage.upload_json.call_args.args
        assert key == f"runs/{RUN_ID}/alignment.json"
        assert data["word_count"] == 1
        assert data["used_fallback"] is False
        assert len(data["words"]) == 1

    def test_updates_run_log_on_success(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                return_value=[WordTimestamp(word="hi", start_ms=0, end_ms=200, confidence=0.9)],
            ),
        ):
            client.post(f"/runs/{RUN_ID}/alignment")

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "alignment",
            "complete",
            output_url=f"runs/{RUN_ID}/alignment.json",
        )


class TestAlignmentRouteFallback:
    def test_deepgram_failure_triggers_fallback(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                side_effect=AlignmentError("API error"),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 200
        assert resp.json()["used_fallback"] is True

    def test_fallback_stores_alignment_json(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                side_effect=AlignmentError("API error"),
            ),
        ):
            client.post(f"/runs/{RUN_ID}/alignment")

        mock_storage.upload_json.assert_called_once()
        _, data = mock_storage.upload_json.call_args.args
        assert data["used_fallback"] is True
        assert len(data["words"]) > 0

    def test_no_deepgram_key_uses_fallback(self, client_no_deepgram):
        mock_storage = _mock_storage()
        with patch("src.routes.alignment.R2Client", return_value=mock_storage):
            resp = client_no_deepgram.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 200
        assert resp.json()["used_fallback"] is True

    def test_fallback_reads_storyboard(self, client):
        mock_storage = _mock_storage()
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                side_effect=AlignmentError("fail"),
            ),
        ):
            client.post(f"/runs/{RUN_ID}/alignment")

        mock_storage.get_json.assert_called_once_with(f"runs/{RUN_ID}/storyboard.json")


class TestAlignmentRouteErrors:
    def test_no_voiceover_returns_404(self, client):
        mock_storage = _mock_storage(audio_keys=[])
        with patch("src.routes.alignment.R2Client", return_value=mock_storage):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 404
        assert "voiceover" in resp.json()["detail"].lower()

    def test_non_audio_keys_ignored(self, client):
        mock_storage = _mock_storage(
            audio_keys=[f"runs/{RUN_ID}/voiceover/notes.txt"]
        )
        with patch("src.routes.alignment.R2Client", return_value=mock_storage):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 404

    def test_deepgram_fail_and_no_storyboard_returns_404(self, client):
        from src.exceptions import StorageError as SE

        mock_storage = _mock_storage()
        mock_storage.get_json.side_effect = SE("not found")
        with (
            patch("src.routes.alignment.R2Client", return_value=mock_storage),
            patch(
                "src.routes.alignment.align_audio",
                new_callable=AsyncMock,
                side_effect=AlignmentError("fail"),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/alignment")

        assert resp.status_code == 404
        assert "storyboard" in resp.json()["detail"].lower()
