"""Tests for cf_platform/workers/voice_production.py (P6-S7).

Covers:
  - _proportional_fallback: character-count proportional timestamps
  - _estimate_duration: word-count-based duration
  - _normalize_word: Deepgram word dict → VoiceWordTimestamp
  - _call_gemini_tts_sync: Gemini SDK call (mocked)
  - build_voice_production_worker: integration — TTS, alignment, fallback paths
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.schemas import StageState
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.voice_production import (
    VoiceGenerationError,
    VoiceWordTimestamp,
    _estimate_duration,
    _normalize_word,
    _proportional_fallback,
    build_voice_production_worker,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_RUN_ID = "run-voice-test"
_USER_ID = "operator"
_SCRIPT = "Housing prices are soaring. Affordability is a crisis. What can we do?"
_SCRIPT_KEY = "r2://script@v1.json"


def _make_script_body(script: str = _SCRIPT) -> dict:
    return ScriptArtifact(
        idea_title="Housing Crisis", niche="american housing", script=script,
        word_count=len(script.split()), generated_at=datetime.now(UTC),
    ).model_dump(mode="json")


def _make_state(script_key: str = _SCRIPT_KEY) -> StageState:
    return StageState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, artifacts={"script": script_key})


# ── _proportional_fallback ─────────────────────────────────────────────────────


def test_proportional_fallback_returns_correct_word_count() -> None:
    """Fallback produces one VoiceWordTimestamp per word."""
    words = "one two three four five"
    result = _proportional_fallback(words, 5.0)
    assert len(result) == 5


def test_proportional_fallback_confidence_is_zero() -> None:
    """Fallback marks all timestamps as estimated (confidence=0.0)."""
    result = _proportional_fallback("hello world", 2.0)
    for ts in result:
        assert ts.confidence == 0.0


def test_proportional_fallback_timestamps_are_sequential() -> None:
    """Each word's start_ms matches the previous word's end_ms."""
    result = _proportional_fallback("a b c d", 4.0)
    for i in range(1, len(result)):
        assert result[i].start_ms == result[i - 1].end_ms


def test_proportional_fallback_covers_full_duration() -> None:
    """The last word's end_ms equals the total duration in milliseconds."""
    total_s = 10.0
    result = _proportional_fallback("hello world foo bar", total_s)
    # Allow ±10ms rounding tolerance
    assert abs(result[-1].end_ms - int(total_s * 1000)) <= 10


def test_proportional_fallback_empty_text_returns_empty() -> None:
    """Empty text returns an empty list."""
    assert _proportional_fallback("", 5.0) == []


def test_proportional_fallback_strips_punctuation() -> None:
    """Punctuation is stripped from words in the output."""
    result = _proportional_fallback("hello, world!", 2.0)
    assert result[0].word == "hello"
    assert result[1].word == "world"


# ── _estimate_duration ────────────────────────────────────────────────────────


def test_estimate_duration_proportional_to_word_count() -> None:
    """Longer scripts produce longer duration estimates."""
    short = "hello world"
    long = " ".join(["word"] * 100)
    assert _estimate_duration(long) > _estimate_duration(short)


def test_estimate_duration_minimum_one_second() -> None:
    """Single-word script returns at least 1.0 seconds."""
    assert _estimate_duration("hello") >= 1.0


def test_estimate_duration_empty_string() -> None:
    """Empty string returns the minimum duration (1.0s)."""
    assert _estimate_duration("") >= 1.0


# ── _normalize_word ───────────────────────────────────────────────────────────


def test_normalize_word_basic() -> None:
    """Converts a Deepgram word dict to a VoiceWordTimestamp."""
    raw = {"word": "hello", "start": 0.5, "end": 0.9, "confidence": 0.95}
    ts = _normalize_word(raw)
    assert ts.word == "hello"
    assert ts.start_ms == 500
    assert ts.end_ms == 900
    assert ts.confidence == pytest.approx(0.95)


