# Architecture — Content Factory

## System overview

Content Factory is a sequential pipeline where each step is an independent HTTP endpoint on a single FastAPI service hosted on Railway. Steps are triggered manually by the operator via a minimal web UI. State is persisted to Google Drive after each step.

```
Operator UI (browser)
       │
       ▼
FastAPI service (Railway)
       │
       ├── POST /runs                    → creates run folder in Drive
       ├── POST /runs/{id}/storyboard    → calls Claude API, saves storyboard.json
       ├── POST /runs/{id}/manifest      → parses storyboard, saves asset_manifest.json
       ├── POST /runs/{id}/assets        → acquires assets (Pexels → Replicate fallback)
       ├── POST /runs/{id}/ffmpeg-script → generates ffmpeg_script.sh
       ├── POST /runs/{id}/render        → executes FFmpeg, uploads output
       └── POST /runs/{id}/voiceover     → accepts .mp3 upload from operator
              │
              ▼
       Google Drive (per-run folder)
```

## Data flow

```
Plain-text VO script
       │
       ▼  [E1] Claude API (prompt v0.4)
storyboard.json
       │
       ▼  [E2] manifest builder
asset_manifest.json
       │
       ▼  [E3] Pexels API / Replicate/Flux
assets in /images, /video, /sfx
       │
       ▼  [E4] FFmpeg script generator
ffmpeg_script.sh
       │
       ▼  [E5] FFmpeg (on Railway) + voiceover.mp3 (operator upload) + music track
final video in /output
```

## Component map

| Component | File | Responsibility |
|-----------|------|---------------|
| App entry point | `src/main.py` | FastAPI app, router registration, startup validation |
| Config / ENV | `src/config.py` | pydantic-settings Settings, all ENV vars |
| Schemas | `src/models.py` | All Pydantic models: RunLog, Storyboard, Manifest, etc. |
| Drive client | `src/drive.py` | Auth, folder creation, file upload/download, run_log helpers |
| Storyboard | `src/storyboard.py` | Claude API call, response parsing, validation |
| Manifest | `src/manifest.py` | Parse storyboard scenes → AssetManifest |
| Pexels | `src/pexels.py` | Stock footage/image queries |
| Replicate | `src/replicate_client.py` | Flux image generation, async polling |
| Acquisition | `src/acquisition.py` | Per-scene fallback orchestration |
| FFmpeg builder | `src/ffmpeg_builder.py` | Generate ffmpeg_script.sh |
| Renderer | `src/renderer.py` | Download assets, run FFmpeg, upload output |
| Operator UI | `src/static/` | HTML/JS, served by FastAPI |

## Checkpointing

`run_log.json` tracks each step's status. Structure:

```json
{
  "run_id": "2026-05-21_housing-affordability-crisis",
  "created_at": "2026-05-21T10:00:00Z",
  "steps": {
    "storyboard":       {"status": "complete", "completed_at": "...", "error": null},
    "asset_manifest":   {"status": "pending",  "completed_at": null,  "error": null},
    "asset_acquisition":{"status": "pending",  "completed_at": null,  "error": null},
    "ffmpeg_script":    {"status": "pending",  "completed_at": null,  "error": null},
    "render":           {"status": "pending",  "completed_at": null,  "error": null}
  }
}
```

On restart, pipeline resumes from the first step that is not `complete`.

## Drive folder structure

```
/Content Factory              ← GOOGLE_DRIVE_ROOT_ID (PROD)
  /music-library              ← shared, operator-managed
  /runs
    /2026-05-21_housing-affordability-crisis/
      storyboard.json
      asset_manifest.json
      run_log.json
      run_log.txt
      ffmpeg_script.sh
      /video
      /images
      /sfx
      /music                  ← copied from /music-library (first track, POC)
      /voiceover              ← operator uploads .mp3 here
      /output                 ← final rendered video
```

## Environment isolation

DEV and PROD are fully isolated Railway services pointing to separate Drive roots. No shared state between environments.
