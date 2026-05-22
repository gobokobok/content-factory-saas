# Environment Variables

All variables must be set in Railway for DEV and PROD environments.
Local development uses `.env.local` (never committed).

See DECISIONS.md D020 for why OAuth refresh token replaced service account JSON.

---

## Core

| Variable | Required | Description |
|----------|----------|-------------|
| `ENVIRONMENT` | Yes | `dev` or `prod`. Controls logging, Drive root folder. |
| `PORT` | Railway-set | Set automatically by Railway. Do not override. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`. Default: `INFO`. |

---

## Google Drive

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Client ID (Desktop app type) from GCP Console. |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret from GCP Console. |
| `GOOGLE_REFRESH_TOKEN` | Yes | Long-lived refresh token. Obtain once by running `python scripts/get_drive_token.py`. |
| `GOOGLE_DRIVE_ROOT_ID` | Yes | Google Drive folder ID of the environment root (`Content Factory` for PROD, `Content Factory DEV` for DEV). |

### One-time setup to get GOOGLE_REFRESH_TOKEN
1. In GCP Console → APIs & Services → Credentials, create an OAuth 2.0 Client ID (type: **Desktop app**)
2. Download or copy the Client ID and Client Secret
3. Run locally: `pip install google-auth-oauthlib && python scripts/get_drive_token.py`
4. Sign in with your Google account in the browser that opens
5. Copy the printed `GOOGLE_REFRESH_TOKEN` value into Railway Variables
6. **Publish your OAuth consent screen** (GCP → APIs & Services → OAuth consent screen → Audience → Publish App) to prevent the refresh token from expiring after 7 days

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

---

## How to set in Railway
1. Go to your Railway service → Variables tab
2. Add each variable
3. Set DEV and PROD services independently — they must point to different Drive root folders
4. Remove `GOOGLE_SERVICE_ACCOUNT_JSON` if it is still present
