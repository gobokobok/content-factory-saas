# Content Factory — Backlog

---

## EPIC 1 — Script to Storyboard (Pipeline Step 2b)
Plain-text voiceover script → `storyboard.json` via Claude API (prompt v0.4)

---

## [E1-S1] Railway service skeleton
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** none

### Goal
Stand up a FastAPI service on Railway with a health check endpoint and startup ENV validation so every subsequent story has a working, deployable foundation.

### Acceptance Criteria
- [ ] FastAPI app runs locally with `uvicorn`
- [ ] `GET /health` returns `{"status": "ok", "environment": "<env>"}` with HTTP 200
- [ ] On startup, app validates all required ENV vars are present; crashes with a clear error if any are missing
- [ ] `railway.toml` and `railway.prod.toml` configured for DEV and PROD
- [ ] Service deploys to Railway DEV and health check passes

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Hit `GET /health` on Railway DEV URL. Confirm 200 response with correct environment value. Check Railway logs for clean startup with no ENV errors.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- ENV.md
- docs/TECH_STACK.md

### Files to create or modify
- `src/main.py` — FastAPI app entry point
- `src/config.py` — ENV validation using pydantic-settings
- `requirements.txt` — dependencies
- `railway.toml`
- `railway.prod.toml`
- `tests/test_health.py`

### Handover
- `src/config.py` — `Settings` class (pydantic-settings) validates all 7 required ENV vars at startup: `ENVIRONMENT`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_ROOT_ID`, `ANTHROPIC_API_KEY`, `PEXELS_API_KEY`, `REPLICATE_API_TOKEN`, `FREESOUND_API_KEY`. Import and inject via `Depends(get_settings)` in all routes.
- `src/main.py` — FastAPI app with lifespan startup hook. `GET /health` returns `{"status":"ok","environment":"<env>"}`. All future routes registered here via `app.include_router()`.
- `tests/test_health.py` — 13 passing tests. Pattern for injecting settings in tests: `app.dependency_overrides[get_settings] = lambda: settings`; use `monkeypatch.delenv()` to isolate ENV vars.
- Railway DEV live at `content-factory-dev-production.up.railway.app`. All 8 ENV vars set in Railway Variables tab.
- No new issues promoted to backlog.

---

## [E1-S2] Google Drive integration
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** in-progress
**Priority:** high
**Depends on:** E1-S1

### Goal
Authenticate with Google Drive via service account, create a run folder with the correct subfolder structure, and initialize `run_log.json` so the pipeline has a persistent storage layer before any content is generated.

### Acceptance Criteria
- [ ] Drive client authenticates using `GOOGLE_SERVICE_ACCOUNT_JSON` ENV var (base64-encoded JSON)
- [ ] `POST /runs` accepts `{"slug": "housing-affordability-crisis"}` and creates `/{YYYY-MM-DD}_{slug}/` under `GOOGLE_DRIVE_ROOT_ID/runs/`
- [ ] All required subfolders created: `/video`, `/images`, `/sfx`, `/music`, `/voiceover`, `/output`
- [ ] `run_log.json` initialized in run folder with all pipeline steps set to `pending`
- [ ] Endpoint returns `{"run_id": "2026-05-21_housing-affordability-crisis", "drive_folder_id": "<id>"}`
- [ ] Run folder is isolated per environment (DEV vs PROD Drive roots)

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing (mock Drive API in tests)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Call `POST /runs` with a test slug via the DEV URL. Verify folder appears in Google Drive DEV root with correct structure. Open `run_log.json` and confirm all steps show `pending`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- ENV.md
- docs/ARCHITECTURE.md
- `src/config.py`

### Files to create or modify
- `src/drive.py` — Drive client, folder creation, run_log helpers
- `src/models.py` — RunLog schema, StepStatus enum
- `src/routes/runs.py` — POST /runs endpoint
- `src/main.py` — register runs router
- `tests/test_drive.py`
- `tests/test_runs.py`

### Handover
- `src/exceptions.py`: `DriveError` — base exception for all Drive failures. Import and catch in routes.
- `src/models.py`: `StepStatus` enum, `StepLog`, `RunLog` (run_log.json schema), `RunCreateRequest` (slug validation), `RunCreateResponse`. `PIPELINE_STEPS` tuple defines the canonical step order.
- `src/drive.py`: `DriveClient` class — init from base64 SA JSON, `create_run_folder(slug, root_folder_id)` → `(run_id, folder_id)`, `upload_json(data, filename, folder_id)` → file ID. `_build_run_log(run_id)` helper (module-level). Idempotent: reuses existing folders by name via `_get_or_create_folder`.
- `src/routes/runs.py`: `POST /runs` — validates slug, instantiates `DriveClient`, returns 201 `{run_id, drive_folder_id}` or 500 on `DriveError`.
- `src/main.py`: `runs_router` registered via `app.include_router()`.
- `tests/test_drive.py` + `tests/test_runs.py`: 30 new tests, all passing. Drive API fully mocked via `unittest.mock.patch`.
- All 43 tests passing (13 from E1-S1, 30 new).

---

## [E1-S3] Storyboard generation
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** backlog
**Priority:** high
**Depends on:** E1-S2

### Goal
Call the Claude API with the v0.4 storyboard prompt, parse the response into a validated `storyboard.json`, upload it to the run folder in Drive, and update `run_log.json` to mark the step complete or failed.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/storyboard` accepts `{"script": "<plain text VO script>"}`
- [ ] Calls Claude API using prompt v0.4 from `docs/PROMPTS.md` as system prompt
- [ ] Parses and validates response as `storyboard.json` (schema defined in `src/models.py`)
- [ ] Uploads `storyboard.json` to the run's Drive folder
- [ ] Updates `run_log.json`: step `storyboard` → `complete` (or `failed` with error message)
- [ ] Returns `{"status": "complete", "storyboard_url": "<drive_file_id>"}` on success
- [ ] On Claude API error or parse failure: step marked `failed`, error logged, HTTP 500 returned

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing (mock Claude API)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
POST a real VO script to `/runs/{run_id}/storyboard` on DEV. Verify `storyboard.json` appears in Drive. Open file and spot-check scene structure. Confirm `run_log.json` shows `storyboard: complete`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- docs/PROMPTS.md — v0.4 prompt (full text required)
- `src/drive.py`
- `src/models.py`

