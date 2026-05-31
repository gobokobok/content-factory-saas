"""Tests for src/tts.py and the POST /runs/{run_id}/tts route."""

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import TTSError
from src.main import app
from src.tts import _encode_pcm_to_mp3, generate_tts, split_into_chunks

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
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
    "ELEVENLABS_API_KEY": "test-xi-key",
    "ELEVENLABS_VOICE_ID": "test-voice-id",
}

RUN_ID = "2026-05-31_test-tts"

_FAKE_PCM = b"\x00\x01" * 1000
_FAKE_MP3 = b"\xff\xfb" + b"\x00" * 200


@pytest.fixture
def settings():
    """Settings with ElevenLabs vars set."""
    return Settings(**VALID_ENV)


@pytest.fixture
def settings_no_xi():
    """Settings without ElevenLabs credentials."""
    env = {**VALID_ENV, "ELEVENLABS_API_KEY": "", "ELEVENLABS_VOICE_ID": ""}
    return Settings(**env)


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _mock_storage(
    script_content: bytes = b"Hello world. This is a test script.",
    script_missing: bool = False,
    upload_ok: bool = True,
):
    """Return a configured R2Client mock."""
    mock = MagicMock()
    if script_missing:
        from src.exceptions import StorageError
        mock.get_bytes.side_effect = StorageError("not found")
    else:
        mock.get_bytes.return_value = script_content
    mock.list_keys.return_value = []
    mock.upload_bytes.return_value = None
    mock._client.delete_object.return_value = {}
    mock._bucket = "test-bucket"
    return mock


# ── split_into_chunks unit tests ──────────────────────────────────────────────


class TestSplitIntoChunks:
    def test_single_sentence_below_limit(self):
        result = split_into_chunks("Hello world.", target_chars=1000)
        assert result == ["Hello world."]

    def test_empty_string_returns_empty(self):
        assert split_into_chunks("") == []

    def test_whitespace_only_returns_empty(self):
        assert split_into_chunks("   ") == []

    def test_merges_short_sentences_into_one_chunk(self):
        script = "Hi there. How are you? I am fine."
        result = split_into_chunks(script, target_chars=1000)
        assert len(result) == 1
        assert "Hi there" in result[0]

    def test_splits_at_sentence_boundary_when_over_limit(self):
        # Two sentences each ~60 chars; target 80 so they must split
        s1 = "The housing market is very complex and hard to predict."  # 55 chars
        s2 = "Prices have risen dramatically in many cities since 2020."  # 57 chars
        result = split_into_chunks(f"{s1} {s2}", target_chars=60)
        assert len(result) == 2
        assert s1 in result[0]
        assert s2 in result[1]

    def test_exclamation_and_question_marks_act_as_boundaries(self):
        script = "Wow! Really? Yes indeed."
        result = split_into_chunks(script, target_chars=5)
        assert len(result) == 3

    def test_single_long_sentence_not_split(self):
        long = "a " * 600  # 1200 chars, no sentence boundary
        result = split_into_chunks(long.strip(), target_chars=100)
        assert len(result) == 1

    def test_returns_list_of_non_empty_strings(self):
        result = split_into_chunks("One. Two. Three.", target_chars=1000)
        assert all(isinstance(s, str) and s for s in result)


# ── _encode_pcm_to_mp3 unit tests ─────────────────────────────────────────────


class TestEncodePcmToMp3:
    def test_returns_bytes_on_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=_FAKE_MP3, stderr=b"")
            result = _encode_pcm_to_mp3(_FAKE_PCM)
        assert result == _FAKE_MP3

    def test_raises_tts_error_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout=b"", stderr=b"some ffmpeg error"
            )
            with pytest.raises(TTSError, match="ffmpeg exited 1"):
                _encode_pcm_to_mp3(_FAKE_PCM)

    def test_raises_tts_error_when_ffmpeg_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(TTSError, match="ffmpeg not found"):
                _encode_pcm_to_mp3(_FAKE_PCM)

    def test_raises_tts_error_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 120)):
            with pytest.raises(TTSError, match="timed out"):
                _encode_pcm_to_mp3(_FAKE_PCM)


# ── generate_tts unit tests ───────────────────────────────────────────────────


