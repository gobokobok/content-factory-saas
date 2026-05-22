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
| `CLAUDE_MODEL` | No | Claude model ID for storyboard generation. Default: `claude-sonnet-4-6`. |

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

---

## How to set in Railway
1. Go to your Railway service → Variables tab
2. Add each variable
3. Set DEV and PROD services independently — they must point to different R2 buckets