### Files to create or modify
- `src/storyboard.py` — Claude API call, response parsing, validation
- `src/routes/storyboard.py` — POST /runs/{run_id}/storyboard
- `src/main.py` — register storyboard router
- `src/models.py` — storyboard schema additions
- `tests/test_storyboard.py`

### Handover
_filled on completion_

---

## EPIC 2 — Storyboard to Asset Manifest (Pipeline Step 3)
Parse `storyboard.json` scenes → `asset_manifest.json` with one asset spec per scene

---

## [E2-S1] Asset manifest generation
**Epic:** E2 — Storyboard to Asset Manifest
**Sprint:** 2
**Status:** backlog
**Priority:** high
**Depends on:** E1-S3

### Goal
Parse a completed `storyboard.json` from Drive and produce an `asset_manifest.json` that lists every scene's asset requirements (type, queries, generation prompt) before acquisition begins.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/manifest` reads `storyboard.json` from the run's Drive folder
- [ ] For each scene, outputs a manifest entry: `{scene_id, clip_type, primary_query, fallback_query, ai_generate_prompt, status: "pending"}`
- [ ] Uploads `asset_manifest.json` to run folder
- [ ] Updates `run_log.json`: step `asset_manifest` → `complete`
- [ ] Returns manifest summary (scene count, clip type breakdown)

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
POST to `/runs/{run_id}/manifest` on DEV using a run with a completed storyboard. Verify `asset_manifest.json` in Drive has one entry per scene. Confirm all statuses are `pending`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- `src/models.py`
- `src/drive.py`

### Files to create or modify
- `src/manifest.py` — storyboard parser, manifest builder
- `src/routes/manifest.py` — POST /runs/{run_id}/manifest
- `src/main.py` — register manifest router
- `src/models.py` — AssetManifest, ManifestEntry schemas
- `tests/test_manifest.py`

### Handover
_filled on completion_

---

