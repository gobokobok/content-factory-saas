"""Word-level timestamp extraction via Deepgram Nova-2 API.

Provides align_audio() for the happy path and proportional_fallback() for when
the Deepgram call is unavailable or fails.
"""

import logging
import re

import httpx

from src.exceptions import AlignmentError
from src.models import WordTimestamp

logger = logging.getLogger(__name__)

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_PUNCT_RE = re.compile(r"[^\w\s]")
_REQUEST_TIMEOUT_SECONDS = 60.0


async def align_audio(audio_url: str, api_key: str) -> list[WordTimestamp]:
    """Call Deepgram Nova-2 to extract word-level timestamps from a public audio URL.

    Returns a list of WordTimestamp entries with start_ms/end_ms in milliseconds.
    Raises AlignmentError on API failure, non-200 response, or unexpected structure.
    """
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    # smart_format=false: keeps numbers/percentages as spoken words ("ninety
    # percent" rather than "90%"). Storyboard voiceover_line text always
    # spells out numbers for TTS, so word-level matching in
    # assign_words_to_scenes (ffmpeg_builder.py) requires Deepgram's output
    # to use the same spelled-out form. See DECISIONS.md D045.
    params = {"model": "nova-2", "smart_format": "false"}
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                _DEEPGRAM_URL,
                headers=headers,
                params=params,
                json={"url": audio_url},
            )
        except httpx.HTTPError as exc:
            raise AlignmentError(f"Deepgram request failed: {exc}") from exc

    if response.status_code != 200:
        raise AlignmentError(
            f"Deepgram returned HTTP {response.status_code}: {response.text[:300]}"
        )

    raw_words = _extract_words(response.json())
    return [_normalize_word(w) for w in raw_words]


def _extract_words(data: dict) -> list[dict]:
    """Pull the words list out of the Deepgram response envelope.

    Raises AlignmentError if the expected keys are missing.
    """
    try:
        return data["results"]["channels"][0]["alternatives"][0]["words"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AlignmentError(
            f"Unexpected Deepgram response structure: {exc}"
        ) from exc


def _normalize_word(raw: dict) -> WordTimestamp:
    """Convert a raw Deepgram word dict to WordTimestamp.

    Strips punctuation from word, converts float seconds to int milliseconds.
    """
    word = _PUNCT_RE.sub("", raw.get("word", "")).strip()
    start_ms = int(float(raw["start"]) * 1000)
    end_ms = int(float(raw["end"]) * 1000)
    confidence = float(raw.get("confidence", 1.0))
    return WordTimestamp(word=word, start_ms=start_ms, end_ms=end_ms, confidence=confidence)


def proportional_fallback(text: str, total_duration_s: float) -> list[WordTimestamp]:
    """Generate word timestamps by character-count proportional distribution.

    Used when Deepgram is unavailable. Confidence is set to 0.0 to signal estimated timing.
    """
    words = text.split()
    if not words:
        return []

    total_chars = sum(len(w) for w in words)
    if total_chars == 0:
        return []

    total_ms = int(total_duration_s * 1000)
    result: list[WordTimestamp] = []
    offset_ms = 0
    for word in words:
        duration_ms = max(1, int(total_ms * len(word) / total_chars))
        clean = _PUNCT_RE.sub("", word).strip()
        result.append(
            WordTimestamp(
                word=clean,
                start_ms=offset_ms,
                end_ms=offset_ms + duration_ms,
                confidence=0.0,
            )
        )
        offset_ms += duration_ms

    return result
