# Environment Variables

All variables must be set in Railway for DEV and PROD environments.
Local development uses `.env.local` (never committed).

See DECISIONS.md D021 for why Cloudflare R2 was chosen over Google Drive.

---

## Core

| Variable | Required | Description |
|----------|----------|-------------|
| `ENVIRONMENT` | Yes | `dev` or `prod`. Controls logging. |
| `PORT` | Railway-set | Set automatically by Railway. Do not override. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`. Default: `INFO`. |

---

## Cloudflare R2 storage

| Variable | Required | Description |
|----------|----------|-------------|
| `R2_ACCOUNT_ID` | Yes | Cloudflare Account ID (found in R2 dashboard, top-right). |
| `R2_ACCESS_KEY_ID` | Yes | R2 API token Access Key ID. |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 API token Secret Access Key. |
| `R2_BUCKET_NAME` | Yes | R2 bucket name. DEV: `content-factory-dev`. PROD: `content-factory`. |

### One-time setup to get R2 credentials
1. Create a [Cloudflare account](https://cloudflare.com) if you don't have one
2. Go to **R2 → Create bucket** — name it `content-factory-dev` (DEV) or `content-factory` (PROD)
3. Go to **R2 → Manage R2 API Tokens → Create API Token**
   - Permissions: **Object Read & Write**
   - Bucket: select your bucket
   - Click **Create API Token**
4. Copy **Account ID**, **Access Key ID**, and **Secret Access Key** into Railway Variables

---

## Operator auth

| Variable | Required | Description |
|----------|----------|-------------|
| `OPERATOR_PASSWORD` | Yes | Password for the operator UI login (S5-S5). |
| `SESSION_SECRET_KEY` | Yes | HMAC key that signs the session cookie. Any long random string. |
| `AUTH_SECRET_MIN_LENGTH` | No | Shortest `OPERATOR_PASSWORD` / `SESSION_SECRET_KEY` the app starts with; a shorter or empty value stops start-up (F7). Default: `12`. |
| `COOKIE_ALLOW_INSECURE` | No | Set `true` only for plain-http local development. The session cookie is `Secure` otherwise, on DEV as well as PROD (F18). Default: `false`. |
| `TRUST_PROXY_HEADERS` | No | Key the login lockout on the right-most `X-Forwarded-For` entry (Railway's proxy) instead of the proxy's own address (F14). Default: `true`. |
| `LEGACY_ROUTES_ENABLED` | No | `true` mounts `/legacy` and the legacy pipeline routes (`/runs` list, drafts, downloads, upload URLs, the per-step routes). Off by default (F3, F10); Studio's run delete and run-settings routes stay on. |
| `LOGIN_MAX_ATTEMPTS` | No | Failed logins per IP before a 429 block. Default: `5`. |
| `LOGIN_ATTEMPT_WINDOW_SECONDS` | No | Rate-limit window in seconds. Default: `900`. |

---

## AI — Claude API

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude storyboard generation. |
| `CLAUDE_MODEL` | No | Claude model ID for storyboard generation (GENERATE task). Default: `claude-sonnet-4-6`. |
| `MODEL_VALIDATE` | No | Claude model for storyboard schema validation (VALIDATE task). Default: `claude-haiku-4-5-20251001`. |
| `MODEL_SUMMARIZE` | No | Claude model for run log summarization (SUMMARIZE task). Default: `claude-haiku-4-5-20251001`. |
| `MODEL_TRANSFORM` | No | Claude model for structured data transformation (TRANSFORM task — reserved). Default: `claude-haiku-4-5-20251001`. |
| `MODEL_REASON` | No | Claude model for complex reasoning tasks (REASON task — reserved). Default: `claude-sonnet-4-6`. |

---

## Asset APIs

| Variable | Required | Description |
|----------|----------|-------------|
| `PEXELS_API_KEY` | Yes | Pexels API key for stock footage/image queries. |
| `PIXABAY_API_KEY` | No* | Pixabay API key for second stock source (D063). Free at pixabay.com/api/docs. When absent, Pixabay is skipped silently. |
| `REPLICATE_API_TOKEN` | Yes | Replicate API token (legacy config — Replicate retired from acquisition in P8-S1 per D063). |
| `FREESOUND_API_KEY` | Yes | Freesound API key for SFX acquisition. |

---

## Pipeline config

| Variable | Required | Description |
|----------|----------|-------------|
| `PEXELS_PER_PAGE` | No | Results per Pexels query. Default: `5`. |
| `REPLICATE_FLUX_MODEL` | No | Replicate model ID for image generation. Default: `black-forest-labs/flux-schnell`. |
| `REPLICATE_POLL_INTERVAL_SECONDS` | No | Polling interval for Replicate async jobs. Default: `3`. |
| `REPLICATE_MAX_POLL_ATTEMPTS` | No | Max polling attempts before timeout. Default: `60`. |
| `FFMPEG_TIMEOUT_SECONDS` | No | Max seconds to wait for FFmpeg subprocess to complete (covers the whole script: per-scene clips, concat, captioning). Default: `1800`. |
| `FFMPEG_SCENE_THREADS` | No | `-threads` cap per concurrent per-scene libx264 encoder (up to 4 run in parallel — see `_MAX` in `_scene_section`). Left unset, libx264 auto-detects the host's full CPU count per process, which can starve the other concurrent encodes on a resource-limited container (D090). Default: `2`. |
| `STORYBOARD_MIN_SCENE_S` | No | Shortest scene (seconds of voiceover) the operator may create by splitting a scene or moving a boundary in Studio (P13). Scenes produced by storyboard generation are not checked against it. Default: `1.0`. |
| `OUTPUT_UPLOAD_MAX_MB` | No | Largest `.mp4` (in MB) the operator may upload as a run's final video — the video rendered in CapCut (P13b-S4, D100). The upload is read into memory before it is stored, so keep it below the container's RAM headroom. Default: `500`. |
| `VOICE_UPLOAD_MAX_MB` | No | Largest voiceover file (in MB) the operator may upload to an "Upload voiceover" run (P14b-S1). The file is read into memory before it is stored. Default: `50`. |
| `VOICE_UPLOAD_MIN_S` | No | Shortest uploaded voiceover (seconds) accepted after Deepgram has measured it (P14b-S4). Default: `3`. |
| `VOICE_UPLOAD_MAX_S` | No | Longest uploaded voiceover (seconds) accepted (P14b-S4). Default: `180`. |
| `VOICE_LOW_CONFIDENCE` | No | Mean Deepgram word confidence below which an uploaded voiceover gets a "may not be in this run's language" warning in Studio (P14b-S4). A warning only — the transcript is kept. Default: `0.6`. |
| `DEEPGRAM_COST_PER_MIN_USD` | No | Deepgram Nova-2 price per audio minute, used only for the cost shown in the upload's TraceEvent (P14b-S1). Default: `0.0043`. |
| `SETTINGS_ENCRYPTION_KEY` | P14 | Fernet key that encrypts tenant-level API keys stored in Postgres (D104). Generate once with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and never change it — keys saved under the old value become unreadable. Without it the Settings page cannot save a key (the Railway keys below still work). **Required when `ENVIRONMENT=prod`:** the app refuses to start without it (F7). |
| `IMAGE_PROVIDER` | No | Fallback image provider when the tenant has not chosen one: `kie` or `openai`. Default: `kie`. |
| `KIE_API_KEY` | No | kie.ai key, fallback when the tenant has not saved one in Settings (D096, D104). |
| `OPENAI_API_KEY` | No | OpenAI key, fallback when the tenant has not saved one in Settings. |
| `KIE_IMAGE_MODEL` / `OPENAI_IMAGE_MODEL` | No | Default model per provider. Defaults: `nano-banana-2-1` / `gpt-image-1`. A model saved in Settings wins. `gpt-image-2-text-to-image` is the expensive one: use it only by choice. |
| `IMAGE_QUALITY` | No | OpenAI quality tier (`low` / `medium` / `high`). Default: `medium`. |
| `IMAGE_RESOLUTION` | No | kie.ai resolution (`1K` / `2K` / `4K`). Default: `1K`. |
| `IMAGE_DEFAULT_ASPECT_RATIO` | No | Aspect used when the run has no `settings.json`. Default: `9:16`. |
| `IMAGE_TIMEOUT_S` / `IMAGE_POLL_INTERVAL_S` | No | How long one generation may take and how often kie.ai is polled. Defaults: `180` / `3`. |
| `IMAGE_COST_USD` | No | Estimated cost of one generated image on a model that has no entry in `IMAGE_MODEL_COSTS_USD`, used for the cost display and the cap. Not read from the provider. Default: `0.03`. |
| `IMAGE_RUN_SPEND_CAP_USD` | No | Per-run spend cap for generated images; at the cap Generate is refused. Default: `2.00`. |
| `STORYBOARD_STOCK_PROMPT_VERSION` | No | Prompt of the Realistic (stock) storyboard worker: `v0.17` (default) or `v0.18` (Visual Director method, Sonnet 5.5, adaptive thinking). Switch only after the side-by-side test (D111). |
| `OPENAI_LLM_MODEL` | No | Model OpenAI uses for text generation when it is the default of the Thinking models block (YouTube metadata today). Default: `gpt-4.1-mini`. |
| `IMAGE_MODEL_COSTS_USD` | No | Estimated price of one image per model, as a JSON object (`{"nano-banana-2-1": 0.02}`). Used for the cost shown before generating, the spend cap and the ledger. A model without an entry costs `IMAGE_COST_USD`. Default: `{"nano-banana-2-1": 0.02, "gpt-image-1": 0.066}` — kie.ai's Nano Banana 2.1 price at 1K, checked 2026-10-11 (2K is 0.03, 4K 0.045: change the entry when `IMAGE_RESOLUTION` changes); OpenAI's `gpt-image-1` at medium quality, measured on the operator's bill in the P-AN1 smoke test (14 images, $0.92). Setting the variable replaces the whole table. |
| `IMAGE_RUN_SPEND_CAP_MAX_USD` | No | The highest AI image cap the operator may set for one run from the Generate all images dialog (P-AN1, D108). The run's own cap is stored in its `settings.json` and wins over the tenant default. Default: `10.00`. |
| `IMAGE_JOB_CONCURRENCY` | No | How many images the Generate all images job generates at once. Default: `3`. |
| `CLIP_RERANK_ENABLED` | No | Enable CLIP semantic reranking of Pexels results (E4-S4). Loads a ~340MB model at startup. Default: `False`. |
| `COLOR_GRADE_PRESET` | No | FFmpeg colour grade applied to the final render (P8-S6). Options: `neutral` (no change), `vivid`, `warm`, `cinematic`, `muted`. Default: `neutral`. |
| `BLUR_FILL_ENABLED` | No | When `true` (default), landscape still images use blur-fill compositing (blurred full-frame behind, sharp subject scaled to fit) instead of cropping. Gated on aspect ratio > 9:16 detected at render time (P8-S6). Default: `true`. |
| `DEEPGRAM_API_KEY` | No* | Deepgram API key for word-level timestamp extraction (E5-S4). If unset, alignment step falls back to proportional distribution. |
| `ELEVENLABS_API_KEY` | No* | ElevenLabs API key for TTS voiceover generation (S10-S1). Required when operator uses "Generate Voiceover" mode. |
| `ELEVENLABS_VOICE_ID` | No* | ElevenLabs voice ID to use for TTS generation (S10-S1). Find IDs at elevenlabs.io/voice-library. |
| `STORYBOARD_CHUNK_SIZE` | No | Max paragraphs per storyboard chunk (S13-S1). Scripts exceeding this are split and sent to Claude in parallel. Default: `10`. |
| `STORYBOARD_CHUNK_MAX_WORDS` | No | Max words per storyboard chunk (S13-S1). Caps output tokens per Claude call independent of paragraph density — comma-list scenes can multiply scene count well beyond what paragraph count predicts. Default: `150`. |
| `ACQUISITION_BATCH_SIZE` | No | Max concurrent asset acquisition calls per batch (S13-S2). Higher values reduce wall-clock time for large manifests. Default: `20`. |
| `ACQUISITION_PEXELS_ONLY` | No | When `true` (default), Replicate image generation is skipped for scenes whose `asset_mode` is `None`. Scenes explicitly set to `ai_generated` still use Replicate. Set to `false` only when slow AI generation is acceptable. Default: `true`. |

---

## Platform v2 (Sprints P0–P7)

New variables for the `platform/` layer. See docs/v2_platform_plan.md and DECISIONS.md D047–D057. Required-from column notes the sprint each becomes required.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | P2+ | Railway Postgres connection string — platform metadata index (D048). Lazy/fault-isolated: outage must not affect the legacy app. |
| `TELEGRAM_BOT_TOKEN` | P3+ | Telegram bot token for the trigger interface (D049). |
| `TELEGRAM_WEBHOOK_SECRET` | P3+ | Shared secret to validate inbound Telegram webhook calls (D049). |
| `TELEGRAM_ALLOWED_CHAT_IDS` | P3+ | Comma-separated Telegram chat ids allowed to trigger replies. Empty = unrestricted. Temporary single-operator allowlist ahead of S19 multi-tenant auth. |
| `REDDIT_CLIENT_ID` | P3+ | Reddit API client id — Discovery source adapter (D050). |
| `REDDIT_CLIENT_SECRET` | P3+ | Reddit API client secret (D050). |
| `REDDIT_USER_AGENT` | P3+ | Reddit API user-agent string (D050). |
| `YOUTUBE_API_KEY` | P3+ | YouTube Data API v3 key — Discovery source adapter (D050). |
| `WEB_SEARCH_API_KEY` | P5+ | Web-search provider key for the Idea→Script fact-check loop (D053). Provider chosen at P5. |
| `YT_ANALYTICS_OAUTH_CLIENT_ID` | P7+ | YouTube Analytics OAuth client id — metrics ingestion (D054). |
| `YT_ANALYTICS_OAUTH_CLIENT_SECRET` | P7+ | YouTube Analytics OAuth client secret (D054). |
| `YT_ANALYTICS_REFRESH_TOKEN` | P7+ | Channel-owner refresh token for YouTube Analytics (D054). |
| `PLATFORM_DEFAULT_USER_ID` | P1+ | Default user_id for the R2 key scheme `users/{user_id}/...` until multi-tenant identity (S19) lands. |
| `HITL_TIMEOUT_SECONDS` | No | Auto-approve timeout for HITL script gate (P6-S3). `0` = wait indefinitely; positive = auto-approve after N seconds. Default: `0`. |
| `GEMINI_API_KEY` | P6-S7+ | Google AI Studio API key for Gemini 2.5 Flash TTS (D061). When absent, voice_production skips TTS and uses proportional timestamp fallback. |
| `GEMINI_TTS_VOICE` | P6-S7+ | Gemini TTS voice name (D061). Options: `Kore`, `Nova`, `Aoede`, `Zephyr`, `Puck`, `Charon`, `Fenrir`, `Orbit`, `Stella`, `Juniper`. Default (when unset): no TTS. |
| `CREATOR_VOICE_MALE` | No | Gemini TTS voice for a Creator run whose voice is "male" (D117). Default: empty, which means `GEMINI_TTS_VOICE` — the voice the channel already uses. Male is the page's default choice. |
| `CREATOR_VOICE_FEMALE` | No | Gemini TTS voice for a Creator run whose voice is "female" (D117). Default: `Kore` (a placeholder until a female voice is chosen after listening). |
| `CREATOR_PROJECT_NAME` | No | Name given to the project the Creator pages (`/create`) keep their runs in when it is first created (D117). Default: `My videos`. Renaming the project later does not create a second one. |
| `CREATOR_SCRIPT_MAX_WORDS` | No | Word limit the Creator's Script step shows and will not go past (D117). Default: `450` (about three minutes). What the page shows; the server's hard bound is `CAP_SCRIPT_WORDS` (P-AUTH S8). |
| `SFX_ENABLED` | No | Per-scene sound effects in the render and the CapCut export (D114). Default: `false` — off for every run, in the Studio too; the storyboard keeps each scene's choice, so `true` brings them back. |
| `GOOGLE_OAUTH_CLIENT_ID` | P-AUTH | Google OAuth client id (D119). Empty = Google sign-in is off and the login page shows only the operator password. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | P-AUTH | Google OAuth client secret (D119). |
| `GOOGLE_OAUTH_REDIRECT_URI` | P-AUTH | The fixed callback URL registered with Google, e.g. `https://<dev host>/auth/google/callback`. Never derived from the request. |
| `OWNER_EMAILS` | P-AUTH | Comma-separated. These Google accounts map onto the owner's legacy tenant (`operator`) and are Super — the owner keeps every run, project and key (D119). |
| `SUPER_EMAILS` | P-AUTH | Comma-separated. Super accounts with their own tenant (D118, D119). |
| `ALLOWED_EMAILS` | P-AUTH | Comma-separated Basic users who may sign in while `SIGNUP_OPEN` is false. The owner also manages a list in the Studio (Settings -> Credits -> Invited accounts, migration 0007); both count. |
| `PASSWORD_LOGIN_ENABLED` | Beta | `true` shows the operator-password login beside Google and keeps `/auth/login` working. Default `false`: Google only, `/auth/login` answers 404. Set it only as a fallback if Google sign-in is broken. |
| `SIGNUP_OPEN` | P-AUTH | `true` lets any verified Google account sign in. Default `false`. Leave false until the caps and the moderation gate are checked on DEV. |
| `SESSION_TTL_DAYS` | P-AUTH | Lifetime of a session. Default `14`. |
| `ACCEPT_LEGACY_COOKIE` | P-AUTH | Accept the pre-P-AUTH constant session cookie as the owner (F6 bridge). Default `true`; set `false` after the owner has signed in once. |
| `ALLOW_IN_MEMORY_STORE` | P-AUTH | Allow process-memory repositories when `DATABASE_URL` is empty. Default `false` — a server without a database answers 503 (S6). Only for a laptop. |
| `ALLOWED_ORIGINS` | P-AUTH | Comma-separated extra origins that may send POST / PUT / PATCH / DELETE; the site's own origin is always allowed. |
| `TERMS_VERSION` | P-AUTH | Version of the terms a first sign-in must accept (S9). Bumping it asks everyone again. Default `2026-10-22` (LEGAL-S1 rewrote the terms and added the privacy notice). |
| `ABUSE_CONTACT_EMAIL` | P-AUTH | Address "Report a problem" mails (S9, D115). Empty hides the link. |
| `LEGAL_CONTROLLER_NAME` / `LEGAL_CONTROLLER_ADDRESS` | LEGAL-S1 | Who the privacy notice and terms name as the controller and the postal address. Empty shows a "to be completed" marker and a banner on `/privacy` and `/terms`. |
| `LEGAL_CONTACT_EMAIL` | LEGAL-S1 | Where data requests (access, erasure) go. Empty falls back to `ABUSE_CONTACT_EMAIL`, then to a marker. |
| `LEGAL_GOVERNING_LAW` | LEGAL-S1 | The law and courts the terms name (a sentence, e.g. "the laws of Latvia"). Empty shows a marker. |
| `LEGAL_TRANSFER_BASIS` | LEGAL-S1 | The transfer mechanism for data sent to the US providers, as a phrase for the privacy notice (e.g. "the EU–US Data Privacy Framework or standard contractual clauses, as each provider offers"). The operator confirms it for each provider. Empty shows a marker. |
| `MINIMUM_AGE` | LEGAL-S1 | Lowest age the terms allow. Default `16`. |
| `PROMPT_LOG_RETENTION_DAYS` | LEGAL-S1 | `prompt_log` rows older than this are deleted by the retention job. Default `90`; `0` keeps them for ever. |
| `RETENTION_JOB_INTERVAL_HOURS` | LEGAL-S1 | How often the retention job runs (also once at start-up): deletes old `prompt_log` rows, expired sessions and used or expired sign-in states. Default `24`; `0` turns it off. |
| `DEMO_ACCESS_EMAIL` | login page | Address the login page's "Apply for the demo access" link mails (default: the owner's). Empty hides the link. |
| `TELEGRAM_ROUTES_ENABLED` | P-AUTH | `true` mounts the Telegram webhook. Default off (D093, S6). Read at import time. |
| `CAP_SCRIPT_WORDS` | P-AUTH | Server cap on a script's words for non-owner tenants (S8, D120). Default `1200`. |
| `CAP_PROMPT_CHARS` / `CAP_STYLE_CHARS` / `CAP_CHARACTER_CHARS` | P-AUTH | Server caps on a prompt, a master style, a character or entry description (D120). Defaults `8000` / `4000` / `3000`. |
| `CAP_RUNS_PER_DAY` | P-AUTH | New videos per tenant per UTC day (D120). Default `10`. |
| `CAP_DAILY_SPEND_USD` | P-AUTH | Estimated provider spend a tenant may reserve per UTC day (D120). Default `5.0`. The owner is exempt. |
| `EST_LLM_CALL_USD` / `EST_TTS_CALL_USD` / `EST_RENDER_USD` | P-AUTH | Estimated dollars reserved for a call with no exact price. Defaults `0.05` / `0.05` / `0.05`. **`EST_RENDER_USD` was `0` until the P-BILL-1 review fix**: a render now has a price (10 credits at the default markup), and the figure the page shows is the one the hold takes. It is a placeholder for the server's real render cost: set it from the first month's Railway CPU cost. |
| `EST_IDEAS_USD` | P-BILL-1 | Estimated dollars of one niche -> ideas run (three LLM calls; the discovery sources are free). Default `0.15`. |
| `EST_TRANSCRIPTION_USD` | P-BILL-1 | Estimated dollars of one voiceover transcription (Deepgram), held before it starts and settled at the minutes actually transcribed (`DEEPGRAM_COST_PER_MIN_USD`). Default `0.05`. |
| `BILLING_ENABLED` | P-BILL-1 | `true` charges credits (D123): a hold before every paid action, a 402 when the balance does not cover it. Default `false` — the ledger only **meters** (records what each action would cost) and nothing is held or refused. Turn it on at beta opening, after AUTH-S10 and P-CORE-S11. The owner is never charged. |
| `CREDIT_VALUE_USD` | P-BILL-1 | The price of one credit in dollars. Default `0.01`. |
| `CREDIT_MARKUP` | P-BILL-1 | Multiplier from raw provider cost to price: credits = ceil(raw x markup / `CREDIT_VALUE_USD`), at least 1 for any non-zero cost. Default `1.0` (one credit = one cent of provider cost; raise it to add a margin). Never shown to users. |
| `SIGNUP_CREDITS` | P-BILL-1 | Credits a new account gets once at first sign-in. Default `200`; `0` gives none. The owner tops accounts up from Settings -> Credits. |
| `BILLING_HOLD_TTL_MINUTES` | P-BILL-1 | A credit hold still open after this long is refundable from Settings -> Credits ("Give back stuck holds"): its job never finished (a restart). Default `120`. |
| `CAP_CONCURRENT_RENDERS` | P-AUTH | Renders one tenant may run at once (D120). Default `1`. |
| `RENDER_MAX_CONCURRENT` | Beta | Renders the whole server runs at once, across all users. Further renders wait and the page shows "Waiting for a free renderer". Default `2`. Size it to the container: each render runs up to 4 FFmpeg encodes. |
| `CAP_STORAGE_MB` | P-AUTH | Uploaded megabytes per tenant (D120). Default `2048`. |
| `MODERATION_MODE` | P-AUTH | `block` (default) refuses a flagged text; `log` records and never blocks — for tuning (D115, D120). |
| `MODERATION_PROVIDER` | P-AUTH | `local` (default) or `openai` — adds OpenAI's free moderation endpoint using `OPENAI_API_KEY`. |
| `MODERATION_MODEL` | P-AUTH | OpenAI moderation model. Default `omni-moderation-latest`. |
| `MODERATION_BLOCKLIST` | P-AUTH | Extra comma-separated phrases that are always refused (case-insensitive). |
| `DEEPGRAM_API_KEY` | P6-S7+ | Deepgram Nova-2 API key for word-level timestamp alignment (D045). When absent, voice_production falls back to proportional timestamps (confidence=0.0). |

> Discovery may optionally use `praw`/`pytrends` instead of raw httpx — only if pragmatic, and only with a DECISIONS.md entry. X/Twitter is intentionally excluded (free-tier constraint); added later via Apify.

---

## How to set in Railway
1. Go to your Railway service → Variables tab
2. Add each variable
3. Set DEV and PROD services independently — they must point to different R2 buckets
