"""cf_platform's own settings (P1-S6) — R2 credentials, independent of src/config.py (D047).

cf_platform may not import src/ outside the legacy adapter, so it maintains a minimal,
standalone Settings class for the ENV vars its core modules need. Reuses the same
ENV var names as src/config.py's Settings (shared R2 bucket) — no new ENV vars.

P2-S1 adds DATABASE_URL (Railway Postgres, D048) — optional/empty by default so a
missing or unset value cannot break platform startup; cf_platform/core/db.py treats
an empty DATABASE_URL as "database unavailable" rather than raising.
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


def get_platform_settings() -> PlatformSettings:
    """Return a validated PlatformSettings instance."""
    return PlatformSettings()
