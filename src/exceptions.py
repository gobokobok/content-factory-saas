"""Domain exceptions for Content Factory pipeline."""


class StorageError(Exception):
    """Raised when an R2 storage operation fails."""


class StoryboardAPIError(Exception):
    """Raised when the Claude API call for storyboard generation fails."""


class StoryboardParseError(Exception):
    """Raised when the Claude response cannot be parsed into a valid storyboard."""
