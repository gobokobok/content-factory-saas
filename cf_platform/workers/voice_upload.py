"""Uploaded-voiceover worker (P14b) — audio file → word-level transcript.

The operator's own recording replaces the TTS step. Deepgram transcribes it and the
result is the same `VoiceAlignmentArtifact` a generated voice produces, so the
storyboard, timeline, render and CapCut export read it unchanged; only
`alignment_method` marks it as an upload.

Like voice_production this is a self-contained platform worker (D047): it imports
nothing from src/. Guards (S4) raise `VoiceUploadError` with a message the Studio
shows as-is: no speech, too short, too long, unreadable audio. A language that looks
wrong is a *warning*, not a failure (`language_warning`): the transcript is kept and
the operator decides.
"""

import logging

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.storyboard_worker import _normalize_deepgram_words
from cf_platform.workers.voice_production import (
    VoiceAlignmentArtifact,
    VoiceWordTimestamp,
    _deepgram_transcribe,
)

logger = logging.getLogger(__name__)

UPLOADED_ALIGNMENT_METHOD = "uploaded_deepgram_nova2"
UPLOADED_SCRIPT_SOURCE = "uploaded_vo"
DEFAULT_LANGUAGE = "en"

VOICE_UPLOAD_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",
    model="deepgram_nova2",
    sampling_params={},
)

# extension → accepted MIME types (browsers disagree on m4a and wav).
_ALLOWED_TYPES: dict[str, frozenset[str]] = {
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"}),
}
_CONTENT_TYPE_BY_EXT = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


class VoiceUploadError(ValueError):
    """An uploaded voiceover that cannot be used; the message is shown to the operator."""


def content_type_for(ext: str) -> str:
    """Return the MIME type stored with an uploaded file of this extension."""
    return _CONTENT_TYPE_BY_EXT[ext]


def _looks_like_audio(ext: str, data: bytes) -> bool:
    """Cheap container check on the first bytes — the file really is mp3, wav or m4a."""
    if ext == ".mp3":
        return data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if ext == ".wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    return data[4:8] == b"ftyp"


def validate_voice_upload(filename: str | None, content_type: str | None, data: bytes, max_bytes: int) -> str:
    """Check extension, MIME type, size and file header; return the extension or raise VoiceUploadError."""
    name = (filename or "").lower()
    ext = next((e for e in _ALLOWED_TYPES if name.endswith(e)), "")
    if not ext:
        raise VoiceUploadError("Unsupported file. Upload an mp3, wav or m4a voiceover.")
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in _ALLOWED_TYPES[ext]:
        raise VoiceUploadError(f"File type {mime or 'unknown'!r} does not match a {ext} audio file.")
    if not data:
        raise VoiceUploadError("The file is empty.")
    if len(data) > max_bytes:
        raise VoiceUploadError(
            f"File too large ({len(data) // (1024 * 1024)} MB). Maximum is {max_bytes // (1024 * 1024)} MB."
        )
    if not _looks_like_audio(ext, data):
        raise VoiceUploadError(f"This is not a readable {ext} audio file.")
    return ext


_CYRILLIC_LANGUAGES = frozenset({"ru", "uk", "be", "bg", "sr", "mk"})


def _script_share(words: list[str]) -> tuple[float, float]:
    """Return (Cyrillic share, Latin share) of the letters in the words."""
    letters = [c for w in words for c in w if c.isalpha()]
    if not letters:
        return 0.0, 0.0
    cyrillic = sum(1 for c in letters if "\u0400" <= c <= "\u04ff")
    latin = sum(1 for c in letters if c.isascii())
    return cyrillic / len(letters), latin / len(letters)


def language_warning(
    words: list[VoiceWordTimestamp], language: str, low_confidence: float
) -> dict | None:
    """Return a warning dict when the transcript looks like it is not in `language`, else None.

    Deepgram is told the run's language, so it never reports a mismatch itself; two
    signals stand in. (1) Script: a Cyrillic-language run whose words are mostly Latin
    letters, or the reverse, was almost certainly spoken in another language
    (`detected` is then "en" or "ru" as the best guess of that script). (2) Mean word
    confidence below `low_confidence`, which is what a wrong-language model produces
    (`detected` is None). Neither is proof — Studio words it as a question.
    """
    if not words:
        return None
    cyrillic, latin = _script_share([w.word for w in words])
    expects_cyrillic = language.lower() in _CYRILLIC_LANGUAGES
    if expects_cyrillic and latin > 0.5:
        return {"expected": language, "detected": "en", "reason": "the words are mostly Latin letters"}
    if not expects_cyrillic and cyrillic > 0.5:
        return {"expected": language, "detected": "ru", "reason": "the words are mostly Cyrillic letters"}
    mean = sum(w.confidence for w in words) / len(words)
    if mean < low_confidence:
        return {
            "expected": language, "detected": None,
            "reason": f"Deepgram was unsure of most words (average confidence {mean:.0%})",
        }
    return None


def build_voice_upload_worker(
    storage: ArtifactStorage,
    deepgram_api_key: str,
    *,
    min_s: float,
    max_s: float,
) -> WorkerNode:
    """Return a worker that transcribes state.inputs['audio_r2_key'] with Deepgram.

    state.inputs['language'] (ISO 639-1, default "en") is the transcription language.
    Words are collapsed exactly as the storyboard will read them (contraction splits
    merged), so the transcript editor's word indices are the storyboard's.
    Raises VoiceUploadError for no speech, a length outside [min_s, max_s], or audio
    Deepgram cannot read.
    """

    async def voice_upload(state: StageState) -> WorkerOutput:
        """Transcribe the uploaded audio and return its VoiceAlignmentArtifact."""
        audio_key = state.inputs["audio_r2_key"]
        if not deepgram_api_key:
            raise VoiceUploadError("Transcription is not available: DEEPGRAM_API_KEY is not set.")
        url = await storage.generate_presigned_url(audio_key, expires_in=900)
        try:
            transcript = await _deepgram_transcribe(
                url, deepgram_api_key, language=state.inputs.get("language") or DEFAULT_LANGUAGE
            )
        except RuntimeError as exc:
            raise VoiceUploadError(f"Deepgram could not transcribe this audio: {exc}") from exc

        words = _normalize_deepgram_words([w.model_dump() for w in transcript.words])
        if not words:
            raise VoiceUploadError("No speech was found in this audio — it may be silent or not a voiceover.")
        duration = transcript.duration_s if transcript.duration_s is not None else words[-1].end_ms / 1000
        if duration < min_s:
            raise VoiceUploadError(f"Audio is too short ({duration:.1f}s). Minimum is {min_s:g}s.")
        if duration > max_s:
            raise VoiceUploadError(f"Audio is too long ({duration:.0f}s). Maximum is {max_s:g}s.")
        logger.info("Uploaded VO transcribed for run %s — %d words, %.1fs", state.run_id, len(words), duration)
        return WorkerOutput(
            artifact=VoiceAlignmentArtifact(
                mp3_r2_key=audio_key,
                word_timestamps=words,
                alignment_method=UPLOADED_ALIGNMENT_METHOD,
                total_duration_s=words[-1].end_ms / 1000,
            )
        )

    return voice_upload
