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

    # Claude model overrides per task type (E8-S4 — ModelRouter)
    MODEL_VALIDATE: str = "claude-haiku-4-5-20251001"
    MODEL_SUMMARIZE: str = "claude-haiku-4-5-20251001"
    MODEL_TRANSFORM: str = "claude-haiku-4-5-20251001"
    MODEL_REASON: str = "claude-sonnet-4-6"

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
    # ffmpeg_script.sh runs as a single subprocess covering all per-scene clips,
    # concat, and captioning. 300s was too short even for a ~3min/40-scene
    # video (timed out mid-caption-encode). 1800s gives headroom for current
    # script lengths; longer videos will need a background-render redesign.
    FFMPEG_TIMEOUT_SECONDS: int = 1800

    # CLIP reranking (E4-S4)
    CLIP_RERANK_ENABLED: bool = False

    # Deepgram alignment (E5-S4)
    DEEPGRAM_API_KEY: str = ""

    # ElevenLabs TTS (S10-S1)
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""

    # Storyboard chunking (S13-S1)
    STORYBOARD_CHUNK_SIZE: int = 10
    # Word-count cap per chunk. Comma-list scenes can multiply scene count well
    # beyond what paragraph count predicts; this caps output tokens per Claude
    # call independent of paragraph density. ~150 words keeps chunks safely
    # under the 8192 max_tokens output limit even for list-heavy scripts.
    STORYBOARD_CHUNK_MAX_WORDS: int = 150

    # Asset acquisition parallelism (S13-S2)
    # Default is 4 — conservative for Railway containers with CLIP reranking enabled
    # (20 concurrent threads × full-res Pexels downloads + CLIP encode caused OOM).
    # Increase via env var on hosts with more memory.
    ACQUISITION_BATCH_SIZE: int = 4
    # When True (default), the Replicate fallback is skipped for scenes whose
    # asset_mode is None.  Scenes explicitly set to "ai_generated" still use
    # Replicate.  Set to False only in environments where Replicate is available
    # and slow AI generation is acceptable (e.g. batch overnight runs).
    ACQUISITION_PEXELS_ONLY: bool = True

    # Auth (S5-S5)
    OPERATOR_PASSWORD: str
    SESSION_SECRET_KEY: str

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
