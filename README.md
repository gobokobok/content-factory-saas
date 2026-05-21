# Content Factory

Automated content production pipeline for "The Housing Equation" — a faceless, data-driven YouTube Shorts channel about American housing economics.

## What it does

Takes a plain-text voiceover script and produces a fully assembled YouTube Short (9:16 vertical video) through a sequence of pipeline steps:

1. **Script → Storyboard** — Claude API generates scene-by-scene storyboard
2. **Storyboard → Asset Manifest** — parses scenes into asset acquisition specs
3. **Asset Acquisition** — fetches stock footage (Pexels) with AI image fallback (Replicate/Flux)
4. **FFmpeg Script Generation** — builds the assembly script
5. **FFmpeg Render** — assembles final video, uploads to Google Drive
6. **Operator UI** — trigger steps, monitor status, upload voiceover

## Setup

### Prerequisites
- Python 3.11
- A Google Cloud project with Drive API enabled and a service account
- API keys: Anthropic, Pexels, Replicate, Freesound

### Local development

```bash
bash scripts/bootstrap.sh
source .venv/bin/activate
# Fill in .env.local (see ENV.md)
uvicorn src.main:app --reload
```

Health check: `curl http://localhost:8000/health`

### Google Drive setup
1. Create a service account in GCP with Drive API enabled
2. Share your Drive folder with the service account email
3. Base64-encode the service account JSON: `base64 -i service-account.json | tr -d '\n'`
4. Add the result to `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env.local`
5. Create a folder in Drive named "Content Factory DEV" and add its ID to `GOOGLE_DRIVE_ROOT_ID`

## Deployment

| Trigger | Environment |
|---------|-------------|
| Push to `main` | DEV (Railway auto-deploy) |
| Git tag `v*.*.*` | PROD (`bash scripts/promote.sh v1.0.0`) |

Railway ENV vars must be set separately for DEV and PROD services. See ENV.md.

## Project docs

| File | Description |
|------|-------------|
| CLAUDE.md | Session bootstrap for AI-assisted development |
| BACKLOG.md | All epics and stories |
| SPRINT.md | Current sprint |
| DECISIONS.md | Architecture and dependency decisions |
| CONVENTIONS.md | Python coding standards |
| ENV.md | All environment variables |
| docs/ARCHITECTURE.md | System design |
| docs/PROMPTS.md | Storyboard generation prompt v0.4 |

## Tools

`/tools/script-generator.html` — standalone script generator (Step 2a). Open in browser, no server required.
