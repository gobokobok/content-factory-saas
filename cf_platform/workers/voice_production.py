"""Voice Production worker (P6-S7) — Script → MP3 → word-level timestamps.

Generates voiceover audio via Gemini 2.5 Flash TTS (single call, no chunking)
and extracts word-level timestamps via Deepgram Nova-2.  Falls back to
character-count-proportional timestamp estimation when either API key is absent
or an API call fails.

This module is a self-contained platform worker and MUST NOT import from src/
(D047).  The Deepgram HTTP logic is re-implemented here using httpx rather than
delegating to src/alignment.py.

The adapter (legacy_video.py) converts VoiceWordTimestamp → src.models.WordTimestamp
at the D047 boundary before passing timestamps into the legacy pipeline functions.

D061: Gemini 2.5 Flash TTS chosen over ElevenLabs — free tier, single API key
(same GEMINI_API_KEY used by the core platform), no per-character cost at POC
scale.  ElevenLabs placeholder removed in P6-S7.
"""

import asyncio
import base64
import logging
import re
import wave
import io
from typing import Optional

import httpx
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

logger = logging.getLogger(__name__)

# ── Gemini TTS constants ──────────────────────────────────────────────────────

_GEMINI_TTS_MODEL = "gemini-2.5-pro-preview-tts"
_GEMINI_PCM_SAMPLE_RATE = 24000
_GEMINI_PCM_CHANNELS = 1
_GEMINI_PCM_SAMPLE_FMT = "s16le"

# ── Deepgram constants ────────────────────────────────────────────────────────

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_DEEPGRAM_TIMEOUT_SECONDS = 60.0
_PUNCT_RE = re.compile(r"[^\w\s.%]")

# ── Narration pace (words-per-second) used for proportional fallback ──────────

_WORDS_PER_SECOND = 160 / 60
_WORDS_PER_SECOND_SHORT = 175 / 60  # 9:16 Shorts narrate faster than 16:9 long-form

# Gemini's native TTS models have no numeric speaking-rate parameter (SpeechConfig
# only exposes language_code, voice_config, multi_speaker_voice_config) — pace is
# controlled by a natural-language style instruction prefixed to the input text,
# which the model follows without vocalizing the instruction itself.
_SHORTS_PACE_INSTRUCTION = (
    "Narrate the following energetically at a brisk, fast pace, about 170 to 180 "
    "words per minute, like a YouTube Shorts voiceover: "
)


# ── Artifact schemas ──────────────────────────────────────────────────────────


class VoiceWordTimestamp(BaseModel):
    """Word-level timestamp produced by Deepgram or proportional fallback.

    Mirrors src.models.WordTimestamp so the adapter can convert via model_dump().
    confidence=0.0 signals estimated (not measured) timing.
    """

    word: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0


class VoiceAlignmentArtifact(BaseModel):
    """Terminal artifact of the voice_production worker.

    mp3_r2_key points to a WAV file in R2; empty when TTS was skipped (no
    Gemini key), in which case the legacy render pipeline produces a silent
    video.  word_timestamps is always populated — by Deepgram when both keys
    are present, otherwise by proportional_fallback.
    """

    mp3_r2_key: str
    word_timestamps: list[VoiceWordTimestamp]
    alignment_method: str
    total_duration_s: float


# ── Worker registration ───────────────────────────────────────────────────────


VOICE_PRODUCTION_REGISTRATION = WorkerRegistration(
    worker_version="2.0.0",
    prompt_version="v1",
    prompt="",
    model="gemini_pro_deepgram",
    sampling_params={},
)


# ── Gemini TTS (no src/ import, D047) ────────────────────────────────────────