def test_normalize_word_strips_punctuation() -> None:
    """Deepgram includes punctuation; _normalize_word strips it."""
    raw = {"word": "crisis,", "start": 1.0, "end": 1.3, "confidence": 0.9}
    ts = _normalize_word(raw)
    assert ts.word == "crisis"


def test_normalize_word_missing_confidence_defaults_to_one() -> None:
    """confidence defaults to 1.0 when absent from the Deepgram dict."""
    raw = {"word": "test", "start": 0.0, "end": 0.2}
    ts = _normalize_word(raw)
    assert ts.confidence == 1.0


# ── Gemini TTS path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_gemini_happy_path_calls_tts_and_alignment() -> None:
    """With Gemini + Deepgram keys, worker calls TTS, uploads MP3, and aligns."""
    fake_mp3 = b"FAKEMP3"
    fake_timestamps = [VoiceWordTimestamp(word="hello", start_ms=0, end_ms=300, confidence=0.99)]
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value="https://presigned.example/audio.mp3")
    state = _make_state()

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body("hello"))),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=fake_mp3)),
        patch("cf_platform.workers.voice_production._align_audio", AsyncMock(return_value=fake_timestamps)),
    ):
        worker = build_voice_production_worker(
            mock_storage,
            gemini_api_key="gemini-key",
            gemini_tts_voice="Kore",
            deepgram_api_key="dg-key",
        )
        result = await worker(state)

    artifact = result.artifact
    assert artifact.mp3_r2_key == f"runs/{_RUN_ID}/voiceover/generated.wav"
    assert artifact.alignment_method == "deepgram_nova2"
    assert artifact.word_timestamps == fake_timestamps
    mock_storage.put_bytes.assert_awaited_once_with(
        f"runs/{_RUN_ID}/voiceover/generated.wav", fake_mp3, "audio/wav"
    )


@pytest.mark.asyncio
async def test_worker_gemini_key_but_no_voice_fails_loudly() -> None:
    """A key without a TTS voice is a readable failure, never a silent no-audio result."""
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    state = _make_state()

    with patch(
        "cf_platform.workers.voice_production.read_artifact",
        AsyncMock(return_value=(MagicMock(), _make_script_body())),
    ):
        worker = build_voice_production_worker(mock_storage, gemini_api_key="key", gemini_tts_voice="")
        with pytest.raises(VoiceGenerationError, match="GEMINI_TTS_VOICE"):
            await worker(state)

    mock_storage.put_bytes.assert_not_awaited()


# ── build_voice_production_worker — no API keys (loud failure) ────────────────


@pytest.mark.asyncio
async def test_worker_no_keys_fails_loudly() -> None:
    """With no Gemini key the worker raises; it never returns a result with no audio."""
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    state = _make_state()

    with patch(
        "cf_platform.workers.voice_production.read_artifact",
        AsyncMock(return_value=(MagicMock(), _make_script_body())),
    ):
        worker = build_voice_production_worker(mock_storage)
        with pytest.raises(VoiceGenerationError, match="GEMINI_API_KEY"):
            await worker(state)

    mock_storage.put_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_happy_path_total_duration_from_last_word() -> None:
    """total_duration_s is derived from the last Deepgram word's end_ms."""
    fake_mp3 = b"MP3"
    last_end_ms = 12500
    fake_timestamps = [
        VoiceWordTimestamp(word="foo", start_ms=0, end_ms=500, confidence=0.9),
        VoiceWordTimestamp(word="bar", start_ms=500, end_ms=last_end_ms, confidence=0.9),
    ]
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value="https://presigned.example/audio.mp3")
    state = _make_state()

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body("foo bar"))),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=fake_mp3)),
        patch("cf_platform.workers.voice_production._align_audio", AsyncMock(return_value=fake_timestamps)),
    ):
        worker = build_voice_production_worker(
            mock_storage, gemini_api_key="k", gemini_tts_voice="v", deepgram_api_key="d"
        )
        result = await worker(state)

    assert result.artifact.total_duration_s == pytest.approx(last_end_ms / 1000)


