"""ElevenLabs TTS voiceover generation.

Splits the script into sentence-boundary chunks (~1000 chars), sends all chunks
to ElevenLabs concurrently, concatenates the raw PCM responses in order, then
encodes to MP3 via an ffmpeg subprocess.  See DECISIONS.md D038 + D039.
"""

import asyncio
import logging
import re
import subprocess
from typing import Optional

import httpx

from src.exceptions import TTSError

logger = logging.getLogger(__name__)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
_OUTPUT_FORMAT = "pcm_44100"
_TARGET_CHUNK_CHARS = 1000

# PCM parameters that must match _OUTPUT_FORMAT
_PCM_SAMPLE_RATE = 44100
_PCM_CHANNELS = 1
_PCM_SAMPLE_FMT = "s16le"


def split_into_chunks(script: str, target_chars: int = _TARGET_CHUNK_CHARS) -> list[str]:
    """Split script at sentence boundaries into chunks of ~target_chars characters.

    Sentences are split on '.', '!', or '?' followed by whitespace or end of string.
    Adjacent short sentences are merged into one chunk until the target length is reached.
    Returns at least one chunk (the full script) even if it exceeds target_chars.
    """
    # Split at sentence-ending punctuation; keep the delimiter attached to the sentence
    raw_sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    if not sentences:
        return [script.strip()] if script.strip() else []

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current_parts and current_len + 1 + sentence_len > target_chars:
            chunks.append(" ".join(current_parts))
            current_parts = [sentence]
            current_len = sentence_len
        else:
            current_parts.append(sentence)
            current_len += (1 if current_parts else 0) + sentence_len

    if current_parts:
        chunks.append(" ".join(current_parts))

    return chunks


async def _call_elevenlabs(
    text: str,
    api_key: str,
    voice_id: str,
    previous_text: Optional[str],
    next_text: Optional[str],
    timeout: float = 60.0,
) -> bytes:
    """Call ElevenLabs streaming TTS for one chunk and return raw PCM bytes.

    Raises TTSError on any HTTP or network failure.
    """
    url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    payload: dict = {
        "text": text,
        "output_format": _OUTPUT_FORMAT,
    }
    if previous_text:
        payload["previous_text"] = previous_text
    if next_text:
        payload["next_text"] = next_text

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"xi-api-key": api_key},
            )
    except httpx.HTTPError as exc:
        raise TTSError(f"ElevenLabs request failed: {exc}") from exc

    if resp.status_code != 200:
        raise TTSError(
            f"ElevenLabs returned {resp.status_code}: {resp.text[:200]}"
        )

    return resp.content


def _encode_pcm_to_mp3(pcm_bytes: bytes) -> bytes:
    """Encode raw PCM bytes to MP3 via ffmpeg subprocess.

    Raises TTSError if ffmpeg fails or is not available.
    """
    cmd = [
        "ffmpeg",
        "-y",                        # overwrite output
        "-f", _PCM_SAMPLE_FMT,
        "-ar", str(_PCM_SAMPLE_RATE),
        "-ac", str(_PCM_CHANNELS),
        "-i", "pipe:0",              # read PCM from stdin
        "-f", "mp3",
        "pipe:1",                    # write MP3 to stdout
    ]
    try:
        result = subprocess.run(
            cmd,
            input=pcm_bytes,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise TTSError("ffmpeg not found — cannot encode PCM to MP3")
    except subprocess.TimeoutExpired:
        raise TTSError("ffmpeg MP3 encode timed out after 120s")

    if result.returncode != 0:
        stderr_snippet = result.stderr[-400:].decode("utf-8", errors="replace")
        raise TTSError(f"ffmpeg exited {result.returncode}: {stderr_snippet}")

    return result.stdout


async def generate_tts(script: str, api_key: str, voice_id: str) -> tuple[bytes, int]:
    """Generate MP3 audio from script using ElevenLabs chunked parallel TTS.

    Returns (mp3_bytes, chunk_count).  Raises TTSError on any failure.
    """
    chunks = split_into_chunks(script)
    if not chunks:
        raise TTSError("Script is empty — cannot generate TTS")

    logger.info("TTS: %d chunks for %d chars of script", len(chunks), len(script))

    # Build coroutines with previous_text / next_text context for prosody continuity
    tasks = []
    for i, chunk in enumerate(chunks):
        prev = chunks[i - 1] if i > 0 else None
        nxt = chunks[i + 1] if i < len(chunks) - 1 else None
        tasks.append(_call_elevenlabs(chunk, api_key, voice_id, prev, nxt))

    try:
        pcm_parts: list[bytes] = await asyncio.gather(*tasks)
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(f"Unexpected error during TTS gather: {exc}") from exc

    combined_pcm = b"".join(pcm_parts)
    logger.info("TTS: PCM concat %d bytes from %d chunks", len(combined_pcm), len(chunks))

    mp3_bytes = _encode_pcm_to_mp3(combined_pcm)
    logger.info("TTS: MP3 encode complete, %d bytes", len(mp3_bytes))

    return mp3_bytes, len(chunks)