def _call_gemini_tts_sync(text: str, api_key: str, voice: str) -> bytes:
    """Call Gemini 2.5 Flash TTS synchronously; return raw PCM bytes.

    google-genai is a synchronous SDK — wrap with asyncio.to_thread at the
    call site.  The inline_data payload is PCM s16le at 24 kHz, mono.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_GEMINI_TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    data = response.candidates[0].content.parts[0].inline_data.data
    if isinstance(data, str):
        return base64.b64decode(data)
    return data


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw PCM (s16le, 24 kHz, mono) in a WAV container — no re-encoding."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_GEMINI_PCM_CHANNELS)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(_GEMINI_PCM_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


async def _tts_generate(script: str, api_key: str, voice: str) -> bytes:
    """Generate WAV from script via a single Gemini 2.5 Flash TTS call."""
    if not script.strip():
        raise RuntimeError("Script is empty — cannot generate TTS")
    pcm_bytes = await asyncio.to_thread(_call_gemini_tts_sync, script, api_key, voice)
    return _pcm_to_wav(pcm_bytes)


# ── Deepgram alignment re-implementation (no src/ import, D047) ──────────────


def _normalize_word(raw: dict) -> VoiceWordTimestamp:
    """Convert a raw Deepgram word dict to VoiceWordTimestamp."""
    word = _PUNCT_RE.sub("", raw.get("word", "")).strip()
    start_ms = int(float(raw["start"]) * 1000)
    end_ms = int(float(raw["end"]) * 1000)
    confidence = float(raw.get("confidence", 1.0))
    return VoiceWordTimestamp(word=word, start_ms=start_ms, end_ms=end_ms, confidence=confidence)


async def _align_audio(audio_url: str, api_key: str) -> list[VoiceWordTimestamp]:
    """Call Deepgram Nova-2 with a presigned URL; return word-level timestamps.

    smart_format=true (D045 rev): the v2 pipeline storyboard copies verbatim
    script text into voiceover_line, so numeric tokens like "15000" (from
    "£15,000") must match Deepgram's output. With smart_format=true Deepgram
    returns "15,000" (normalises to "15000") instead of "fifteen thousand"
    (never matches "15000"), eliminating the orphaned-word/missing-caption bug
    for all figure-heavy scripts.
    """
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    params = {"model": "nova-2", "smart_format": "true"}
    async with httpx.AsyncClient(timeout=_DEEPGRAM_TIMEOUT_SECONDS) as client:
        resp = await client.post(_DEEPGRAM_URL, headers=headers, params=params, json={"url": audio_url})
    if resp.status_code != 200:
        raise RuntimeError(f"Deepgram returned {resp.status_code}: {resp.text[:300]}")
    try:
        raw_words = resp.json()["results"]["channels"][0]["alternatives"][0]["words"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Deepgram response structure: {exc}") from exc
    return [_normalize_word(w) for w in raw_words]


# ── Proportional fallback (no src/ import, D047) ─────────────────────────────


def _proportional_fallback(text: str, total_duration_s: float) -> list[VoiceWordTimestamp]:
    """Distribute word timestamps proportionally by character count.

    Used when Deepgram is unavailable.  confidence=0.0 marks estimated timing.
    """
    words = text.split()
    if not words:
        return []
    total_chars = sum(len(w) for w in words)
    if total_chars == 0:
        return []
    total_ms = int(total_duration_s * 1000)
    result: list[VoiceWordTimestamp] = []
    offset_ms = 0
    for word in words:
        duration_ms = max(1, int(total_ms * len(word) / total_chars))
        clean = _PUNCT_RE.sub("", word).strip()
        result.append(VoiceWordTimestamp(word=clean, start_ms=offset_ms, end_ms=offset_ms + duration_ms, confidence=0.0))
        offset_ms += duration_ms
    return result


def _estimate_duration(script: str, aspect_ratio: str = "16:9") -> float:
    """Estimate narration duration from word count at standard narration pace.

    9:16 Shorts use a faster proportional-fallback rate to match the TTS pace
    instruction applied in _build_tts_input.
    """
    wps = _WORDS_PER_SECOND_SHORT if aspect_ratio == "9:16" else _WORDS_PER_SECOND
    return max(1.0, len(script.split()) / wps)


def _build_tts_input(script: str, aspect_ratio: str) -> str:
    """Prefix the script with a pace-style instruction for 9:16 Shorts narration."""
    if aspect_ratio == "9:16":
        return _SHORTS_PACE_INSTRUCTION + script
    return script


# ── Worker factory ────────────────────────────────────────────────────────────


def build_voice_production_worker(
    storage: ArtifactStorage,
    gemini_api_key: str = "",
    gemini_tts_voice: str = "",
    deepgram_api_key: str = "",
) -> WorkerNode:
    """Return a voice_production WorkerNode bound to the given credentials.

    Worker reads state.artifacts['script'] → fetches ScriptArtifact from R2 →
    attempts Gemini 2.5 Flash TTS (if key present) → uploads MP3 to
    runs/{run_id}/voiceover/generated.mp3 → attempts Deepgram alignment via
    a 15-minute presigned URL → falls back to proportional timestamps on any
    failure.  Returns WorkerOutput(artifact=VoiceAlignmentArtifact).

    Fault isolation (D048): missing keys or API failures degrade gracefully;
    the pipeline always continues with whatever timestamps are available.

    state.inputs['aspect_ratio'] (default "16:9") selects narration pace: "9:16"
    applies a fast-pace style instruction for Shorts (~170-180 wpm); other ratios
    use Gemini's natural default pace.
    """

    async def voice_production(state: StageState) -> WorkerOutput:
        """Generate TTS audio and word-level timestamps for the script."""
        script_key = state.artifacts.get("script")
        if not script_key:
            raise KeyError("state.artifacts['script'] missing — idea_to_script must run before voice_production")

        _, script_body = await read_artifact(storage, script_key)
        script_text: str = script_body["script"]
        aspect_ratio: str = state.inputs.get("aspect_ratio", "16:9")

        mp3_r2_key = ""
        word_timestamps: list[VoiceWordTimestamp] = []
        alignment_method = "proportional_fallback"
        total_duration_s = _estimate_duration(script_text, aspect_ratio)

        # ── Step 1: TTS ────────────────────────────────────────────────────
        if gemini_api_key and gemini_tts_voice:
            try:
                tts_input = _build_tts_input(script_text, aspect_ratio)
                wav_bytes = await _tts_generate(tts_input, gemini_api_key, gemini_tts_voice)
                mp3_r2_key = f"runs/{state.run_id}/voiceover/generated.wav"
                await storage.put_bytes(mp3_r2_key, wav_bytes, "audio/wav")
                logger.info("TTS complete for run %s — %d bytes", state.run_id, len(wav_bytes))
            except Exception as exc:
                logger.warning("TTS failed for run %s — using proportional fallback: %s", state.run_id, exc)
                mp3_r2_key = ""

        # ── Step 2: Alignment ──────────────────────────────────────────────
        if mp3_r2_key and deepgram_api_key:
            try:
                # 15-minute presigned URL so Deepgram can fetch the file.
                presigned_url = await storage.generate_presigned_url(mp3_r2_key, expires_in=900)
                word_timestamps = await _align_audio(presigned_url, deepgram_api_key)
                alignment_method = "deepgram_nova2"
                if word_timestamps:
                    total_duration_s = word_timestamps[-1].end_ms / 1000
                logger.info("Deepgram alignment complete for run %s — %d words", state.run_id, len(word_timestamps))
            except Exception as exc:
                logger.warning("Deepgram alignment failed for run %s — using proportional fallback: %s", state.run_id, exc)
                word_timestamps = []

        # ── Step 3: Fallback ───────────────────────────────────────────────
        if not word_timestamps:
            word_timestamps = _proportional_fallback(script_text, total_duration_s)
            alignment_method = "proportional_fallback"

        return WorkerOutput(
            artifact=VoiceAlignmentArtifact(
                mp3_r2_key=mp3_r2_key,
                word_timestamps=word_timestamps,
                alignment_method=alignment_method,
                total_duration_s=total_duration_s,
            )
        )

    return voice_production