# ── build_voice_production_worker — TTS failure is loud ───────────────────────


@pytest.mark.asyncio
async def test_worker_tts_failure_raises_readable_error() -> None:
    """When Gemini TTS raises, the worker raises VoiceGenerationError and writes nothing."""
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    state = _make_state()

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch(
            "cf_platform.workers.voice_production._tts_generate",
            AsyncMock(side_effect=RuntimeError("Gemini quota exceeded")),
        ),
    ):
        worker = build_voice_production_worker(
            mock_storage, gemini_api_key="gemini-key", gemini_tts_voice="Kore"
        )
        with pytest.raises(VoiceGenerationError) as info:
            await worker(state)

    assert "Gemini quota exceeded" in str(info.value)
    assert "Retry" in str(info.value)
    mock_storage.put_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_tts_failure_message_redacts_keys() -> None:
    """A provider error that echoes a URL with key=… never carries the secret."""
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch(
            "cf_platform.workers.voice_production._tts_generate",
            AsyncMock(side_effect=RuntimeError("503 for https://x.example/v1?key=AIzaSECRET123&alt=json")),
        ),
    ):
        worker = build_voice_production_worker(
            mock_storage, gemini_api_key="gemini-key", gemini_tts_voice="Kore"
        )
        with pytest.raises(VoiceGenerationError) as info:
            await worker(_make_state())

    assert "AIzaSECRET123" not in str(info.value)
    assert "key=REDACTED" in str(info.value)


@pytest.mark.asyncio
async def test_worker_upload_failure_raises() -> None:
    """If the audio cannot be stored, the job fails — there is no usable voiceover."""
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock(side_effect=OSError("R2 down"))

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=b"WAV")),
    ):
        worker = build_voice_production_worker(
            mock_storage, gemini_api_key="k", gemini_tts_voice="v"
        )
        with pytest.raises(VoiceGenerationError, match="R2 down"):
            await worker(_make_state())


# ── build_voice_production_worker — Deepgram failure falls back ───────────────


@pytest.mark.asyncio
async def test_worker_deepgram_failure_falls_back_to_proportional() -> None:
    """When Deepgram raises after successful TTS, worker uses proportional fallback."""
    fake_mp3 = b"MP3BYTES"
    mock_storage = MagicMock()
    mock_storage.put_bytes = AsyncMock()
    mock_storage.generate_presigned_url = AsyncMock(return_value="https://presigned.example/audio.mp3")
    state = _make_state()

    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=fake_mp3)),
        patch(
            "cf_platform.workers.voice_production._align_audio",
            AsyncMock(side_effect=RuntimeError("Deepgram 503")),
        ),
    ):
        worker = build_voice_production_worker(
            mock_storage,
            gemini_api_key="gemini-key",
            gemini_tts_voice="Kore",
            deepgram_api_key="dg-key",
        )
        result = await worker(state)

    assert result.artifact.alignment_method == "proportional_fallback"
    # WAV was still uploaded before Deepgram was called
    assert result.artifact.mp3_r2_key == f"runs/{_RUN_ID}/voiceover/generated.wav"
    mock_storage.put_bytes.assert_awaited_once()


# ── build_voice_production_worker — missing script artifact ───────────────────


@pytest.mark.asyncio
async def test_worker_missing_script_key_raises_key_error() -> None:
    """Worker raises KeyError when state.artifacts['script'] is absent."""
    mock_storage = MagicMock()
    state = StageState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, artifacts={})

    worker = build_voice_production_worker(mock_storage)
    with pytest.raises(KeyError, match="script"):
        await worker(state)


# ── Real audio length, run language, empty transcript ─────────────────────────


def _wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    """A silent mono 16-bit WAV of the given length."""
    from cf_platform.workers.voice_production import _pcm_to_wav

    return _pcm_to_wav(b"\x00\x00" * int(rate * seconds))


def _worker_state(**inputs: str) -> StageState:
    return StageState(run_id=_RUN_ID, user_id=_USER_ID, inputs=inputs, artifacts={"script": _SCRIPT_KEY})


