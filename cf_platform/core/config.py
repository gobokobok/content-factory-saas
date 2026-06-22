"""cf_platform's own settings (P1-S6) — R2 credentials, independent of src/config.py (D047).

cf_platform may not import src/ outside the legacy adapter, so it maintains a minimal,
standalone Settings class for the ENV vars its core modules need. Reuses the same
ENV var names as src/config.py's Settings (shared R2 bucket) — no new ENV vars.

P2-S1 adds DATABASE_URL (Railway Postgres, D048) — optional/empty by default so a
missing or unset value cannot break platform startup; cf_platform/core/db.py treats
an empty DATABASE_URL as "database unavailable" rather than raising.

P3-S1 adds TELEGRAM_BOT_TOKEN/TELEGRAM_WEBHOOK_SECRET (D049) — optional/empty by
default; an unset secret rejects all webhook calls rather than failing startup.
TELEGRAM_ALLOWED_CHAT_IDS restricts which chats the bot will reply to (temporary,
single-operator allowlist ahead of S19 multi-tenant auth); empty means unrestricted.

P3-S2 adds REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET/REDDIT_USER_AGENT and
YOUTUBE_API_KEY (D050) — optional/empty by default; the Discovery worker's
partial-failure isolation (AC #3) means a missing credential degrades that one
source adapter to an error trace event rather than failing the worker or startup.
GoogleTrendsAdapter needs no credentials (raw httpx against the public, unofficial
Trends API).

P4-S1 adds ANTHROPIC_API_KEY (same ENV var as src/config.py) — optional/empty
by default per D048 fault isolation; a missing key will fail at Claude call time
inside the Topic Generator worker rather than at platform startup. In practice
this key is always set since the legacy pipeline also requires it.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """R2 credentials + Postgres connection string for cf_platform (D047, D048)."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    DATABASE_URL: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = ""
    YOUTUBE_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    HITL_TIMEOUT_SECONDS: int = 0
    GEMINI_API_KEY: str = ""
    GEMINI_TTS_VOICE: str = ""
    DEEPGRAM_API_KEY: str = ""
    # Same ENV var names as src/config.py — reused by the native AcquisitionWorker (P9-S3).
    PEXELS_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""


def get_platform_settings() -> PlatformSettings:
    """Return a validated PlatformSettings instance."""
    return PlatformSettings()
