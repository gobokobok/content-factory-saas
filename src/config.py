"""Application configuration — all ENV vars loaded and validated at startup via pydantic-settings."""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    PIXABAY_API_KEY: str = ""  # optional — absent skips Pixabay silently (D063)

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
    # Per-process -threads cap for the libx264 encoders launched inside
    # _scene_section's parallel batch (up to 4 scenes encode concurrently — see
    # _scene_section's _MAX). Left unset, libx264 auto-detects the HOST's
    # logical CPU count rather than the container's actual cgroup quota, so 4
    # concurrent processes can each spin up dozens of threads and starve each
    # other. PROD run e743b0ea-93dd-47ef-9910-0b2a95b6db43 crashed this way:
    # libx264 reported threads=60 per process, and one of the 4 concurrent
    # scene encodes lost the resulting contention and errored out re-opening
    # its filter graph ("Error reinitializing filters!", exit 1). See D090.
    FFMPEG_SCENE_THREADS: int = 2

    # CLIP reranking (E4-S4)
    CLIP_RERANK_ENABLED: bool = False

    # Colour grading (P8-S6)
    COLOR_GRADE_PRESET: str = "neutral"  # neutral | vivid | warm | cinematic | muted
    BLUR_FILL_ENABLED: bool = True  # landscape stills get blur-fill compositing when True

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

    # Login rate limiting: block an IP after LOGIN_MAX_ATTEMPTS failed
    # attempts within LOGIN_ATTEMPT_WINDOW_SECONDS.  Defaults suit a
    # single-operator tool; override via ENV if needed.
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_ATTEMPT_WINDOW_SECONDS: int = 900
    # F18: the session cookie is Secure unless this is set — only for plain-http
    # local development. DEV and PROD are https and must leave it false.
    COOKIE_ALLOW_INSECURE: bool = False
    # F14: key the login lockout on the right-most X-Forwarded-For entry (the one
    # Railway's proxy appends) instead of the proxy's own address.
    TRUST_PROXY_HEADERS: bool = True
    # Shortest OPERATOR_PASSWORD / SESSION_SECRET_KEY the app starts with (F7).
    AUTH_SECRET_MIN_LENGTH: int = 12
    # Google sign-in and accounts (P-AUTH, D114, D118). The redirect URI is fixed here,
    # never derived from the request Host header. Empty client id = Google sign-in off.
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""
    # Comma-separated e-mails. OWNER_EMAILS map onto the legacy tenant (the owner keeps
    # their data) and are Super; SUPER_EMAILS are Super with their own tenant;
    # ALLOWED_EMAILS may sign in as Basic while SIGNUP_OPEN is false.
    OWNER_EMAILS: str = ""
    SUPER_EMAILS: str = ""
    ALLOWED_EMAILS: str = ""
    # When true any verified Google account may sign in. Leave false until the caps (S8)
    # and the moderation gate (S9) are deployed and checked.
    SIGNUP_OPEN: bool = False
    SESSION_TTL_DAYS: int = 14
    # Accept the pre-P-AUTH constant cookie as the owner (F6). Set false once the owner
    # has signed in again; the cookie cannot expire or be revoked, so this is a bridge.
    ACCEPT_LEGACY_COOKIE: bool = True
    # The repositories fall back to process memory when DATABASE_URL is empty. That is
    # right on a laptop and wrong on a server, so it is refused unless this is set (S6).
    ALLOW_IN_MEMORY_STORE: bool = False
    # Origins besides the request's own that may send mutating requests (comma-separated).
    ALLOWED_ORIGINS: str = ""
    # Where "Report a problem" mails (S9, D115). Empty hides the link.
    ABUSE_CONTACT_EMAIL: str = ""
    # The version of the terms a first sign-in accepts (S9); bumping it asks again.
    TERMS_VERSION: str = "2026-10-14"
    # Encryption key for tenant-stored integration keys. Read here only so a prod
    # start-up without one is refused (F7); the platform reads it in its own settings.
    SETTINGS_ENCRYPTION_KEY: str = ""

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure LOG_LEVEL is one of the accepted values."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return upper


def check_deployment_settings(settings: Settings) -> Settings:
    """Raise ValueError for auth secrets that are empty or too short, or a prod start without the encryption key (F7).

    Applied in get_settings() — the path the running app takes — rather than as a
    model validator, so tests that build Settings from a dict are unaffected.
    """
    minimum = max(1, settings.AUTH_SECRET_MIN_LENGTH)
    for name in ("OPERATOR_PASSWORD", "SESSION_SECRET_KEY"):
        if len(getattr(settings, name)) < minimum:
            raise ValueError(f"{name} must be at least {minimum} characters")
    if settings.ENVIRONMENT == "prod" and not settings.SETTINGS_ENCRYPTION_KEY:
        raise ValueError("SETTINGS_ENCRYPTION_KEY must be set when ENVIRONMENT=prod")
    return settings


def get_settings() -> Settings:
    """Return a validated Settings instance. Called once at startup and injected via Depends()."""
    return check_deployment_settings(Settings())