def _mock_storage() -> MagicMock:
    storage = MagicMock()
    storage.put_bytes = AsyncMock()
    storage.generate_presigned_url = AsyncMock(return_value="https://presigned.example/audio.wav")
    return storage


def test_wav_duration_reads_the_real_length() -> None:
    """The WAV header gives the playing time; bytes that are not a WAV give None."""
    from cf_platform.workers.voice_production import _wav_duration_s

    assert _wav_duration_s(_wav_bytes(2.5)) == pytest.approx(2.5)
    assert _wav_duration_s(b"not a wav") is None


@pytest.mark.asyncio
async def test_fallback_duration_is_the_real_audio_length_not_the_estimate() -> None:
    """Without Deepgram words, total_duration_s is the WAV's length — the word-count estimate drifts."""
    storage = _mock_storage()
    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=_wav_bytes(41.0))),
    ):
        worker = build_voice_production_worker(storage, gemini_api_key="k", gemini_tts_voice="v", deepgram_api_key="")
        result = await worker(_make_state())

    assert result.artifact.alignment_method == "proportional_fallback"
    assert result.artifact.total_duration_s == pytest.approx(41.0)
    assert result.artifact.word_timestamps[-1].end_ms == pytest.approx(41000, abs=50)


@pytest.mark.asyncio
async def test_run_language_is_sent_to_deepgram() -> None:
    """A Russian run asks Deepgram for Russian; a run with no language asks for English."""
    words = [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250, confidence=0.9) for i, w in enumerate(_SCRIPT.split())]
    for inputs, expected in (({"language": "ru"}, "ru"), ({}, "en")):
        align = AsyncMock(return_value=words)
        with (
            patch(
                "cf_platform.workers.voice_production.read_artifact",
                AsyncMock(return_value=(MagicMock(), _make_script_body())),
            ),
            patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=_wav_bytes(4.0))),
            patch("cf_platform.workers.voice_production._align_audio", align),
        ):
            worker = build_voice_production_worker(
                _mock_storage(), gemini_api_key="k", gemini_tts_voice="v", deepgram_api_key="d"
            )
            result = await worker(_worker_state(**inputs))
        assert align.await_args.args[2] == expected
        assert result.artifact.alignment_method == "deepgram_nova2"


@pytest.mark.asyncio
async def test_transcript_that_missed_the_narration_fails_after_one_retry() -> None:
    """0 of ~13 words heard (the wrong-language case) fails the voiceover, not a fake alignment."""
    align = AsyncMock(return_value=[])
    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=_wav_bytes(4.0))),
        patch("cf_platform.workers.voice_production._align_audio", align),
    ):
        worker = build_voice_production_worker(
            _mock_storage(), gemini_api_key="k", gemini_tts_voice="v", deepgram_api_key="d"
        )
        with pytest.raises(VoiceGenerationError, match="language: ru"):
            await worker(_worker_state(language="ru"))
    assert align.await_count == 2


@pytest.mark.asyncio
async def test_transcript_recovers_on_the_retry() -> None:
    """A thin first answer followed by a full one is accepted."""
    words = [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250, confidence=0.9) for i, w in enumerate(_SCRIPT.split())]
    align = AsyncMock(side_effect=[words[:1], words])
    with (
        patch(
            "cf_platform.workers.voice_production.read_artifact",
            AsyncMock(return_value=(MagicMock(), _make_script_body())),
        ),
        patch("cf_platform.workers.voice_production._tts_generate", AsyncMock(return_value=_wav_bytes(4.0))),
        patch("cf_platform.workers.voice_production._align_audio", align),
    ):
        worker = build_voice_production_worker(
            _mock_storage(), gemini_api_key="k", gemini_tts_voice="v", deepgram_api_key="d"
        )
        result = await worker(_make_state())
    assert result.artifact.alignment_method == "deepgram_nova2"
    assert len(result.artifact.word_timestamps) == len(words)