## EPIC 3 — Asset Acquisition (Pipeline Step 4)
For each scene: Pexels primary → Pexels fallback → Replicate/Flux AI generation. Download to Drive.

---

## [E3-S1] Pexels stock footage integration
**Epic:** E3 — Asset Acquisition
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E2-S1

### Goal
Query Pexels with primary and fallback search terms for each scene, download the best match to the correct Drive subfolder, and update the manifest entry with the result.

### Acceptance Criteria
- [ ] Pexels client queries videos/photos using `primary_query`; falls back to `fallback_query` if no result
- [ ] Downloads asset to `/images` or `/video` subfolder depending on clip_type
- [ ] Updates `asset_manifest.json` entry: `{source: "pexels", file_path: "<drive_path>", status: "acquired"}`
- [ ] Handles Pexels rate limits gracefully (retry with backoff)

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing (mock Pexels API)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Run asset acquisition on a 3-scene test manifest. Verify files appear in Drive `/images` or `/video`. Check manifest entries show `source: pexels`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- `src/models.py`
- `src/drive.py`

### Files to create or modify
- `src/pexels.py` — Pexels API client
- `tests/test_pexels.py`

### Handover
_filled on completion_

---

## [E3-S2] Replicate/Flux AI image generation fallback
**Epic:** E3 — Asset Acquisition
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E3-S1

### Goal
When both Pexels queries return no result, generate an image via Replicate/Flux using the scene's `ai_generate_prompt`, download it to Drive `/images`, and update the manifest.

### Acceptance Criteria
- [ ] Replicate client calls Flux model with `ai_generate_prompt`
- [ ] Polls for completion (async generation)
- [ ] Downloads generated image to run `/images` folder
- [ ] Updates manifest entry: `{source: "replicate", file_path: "<drive_path>", status: "acquired"}`
- [ ] Handles Replicate API errors gracefully

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing (mock Replicate API)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Force Pexels to return no results for a scene. Confirm Replicate is called and image appears in Drive `/images`. Check manifest shows `source: replicate`.

### Files to read
- `src/pexels.py`
- `src/models.py`
- `src/drive.py`

### Files to create or modify
- `src/replicate_client.py` — Replicate/Flux client
- `tests/test_replicate_client.py`

### Handover
_filled on completion_

---

## [E3-S3] Asset acquisition orchestrator
**Epic:** E3 — Asset Acquisition
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E3-S1, E3-S2

### Goal
Wire Pexels and Replicate into a single acquisition loop that processes every scene in the manifest, handles the fallback chain, and exposes a single endpoint to trigger the full acquisition step.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/assets` processes all `pending` scenes in `asset_manifest.json`
- [ ] Per-scene fallback chain: Pexels primary → Pexels fallback → Replicate/Flux
- [ ] Skips scenes already marked `acquired` (idempotent / resumable)
- [ ] Updates `run_log.json`: step `asset_acquisition` → `complete` or `failed`
- [ ] Returns summary: `{acquired: N, failed: N, sources: {pexels: N, replicate: N}}`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
POST to `/runs/{run_id}/assets` on DEV. Verify all scenes acquired. Check Drive folders. Review `run_log.json` for `complete` status.

### Files to create or modify
- `src/acquisition.py` — orchestration logic
- `src/routes/assets.py` — POST /runs/{run_id}/assets
- `src/main.py` — register assets router
- `tests/test_acquisition.py`

### Handover
_filled on completion_

---

## EPIC 4 — FFmpeg Script Generation (Pipeline Step 5)
`storyboard.json` + `asset_manifest.json` → `ffmpeg_script.sh`

---

## [E4-S1] FFmpeg script generator
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E3-S3

### Goal
Read the storyboard and asset manifest from Drive and generate a valid `ffmpeg_script.sh` that assembles all assets (video clips, images, voiceover, music, SFX) into a 9:16 Short.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/ffmpeg-script` reads storyboard and manifest from Drive
- [ ] Generates `ffmpeg_script.sh` with correct clip durations from storyboard
- [ ] Handles `hard_cut`, `still_with_motion`, and `animated` clip types
- [ ] Mixes voiceover + music + SFX audio tracks
- [ ] Outputs 9:16 vertical format (1080×1920)
- [ ] Uploads `ffmpeg_script.sh` to run folder
- [ ] Updates `run_log.json`: step `ffmpeg_script` → `complete`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing (validate script syntax)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Generate script for a test run. Manually inspect `ffmpeg_script.sh` in Drive. Verify clip count matches storyboard scene count and durations are correct.

