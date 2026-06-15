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
| `REPLICATE_API_TOKEN` | Yes | Replicate API token for Flux AI image generation. |
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
| `CLIP_RERANK_ENABLED` | No | Enable CLIP semantic reranking of Pexels results (E4-S4). Loads a ~340MB model at startup. Default: `False`. |
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

> Discovery may optionally use `praw`/`pytrends` instead of raw httpx — only if pragmatic, and only with a DECISIONS.md entry. X/Twitter is intentionally excluded (free-tier constraint); added later via Apify.

---

## How to set in Railway
1. Go to your Railway service → Variables tab
2. Add each variable
3. Set DEV and PROD services independently — they must point to different R2 buckets
