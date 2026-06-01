"""Domain exceptions for Content Factory pipeline."""


class StorageError(Exception):
    """Raised when an R2 storage operation fails."""


class StoryboardAPIError(Exception):
    """Raised when the Claude API call for storyboard generation fails."""


class StoryboardParseError(Exception):
    """Raised when the Claude response cannot be parsed into a valid storyboard."""


class StoryboardValidationError(Exception):
    """Raised when Haiku schema validation finds rule violations in storyboard.json."""


class ManifestError(Exception):
    """Raised when asset manifest generation fails (e.g. invalid storyboard data)."""


class PexelsError(Exception):
    """Raised when a Pexels API search, rate-limit retry, or asset download fails."""


class ReplicateError(Exception):
    """Raised when a Replicate prediction create, poll, or image download fails."""


class FFmpegBuildError(Exception):
    """Raised when ffmpeg_script.sh cannot be generated (e.g. unacquired scene assets)."""


class RenderError(Exception):
    """Raised when FFmpeg execution fails or output cannot be uploaded."""


class CLIPError(Exception):
    """Raised when CLIP model encoding fails during Pexels result reranking."""


class AlignmentError(Exception):
    """Raised when Deepgram API call fails or returns an unexpected response."""


class TTSError(Exception):
    """Raised when ElevenLabs TTS API call, PCM concat, or ffmpeg MP3 encode fails."""


class MetadataError(Exception):
    """Raised when Claude API call or JSON parsing fails during metadata generation."""
