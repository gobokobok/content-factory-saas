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
        # An empty Railway variable ("SIGNUP_OPEN=") means "not set", not a parse error that
        # stops the app from starting (P-AUTH DEV crash, 2026-10-14).
        env_ignore_empty=True,
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
    # D117 — the two narrator voices a run may choose in the Creator pages (Gemini TTS
    # voice names). Empty male means GEMINI_TTS_VOICE, the voice the channel already uses;
    # a run with no choice uses GEMINI_TTS_VOICE too.
    CREATOR_VOICE_MALE: str = ""
    CREATOR_VOICE_FEMALE: str = "Kore"
    # D117 — the fixed project the Creator pages keep their runs in until every user
    # has a hidden personal project (P-AUTH).
    CREATOR_PROJECT_NAME: str = "My videos"
    # D117 — word limit the Creator's Script step shows (about three minutes of narration).
    CREATOR_SCRIPT_MAX_WORDS: int = 450
    # D114 (6) — per-scene sound effects in the render and the CapCut export. Off by
    # default for every tier: they did not sound natural.
    SFX_ENABLED: bool = False
    # P-AUTH (S6) — same ENV var as src/config.py: allow the process-memory repositories.
    ALLOW_IN_MEMORY_STORE: bool = False
    # P-AUTH (S8, F4, F8) — server-side caps and the interim per-tenant cost bound, applied
    # to every tenant except the owner's. Replaced by the credit ledger in P-BILL-1.
    CAP_SCRIPT_WORDS: int = 1200
    CAP_PROMPT_CHARS: int = 8000
    CAP_STYLE_CHARS: int = 4000
    CAP_CHARACTER_CHARS: int = 3000
    CAP_RUNS_PER_DAY: int = 10
    CAP_DAILY_SPEND_USD: float = 5.0
    CAP_CONCURRENT_RENDERS: int = 1
    RENDER_MAX_CONCURRENT: int = 2
    CAP_STORAGE_MB: int = 2048
    # Estimated dollars of one paid call that has no exact price (LLM, TTS, a prompt rewrite).
    EST_LLM_CALL_USD: float = 0.05
    EST_TTS_CALL_USD: float = 0.05
    # One server render. Non-zero so the render action has a price (the page shows the same figure the hold takes).
    EST_RENDER_USD: float = 0.05
    EST_TRANSCRIPTION_USD: float = 0.05
    # One niche -> ideas run: three LLM calls (the discovery sources are free).
    EST_IDEAS_USD: float = 0.15
    # P-BILL-1 (D123) — credits. Off by default: the ledger then only records what each paid
    # action would cost (metering) and no balance is held or refused. One credit is
    # CREDIT_VALUE_USD of price; price = raw provider cost x CREDIT_MARKUP, rounded up.
    BILLING_ENABLED: bool = False
    CREDIT_VALUE_USD: float = 0.01
    CREDIT_MARKUP: float = 2.0
    # Credits a new account gets once at its first sign-in (0: the owner tops accounts up).
    SIGNUP_CREDITS: int = 200
    # A credit hold still open after this many minutes is refundable by the owner (the job never finished).
    BILLING_HOLD_TTL_MINUTES: int = 120
    # P-AUTH (S9, D115) — the moderation gate. "block" refuses a flagged text, "log" only
    # records it. MODERATION_BLOCKLIST is extra comma-separated phrases, case-insensitive.
    MODERATION_MODE: str = "block"
    # "local" runs only the built-in rules; "openai" adds OpenAI's free moderation endpoint
    # (uses OPENAI_API_KEY). A provider outage never blocks generation.
    MODERATION_PROVIDER: str = "local"
    MODERATION_MODEL: str = "omni-moderation-latest"
    MODERATION_BLOCKLIST: str = ""
    DEEPGRAM_API_KEY: str = ""
    # Same ENV var names as src/config.py — reused by the native AcquisitionWorker (P9-S3).
    PEXELS_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""
    # Same ENV var names as src/config.py — reused by the native RenderWorker (P9-S4).
    FFMPEG_TIMEOUT_SECONDS: int = 1800
    COLOR_GRADE_PRESET: str = "neutral"
    BLUR_FILL_ENABLED: bool = True
    # -threads cap per concurrent per-scene libx264 encoder (D090). Same ENV var
    # name and default as src/config.py's Settings.FFMPEG_SCENE_THREADS.
    FFMPEG_SCENE_THREADS: int = 2
    # Shortest scene the operator may create by splitting or moving a boundary
    # in Studio (P13-S2 / P13-S4). Scenes the storyboard generator produced are
    # not checked against it.
    STORYBOARD_MIN_SCENE_S: float = 1.0
    # Largest .mp4 the operator may upload as a run's final video — the video rendered
    # in CapCut (P13b-S4, D100).
    OUTPUT_UPLOAD_MAX_MB: int = 500
    # Uploaded voiceover (P14b). Size cap, length window, the mean word confidence
    # below which Studio warns that the audio may not be in the run's language, and
    # the per-minute Deepgram price used for the TraceEvent cost estimate.
    VOICE_UPLOAD_MAX_MB: int = 50
    VOICE_UPLOAD_MIN_S: float = 3.0
    VOICE_UPLOAD_MAX_S: float = 180.0
    VOICE_LOW_CONFIDENCE: float = 0.6
    DEEPGRAM_COST_PER_MIN_USD: float = 0.0043
    # AI image generation (P14, D096, D104). Provider, model and key are tenant
    # settings first; these are the fallbacks and the tunables.
    SETTINGS_ENCRYPTION_KEY: str = ""
    IMAGE_PROVIDER: str = "kie"
    KIE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    KIE_IMAGE_MODEL: str = "gpt-image-2-text-to-image"
    OPENAI_IMAGE_MODEL: str = "gpt-image-1"
    # Default OpenAI model for text generation (the Thinking models block, P-INT1).
    OPENAI_LLM_MODEL: str = "gpt-4.1-mini"
    IMAGE_QUALITY: str = "medium"
    IMAGE_RESOLUTION: str = "1K"
    IMAGE_DEFAULT_ASPECT_RATIO: str = "9:16"
    IMAGE_TIMEOUT_S: int = 180
    IMAGE_POLL_INTERVAL_S: float = 3.0
    IMAGE_COST_USD: float = 0.03
    IMAGE_RUN_SPEND_CAP_USD: float = 2.0
    # Which prompt the Realistic (stock) storyboard worker uses: "v0.17" (default) or
    # "v0.18" (Visual Director method on Sonnet 5.5) — switch after the side-by-side test.
    STORYBOARD_STOCK_PROMPT_VERSION: str = "v0.17"
    # Animation mode (P-AN1, D108). Per-model image prices as a JSON object
    # (model id -> dollars) — a model without an entry costs IMAGE_COST_USD. The
    # highest cap the operator may set for one run from the Generate all dialog, and
    # how many images the bulk job generates at once.
    # Default: kie.ai's Nano Banana 2.1 at 1K (kie.ai price page, checked 2026-10-11;
    # 2K is 0.03 and 4K 0.045 — change the entry when IMAGE_RESOLUTION changes).
    # gpt-image-1 (OpenAI direct, medium, 1024x1536): 14 images cost $0.92 on the
    # operator's OpenAI bill in the P-AN1 smoke test — the general 0.03 undercounted it.
    IMAGE_MODEL_COSTS_USD: dict[str, float] = {"nano-banana-2-1": 0.02, "gpt-image-1": 0.066}
    IMAGE_RUN_SPEND_CAP_MAX_USD: float = 10.0
    IMAGE_JOB_CONCURRENCY: int = 3


def get_platform_settings() -> PlatformSettings:
    """Return a validated PlatformSettings instance."""
    return PlatformSettings()
