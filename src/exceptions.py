"""Domain exceptions for Content Factory pipeline."""


class StorageError(Exception):
    """Raised when an R2 storage operation fails."""


class StoryboardAPIError(Exception):
    """Raised when the Claude API call for storyboard generation fails."""


class StoryboardParseError(Exception):
    """Raised when the Claude response cannot be parsed into a valid storyboard."""


class ManifestError(Exception):
    """Raised when asset manifest generation fails (e.g. invalid storyboard data)."""


class PexelsError(Exception):
    """Raised when a Pexels API search, rate-limit retry, or asset download fails."""


class ReplicateError(Exception):
    """Raised when a Replicate prediction create, poll, or image download fails."""
