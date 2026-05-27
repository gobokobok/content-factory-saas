"""Application configuration — all ENV vars loaded and validated at startup via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal


class Settings(BaseSettings):
    """Validates all required ENV vars at process start. Missing vars raise an error immediately."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core
    ENVIRONMENT: Literal["dev", "prod"]
    LOG_LEVEL: str = "INFO"

    # Cloudflare R2 storage
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str

    # Claude API
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    # Asset APIs
    PEXELS_API_KEY: str
    REPLICATE_API_TOKEN: str
    FREESOUND_API_KEY: str

    # Pipeline config (optional with defaults)
    PEXELS_PER_PAGE: int = 5
    REPLICATE_FLUX_MODEL: str = "black-forest-labs/flux-schnell"
    REPLICATE_POLL_INTERVAL_SECONDS: int = 3
    REPLICATE_MAX_POLL_ATTEMPTS: int = 60

    # FFmpeg
    FFMPEG_TIMEOUT_SECONDS: int = 300

    # CLIP reranking (E4-S4)
    CLIP_RERANK_ENABLED: bool = False

    # Deepgram alignment (E5-S4)
    DEEPGRAM_API_KEY: str = ""

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure LOG_LEVEL is one of the accepted values."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return upper


def get_settings() -> Settings:
    """Return a validated Settings instance. Called once at startup and injected via Depends()."""
    return Settings()
