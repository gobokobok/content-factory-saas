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
| `FFMPEG_TIMEOUT_SECONDS` | No | Max seconds to wait for FFmpeg subprocess to complete. Default: `300`. |
| `CLIP_RERANK_ENABLED` | No | Enable CLIP semantic reranking of Pexels results (E4-S4). Loads a ~340MB model at startup. Default: `False`. |
| `DEEPGRAM_API_KEY` | No* | Deepgram API key for word-level timestamp extraction (E5-S4). If unset, alignment step falls back to proportional distribution. |
| `ELEVENLABS_API_KEY` | No* | ElevenLabs API key for TTS voiceover generation (S10-S1). Required when operator uses "Generate Voiceover" mode. |
| `ELEVENLABS_VOICE_ID` | No* | ElevenLabs voice ID to use for TTS generation (S10-S1). Find IDs at elevenlabs.io/voice-library. |
| `STORYBOARD_CHUNK_SIZE` | No | Max paragraphs per storyboard chunk (S13-S1). Scripts exceeding this are split and sent to Claude in parallel. Default: `10`. |
| `ACQUISITION_BATCH_SIZE` | No | Max concurrent asset acquisition calls per batch (S13-S2). Higher values reduce wall-clock time for large manifests. Default: `20`. |

---

## How to set in Railway
1. Go to your Railway service → Variables tab
2. Add each variable
3. Set DEV and PROD services independently — they must point to different R2 buckets