class TestGenerateTts:
    @pytest.mark.asyncio
    async def test_returns_mp3_bytes_and_chunk_count(self):
        script = "Hello world. Second sentence."
        with (
            patch("src.tts._call_elevenlabs", new_callable=AsyncMock, return_value=_FAKE_PCM),
            patch("src.tts._encode_pcm_to_mp3", return_value=_FAKE_MP3),
        ):
            mp3, chunk_count = await generate_tts(script, "key", "voice")
        assert mp3 == _FAKE_MP3
        assert chunk_count >= 1

    @pytest.mark.asyncio
    async def test_raises_tts_error_on_empty_script(self):
        with pytest.raises(TTSError, match="empty"):
            await generate_tts("", "key", "voice")

    @pytest.mark.asyncio
    async def test_raises_tts_error_when_elevenlabs_fails(self):
        with patch(
            "src.tts._call_elevenlabs",
            new_callable=AsyncMock,
            side_effect=TTSError("API error"),
        ):
            with pytest.raises(TTSError, match="API error"):
                await generate_tts("Hello world.", "key", "voice")

    @pytest.mark.asyncio
    async def test_previous_text_not_set_for_first_chunk(self):
        calls = []

        async def _capture(text, api_key, voice_id, previous_text, next_text, **kw):
            calls.append({"text": text, "prev": previous_text, "next": next_text})
            return _FAKE_PCM

        script = "First. Second. Third."
        with (
            patch("src.tts._call_elevenlabs", side_effect=_capture),
            patch("src.tts._encode_pcm_to_mp3", return_value=_FAKE_MP3),
        ):
            await generate_tts(script, "k", "v")

        assert calls[0]["prev"] is None

    @pytest.mark.asyncio
    async def test_next_text_not_set_for_last_chunk(self):
        calls = []

        async def _capture(text, api_key, voice_id, previous_text, next_text, **kw):
            calls.append({"text": text, "prev": previous_text, "next": next_text})
            return _FAKE_PCM

        # Force 2 chunks by using a tiny target_chars
        import src.tts as tts_mod
        original = tts_mod._TARGET_CHUNK_CHARS
        tts_mod._TARGET_CHUNK_CHARS = 10
        try:
            with (
                patch("src.tts._call_elevenlabs", side_effect=_capture),
                patch("src.tts._encode_pcm_to_mp3", return_value=_FAKE_MP3),
            ):
                await generate_tts("First sentence. Second sentence.", "k", "v")
        finally:
            tts_mod._TARGET_CHUNK_CHARS = original

        assert calls[-1]["next"] is None


# ── Route integration tests ───────────────────────────────────────────────────


class TestTtsRoute:
    def test_returns_503_when_api_key_missing(self, settings_no_xi):
        app.dependency_overrides[get_settings] = lambda: settings_no_xi
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post(f"/runs/{RUN_ID}/tts")
        app.dependency_overrides.clear()
        assert resp.status_code == 503

    def test_returns_404_when_script_missing(self, client):
        storage = _mock_storage(script_missing=True)
        with patch("src.routes.tts._make_r2_client", return_value=storage):
            resp = client.post(f"/runs/{RUN_ID}/tts")
        assert resp.status_code == 404
        assert "script.txt" in resp.json()["detail"]

    def test_returns_422_when_script_empty(self, client):
        storage = _mock_storage(script_content=b"   ")
        with patch("src.routes.tts._make_r2_client", return_value=storage):
            resp = client.post(f"/runs/{RUN_ID}/tts")
        assert resp.status_code == 422

    def test_returns_502_when_elevenlabs_fails(self, client):
        storage = _mock_storage()
        with (
            patch("src.routes.tts._make_r2_client", return_value=storage),
            patch(
                "src.routes.tts.generate_tts",
                new_callable=AsyncMock,
                side_effect=TTSError("upstream error"),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/tts")
        assert resp.status_code == 502
        assert "TTS generation failed" in resp.json()["detail"]

    def test_returns_200_on_success(self, client):
        storage = _mock_storage()
        with (
            patch("src.routes.tts._make_r2_client", return_value=storage),
            patch(
                "src.routes.tts.generate_tts",
                new_callable=AsyncMock,
                return_value=(_FAKE_MP3, 2),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/tts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert data["chunk_count"] == 2
        assert "voiceover/generated.mp3" in data["key"]

    def test_uploads_generated_mp3_on_success(self, client):
        storage = _mock_storage()
        with (
            patch("src.routes.tts._make_r2_client", return_value=storage),
            patch(
                "src.routes.tts.generate_tts",
                new_callable=AsyncMock,
                return_value=(_FAKE_MP3, 1),
            ),
        ):
            client.post(f"/runs/{RUN_ID}/tts")

        storage.upload_bytes.assert_called_once()
        call_args = storage.upload_bytes.call_args
        assert call_args[0][0] == f"runs/{RUN_ID}/voiceover/generated.mp3"
        assert call_args[0][1] == _FAKE_MP3
        assert call_args[1].get("content_type") == "audio/mpeg"

    def test_purges_existing_voiceover_on_success(self, client):
        existing_key = f"runs/{RUN_ID}/voiceover/old_upload.mp3"
        storage = _mock_storage()
        storage.list_keys.return_value = [existing_key]

        with (
            patch("src.routes.tts._make_r2_client", return_value=storage),
            patch(
                "src.routes.tts.generate_tts",
                new_callable=AsyncMock,
                return_value=(_FAKE_MP3, 1),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/tts")

        assert resp.status_code == 200
        storage._client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key=existing_key
        )

    def test_existing_upload_not_purged_when_tts_fails(self, client):
        existing_key = f"runs/{RUN_ID}/voiceover/uploaded.mp3"
        storage = _mock_storage()
        storage.list_keys.return_value = [existing_key]

        with (
            patch("src.routes.tts._make_r2_client", return_value=storage),
            patch(
                "src.routes.tts.generate_tts",
                new_callable=AsyncMock,
                side_effect=TTSError("fail"),
            ),
        ):
            resp = client.post(f"/runs/{RUN_ID}/tts")

        assert resp.status_code == 502
        # delete_object must NOT have been called
        storage._client.delete_object.assert_not_called()