### Files to create or modify
- `src/ffmpeg_builder.py` — script generation logic
- `src/routes/ffmpeg_script.py` — POST /runs/{run_id}/ffmpeg-script
- `src/main.py` — register route
- `tests/test_ffmpeg_builder.py`

### Handover
_filled on completion_

---

## EPIC 5 — FFmpeg Execution + Drive Upload (Pipeline Step 6)
Execute `ffmpeg_script.sh` on Railway, upload final video to Drive `/output`

---

## [E5-S1] FFmpeg execution and output upload
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E4-S1

### Goal
Download all assets from Drive to a Railway temp directory, execute `ffmpeg_script.sh`, and upload the output video back to Drive `/output`, then clean up temp files.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/render` downloads all assets from Drive to `/tmp/{run_id}/`
- [ ] Downloads and executes `ffmpeg_script.sh`
- [ ] Captures FFmpeg stdout/stderr and appends to `run_log.txt`
- [ ] Uploads output video to Drive `/output`
- [ ] Cleans up `/tmp/{run_id}/` after upload
- [ ] Updates `run_log.json`: step `render` → `complete` or `failed`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Trigger render on a fully assembled test run on DEV. Wait for completion. Verify video appears in Drive `/output`. Check `run_log.txt` for FFmpeg output. Watch the video.

### Files to create or modify
- `src/renderer.py` — download assets, run FFmpeg, upload output
- `src/routes/render.py` — POST /runs/{run_id}/render
- `src/main.py` — register route
- `tests/test_renderer.py`

### Handover
_filled on completion_

---

## EPIC 6 — Operator UI (Pipeline Step 7)
HTML/JS web UI: create runs, trigger steps, upload voiceover, monitor status, view logs

---

## [E6-S0] Minimal run creation UI
**Epic:** E6 — Operator UI
**Sprint:** 1
**Status:** backlog
**Priority:** high
**Depends on:** E1-S2
**Story points:** 2

### Goal
Give a non-technical stakeholder a human-touchable artifact at the end of Sprint 1: a plain HTML form that creates a production run without curl or Postman.

### Acceptance Criteria
- [ ] Single HTML page with a slug input field and a Submit button
- [ ] On submit, calls `POST /runs` and displays the returned `run_id` and a Google Drive folder link
- [ ] Error message shown if `POST /runs` returns non-201
- [ ] No styling required — functional correctness only
- [ ] A non-technical user can create a run end-to-end without developer assistance

### Definition of Done
- [ ] All AC checked
- [ ] Served from FastAPI (`GET /` or a dedicated route)
- [ ] Manual smoke test: non-technical user creates a run, folder visible in Drive
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open the page in a browser. Enter a slug (e.g. `test-run`). Click Submit. Confirm `run_id` appears on screen. Open Google Drive and verify the folder exists.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- docs/UI_GUIDELINES.md
- `src/routes/runs.py`

### Files to create or modify
- `src/static/create-run.html` — slug form, fetch call, result display
- `src/main.py` — serve static file or add GET route

### Handover
_filled on completion_

---

## [E6-S1] UI skeleton
**Epic:** E6 — Operator UI
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Depends on:** E1-S1

### Goal
Serve a static HTML/JS operator UI from the FastAPI service that loads the run list and displays the current service health.

### Acceptance Criteria
- [ ] `GET /` serves `src/static/index.html`
- [ ] Page loads without errors in browser
- [ ] Displays service status (health check result)
- [ ] Lists existing runs (run IDs, created date) by querying `GET /runs`
- [ ] `GET /runs` endpoint returns list of run IDs from Drive

### Files to create or modify
- `src/static/index.html`
- `src/static/app.js`
- `src/static/style.css`
- `src/routes/runs.py` — add GET /runs
- `tests/test_ui_routes.py`

### Handover
_filled on completion_

---

## [E6-S2] Run creation UI
**Epic:** E6 — Operator UI
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Depends on:** E6-S1, E1-S2

### Goal
Let the operator create a new production run from the UI by entering a slug. The UI calls `POST /runs` and navigates to the new run's detail page.

### Acceptance Criteria
- [ ] "New Run" form accepts a slug string, validates no spaces or special chars
- [ ] Submits to `POST /runs`, creates Drive folder, shows success with run ID
- [ ] Navigates to run detail page after creation

### Files to create or modify
- `src/static/index.html`
- `src/static/app.js`

### Handover
_filled on completion_

---

## [E6-S3] Step trigger and status monitor
**Epic:** E6 — Operator UI
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E6-S2

### Goal
Display per-step pipeline status on the run detail page with trigger and retry buttons. Each step shows pass/fail and updates after being triggered.

### Acceptance Criteria
- [ ] Run detail page shows all 6 pipeline steps with current status (pending/complete/failed)
- [ ] Each step has a "Run" button (disabled if upstream step not complete)
- [ ] Failed steps show a "Retry" button
- [ ] Status refreshes automatically every 10 seconds
- [ ] Triggering a step calls the appropriate API endpoint

### Files to create or modify
- `src/static/run.html`
- `src/static/run.js`
- `src/routes/runs.py` — GET /runs/{run_id}/status

### Handover
_filled on completion_

---

## [E6-S4] Voiceover upload
**Epic:** E6 — Operator UI
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E6-S3

### Goal
Let the operator upload a voiceover `.mp3` directly from the UI to the run's `/voiceover` Drive folder, enabling the FFmpeg step to proceed.

### Acceptance Criteria
- [ ] File picker accepts `.mp3` only
- [ ] Uploads via `POST /runs/{run_id}/voiceover`
- [ ] Shows upload progress and confirms success
- [ ] File appears in Drive `/voiceover` subfolder
- [ ] UI marks voiceover step as complete

### Files to create or modify
- `src/static/run.html`
- `src/static/run.js`
- `src/routes/runs.py` — POST /runs/{run_id}/voiceover

### Handover
_filled on completion_

---

## [E6-S5] Inline log viewer
**Epic:** E6 — Operator UI
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Depends on:** E6-S3

### Goal
Display `run_log.txt` content inline on the run detail page, collapsible per step, so the operator can see what failed and why without leaving the UI.

### Acceptance Criteria
- [ ] Each pipeline step has a collapsible log section
- [ ] Log content fetched from `GET /runs/{run_id}/log`
- [ ] Auto-expands the most recently failed step's log
- [ ] Refreshes on status poll interval

### Files to create or modify
- `src/static/run.html`
- `src/static/run.js`
- `src/routes/runs.py` — GET /runs/{run_id}/log

### Handover
_filled on completion_

---

## EPIC 8 — Cost Optimization: Model Routing
Route pipeline tasks to the appropriate model (Haiku / Sonnet / Opus) based on task complexity to minimize API costs without sacrificing quality.

---

## [E8-S1] Haiku schema validator — storyboard.json
**Epic:** E8 — Cost Optimization
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E1-S3

### Goal
Validate `storyboard.json` against the v0.4 schema using Haiku before any downstream step runs.

### Acceptance Criteria
- [ ] Haiku called with schema from `docs/PROMPTS.md` + generated `storyboard.json`
- [ ] Returns `{valid: bool, errors: [list of field/rule violations]}`
- [ ] If invalid: step halts, errors written to `run_log.json` and `run_log.txt`
- [ ] If valid: pipeline proceeds to next step
- [ ] Haiku model string: `claude-haiku-4-5-20251001`
- [ ] Validation cost logged per run in `run_log.json`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Submit a valid storyboard — confirm pipeline proceeds. Submit a storyboard with a missing `sfx` field — confirm halt + error logged.

### Files to read
- `docs/PROMPTS.md` — schema section
- `src/storyboard.py` — E1-S3 output
- `docs/ARCHITECTURE.md` — run_log.json schema

### Files to create or modify
- `src/validators/storyboard_validator.py` — new
- `tests/test_storyboard_validator.py` — new
- `src/storyboard.py` — add validation call after generation

### Handover
_filled on completion_

---

## [E8-S2] Haiku asset manifest generator
**Epic:** E8 — Cost Optimization
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E2-S1, E8-S1

### Goal
Replace Sonnet with Haiku for asset manifest generation — pure structured transformation from storyboard scenes to asset queue entries.

### Acceptance Criteria
- [ ] Haiku receives `storyboard.json` scenes array
- [ ] Returns `asset_manifest.json` with one entry per scene: `{scene_id, primary_query, fallback_query, ai_prompt, asset_type, duration_s, motion_effect}`
- [ ] Output schema matches E3 asset acquisition input contract
- [ ] Haiku model string: `claude-haiku-4-5-20251001`
- [ ] Falls back to Sonnet if Haiku returns malformed JSON (log the fallback)

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Run with a known good `storyboard.json` — verify `asset_manifest.json` has correct entry count, all fields populated, no nulls where not allowed.

### Files to read
- `src/asset_manifest.py` — E2-S1 output
- `docs/ARCHITECTURE.md` — asset manifest schema
- `docs/PROMPTS.md` — storyboard.json schema

### Files to create or modify
- `src/asset_manifest.py` — swap model, add fallback logic
- `tests/test_asset_manifest.py` — add Haiku-specific assertions

### Handover
_filled on completion_

---

## [E8-S3] Haiku run log summarizer
**Epic:** E8 — Cost Optimization
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Depends on:** E1-S2, E6-S1

### Goal
Generate human-readable `run_log.txt` from `run_log.json` using Haiku for display in the operator UI.

### Acceptance Criteria
- [ ] Haiku receives `run_log.json`
- [ ] Returns plain English summary per step: `"Step 2b — Storyboard: Complete (14 scenes, 38s total)"` / `"Step 3 — Asset Manifest: Failed — missing sfx field in scene 03b"`
- [ ] Summary written to `run_log.txt` in Drive run folder
- [ ] UI displays `run_log.txt` inline, collapsible per step
- [ ] Called after every step completion or failure
- [ ] Haiku model string: `claude-haiku-4-5-20251001`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Complete E1-S3 on DEV — verify `run_log.txt` appears in Drive with readable step summary. Check UI displays it correctly.

### Files to read
- `src/drive.py` — E1-S2 output, Drive write utility
- `docs/ARCHITECTURE.md` — run_log.json schema
- `src/static/` — E6 operator UI output

### Files to create or modify
- `src/log_summarizer.py` — new
- `tests/test_log_summarizer.py` — new
- `src/pipeline.py` — call summarizer after each step

### Handover
_filled on completion_

---

## [E8-S4] Model router utility
**Epic:** E8 — Cost Optimization
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Depends on:** E8-S1, E8-S2, E8-S3

### Goal
Centralize model selection logic in a single utility. All Claude API calls go through the router — no hardcoded model strings scattered across modules.

### Acceptance Criteria
- [ ] `ModelRouter` class in `src/utils/model_router.py`
- [ ] Task types defined as constants: `VALIDATE`, `TRANSFORM`, `SUMMARIZE`, `GENERATE`, `REASON`
- [ ] Router maps task type to model string
- [ ] Model overridable via ENV var per task type (for testing/cost tuning)
- [ ] All existing Claude API calls refactored to use router
- [ ] Cost per call logged: model used, input tokens, output tokens, USD estimate

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Run full pipeline on DEV — verify `run_log.txt` shows correct model used per step and token counts.

### Files to read
- `src/storyboard.py`
- `src/asset_manifest.py`
- `src/validators/storyboard_validator.py`
- `src/log_summarizer.py`
- `docs/TECH_STACK.md`

### Files to create or modify
- `src/utils/model_router.py` — new
- `src/storyboard.py` — refactor model call
- `src/asset_manifest.py` — refactor model call
- `src/validators/storyboard_validator.py` — refactor model call
- `src/log_summarizer.py` — refactor model call
- `.env.example` — add `MODEL_*` override vars
- `ENV.md` — document new vars

### Handover
_filled on completion_
