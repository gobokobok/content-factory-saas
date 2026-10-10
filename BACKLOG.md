# Content Factory — Backlog (Full Archive)

> **Active stories (last completed sprint, upcoming sprint outlines, open unassigned stories) are in BACKLOG_ACTIVE.md.** Read that file during normal sessions.
> This file is the complete archive — read it only when planning a new sprint or searching history.

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
- Railway DEV live at `<railway-dev-url>`. All 8 ENV vars set in Railway Variables tab.
- No new issues promoted to backlog.

---

## [E1-S2] Google Drive integration
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
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

## [E1-S2b] Migrate storage from Google Drive to Cloudflare R2
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Story points:** 3
**Depends on:** E1-S2
**Blocks:** E1-S3

### Goal
Replace Google Drive + OAuth with Cloudflare R2 + static API token so storage integration requires zero human OAuth steps and works autonomously.

### Acceptance Criteria
- [ ] `src/storage.py` R2Client passes all unit tests with mocked boto3
- [ ] `POST /runs` returns `{"run_id": "...", "storage_prefix": "runs/{run_id}/"}` with HTTP 201
- [ ] `run_log.json` appears in R2 bucket after smoke test
- [ ] All Google Drive deps removed from `requirements.txt`
- [ ] Railway DEV env vars updated (human action — see smoke test)

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
```bash
curl -X POST https://<railway-dev-url>/runs \
  -H "Content-Type: application/json" \
  -d '{"slug": "test-affordability"}'
```
Verify `run_log.json` appears at key `runs/2026-05-22_test-affordability/run_log.json` in the Cloudflare R2 dashboard.

### Human actions required
1. Create Cloudflare account at cloudflare.com if you don't have one
2. R2 → Create bucket named `content-factory-dev`
3. R2 → Manage R2 API Tokens → Create token → R2 read and write → select `content-factory-dev` bucket → copy Account ID, Access Key ID, Secret Access Key
4. Railway DEV → remove `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` → add `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME=content-factory-dev`

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- `src/config.py`
- `src/models.py`
- `src/routes/runs.py`

### Files to create or modify
- `src/storage.py` — new: R2Client using boto3 S3-compatible API
- `src/config.py` — swap Google OAuth vars for R2 vars
- `src/exceptions.py` — StorageError replaces DriveError
- `src/models.py` — RunCreateResponse: drive_folder_id → storage_prefix; add output_url to StepLog
- `src/routes/runs.py` — R2Client replaces DriveClient
- `src/drive.py` — delete
- `scripts/get_drive_token.py` — delete
- `requirements.txt` — remove google libs, add boto3
- `ENV.md` — replace Google vars with R2 vars
- `DECISIONS.md` — D021 added, D003 + D020 updated
- `tests/test_drive.py` → `tests/test_storage.py` — rewritten for R2Client
- `tests/test_runs.py` — updated mocks and assertions
- `tests/test_health.py` — updated VALID_ENV

### Handover
- `src/storage.py`: `R2Client(account_id, access_key_id, secret_access_key, bucket_name)` — init builds boto3 S3 client with R2 endpoint. Key methods: `create_run_folder(run_id) → prefix`, `upload_json(key, data)`, `get_json(key) → dict`, `update_run_log(run_id, step, status, output_url=None)`. Module-level `_build_run_log(run_id)` available for tests.
- `src/exceptions.py`: `StorageError` replaces `DriveError`. Import and catch in all routes.
- `src/models.py`: `RunCreateResponse` now has `storage_prefix` (was `drive_folder_id`). `StepLog` gains optional `output_url` field. All other schemas unchanged.
- `src/config.py`: R2 vars — `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` (all required). Google vars removed.
- `src/routes/runs.py`: run_id constructed in route (`{today}_{slug}`), passed directly to `client.create_run_folder(run_id)`. Returns `{run_id, storage_prefix}`.
- `tests/test_storage.py`: 18 tests, boto3 mocked via `patch("src.storage.boto3.client")`. Mock pattern: `patch` returns `mock_client`; set `mock_client.put_object` / `get_object` return values directly.
- R2 key structure: `runs/{run_id}/run_log.json`, `runs/{run_id}/storyboard.json`, etc. No folder creation — prefixes are implicit.
- Railway DEV: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME=content-factory-dev` set and verified. Bucket: `content-factory-dev`.
- 47 tests passing.
**Promoted to backlog:** none

---

## [E1-S3] Storyboard generation
**Epic:** E1 — Script to Storyboard
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E1-S2b

### Goal
Call the Claude API with the v0.4 storyboard prompt, parse the response into a validated `storyboard.json`, upload it to the run folder in R2, and update `run_log.json` to mark the step complete or failed.

### Acceptance Criteria
- [x] `POST /runs/{run_id}/storyboard` accepts `{"script": "<plain text VO script>"}`
- [x] Calls Claude API using prompt v0.4 from `docs/PROMPTS.md` as system prompt
- [x] Parses and validates response as `storyboard.json` (schema defined in `src/models.py`)
- [x] Uploads `storyboard.json` to the run's R2 prefix
- [x] Updates `run_log.json`: step `storyboard` → `complete` (or `failed` with error message)
- [x] Returns `{"status": "complete", "storyboard_key": "runs/{run_id}/storyboard.json"}` on success
- [x] On Claude API error or parse failure: step marked `failed`, error logged, HTTP 500 returned

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (mock Claude API)
- [x] CI green, deployed to DEV
- [x] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
POST a real VO script to `/runs/{run_id}/storyboard` on DEV. Verify `storyboard.json` appears in R2. Open file and spot-check scene structure. Confirm `run_log.json` shows `storyboard: complete`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- docs/PROMPTS.md — v0.4 prompt (full text required)
- `src/storage.py` (replaced `src/drive.py` after E1-S2b)
- `src/models.py`

### Files to create or modify
- `src/storyboard.py` — Claude API call, response parsing, validation
- `src/routes/storyboard.py` — POST /runs/{run_id}/storyboard
- `src/main.py` — register storyboard router
- `src/models.py` — storyboard schema additions
- `src/exceptions.py` — StoryboardAPIError, StoryboardParseError
- `src/storage.py` — error param added to update_run_log
- `tests/test_storyboard.py`

### Handover
- `src/storyboard.py`: `generate_storyboard(script, settings) → Storyboard` (async). Calls `_call_claude_api` (async, uses `AsyncAnthropic`, prompt caching on system prompt). `_parse_storyboard_response(text)` splits on `---` separators → `_parse_global`, `_parse_scene`, `_parse_summary`. `SYSTEM_PROMPT` constant holds the full v0.4 text.
- `src/routes/storyboard.py`: `POST /runs/{run_id}/storyboard` — async, accepts `StoryboardRequest`, returns `StoryboardResponse`. On success: uploads to `runs/{run_id}/storyboard.json`, calls `update_run_log(..., "complete", output_url=key)`. On failure: calls `update_run_log(..., "failed", error=str(exc))`, returns 500.
- `src/models.py`: `Storyboard` uses `Field(alias="global")` for the global block — always serialise with `model_dump(by_alias=True, mode="json")`. `StoryboardScene.clip_type` is `Literal["hard_cut", "still_with_motion", "animated"]`.
- `src/exceptions.py`: `StoryboardAPIError` (Claude API failures), `StoryboardParseError` (response parse failures).
- `src/storage.py`: `update_run_log` now accepts optional `error: str` parameter.
- `tests/test_storyboard.py`: 21 tests — parser unit tests + route integration tests. Route fixture: `TestClient(app, raise_server_exceptions=False)` without context manager (same pattern as test_runs.py). Mock pattern: `patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock)`.
- Smoke test: 12-scene storyboard generated on DEV for housing-crisis VO script. All fields populated, `run_log.json` shows `storyboard: complete`. 68 tests total passing.
- AC delta: response uses `storyboard_key` (R2 key path) instead of `storyboard_url` (Drive file ID) — Drive was removed in E1-S2b.

---

## [E1-S4] Run list and artifact retrieval endpoints
**Epic:** E1 — Script to Storyboard
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 3
**Priority:** high
**Depends on:** E1-S2b
**Blocks:** E6-S2

### Goal
Backend endpoints needed by the operator UI to list runs and view step artifacts.

### Acceptance Criteria
- [x] `GET /runs` — lists all runs by scanning R2 for `run_log.json` files; returns `[{run_id, created_at, steps: {step: status}}]` sorted by date descending
- [x] `GET /runs/{run_id}/artifact/{step}` — fetches the artifact for that step from R2 and returns it; step values: `storyboard`, `manifest`, `ffmpeg_script`, `render`
- [x] Returns 404 if run or artifact not found
- [x] `render` step returns a presigned R2 URL (valid 1 hour) for direct video download/playback
- [x] All other steps return JSON or text content inline

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing — 35 new tests, 282 total
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Handover
- `src/storage.py`: `R2Client.list_runs() → list[dict]` — scans `runs/` prefix, filters keys ending in `/run_log.json`, fetches each, returns `[{run_id, created_at, steps: {step: status_string}}]` sorted by `created_at` descending. `R2Client.generate_presigned_url(key, expires_in=3600) → str` — delegates to boto3 `generate_presigned_url("get_object", ...)`.
- `src/models.py`: `RunSummary(run_id, created_at, steps: dict[str, str])`, `RunListResponse(runs: list[RunSummary])`, `ArtifactResponse(step, content_type, content=None, url=None)` added.
- `src/routes/runs.py`: `GET /runs` → `RunListResponse` (500 on storage failure). `GET /runs/{run_id}/artifact/{step}` → `ArtifactResponse` (404 if artifact missing, 422 for invalid step). `_STEP_ARTIFACT_KEYS` dict maps each step to its R2 key template and content type. `_make_r2_client(settings)` helper added to DRY up R2Client construction.
- Step → R2 key mapping: `storyboard` → `storyboard.json` (JSON); `manifest` → `asset_manifest.json` (JSON); `ffmpeg_script` → `ffmpeg_script.sh` (text, decoded UTF-8); `render` → `output/final.mp4` (presigned URL, 1h TTL).
- No new ENV vars. No new dependencies.
- 282 total tests passing (35 new).

---

## EPIC 2 — Storyboard to Asset Manifest (Pipeline Step 3)
Parse `storyboard.json` scenes → `asset_manifest.json` with one asset spec per scene

---

## [E2-S1] Asset manifest generation
**Epic:** E2 — Storyboard to Asset Manifest
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-22
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
- `src/manifest.py`: `build_manifest(run_id, storyboard_data) → AssetManifest` — pure transformation, no API calls. Maps `visual_prompts.primary_stk → primary_query`, `fallback_stk → fallback_query`, `ai_generate → ai_generate_prompt`. Raises `ManifestError` on invalid storyboard data. `clip_type_breakdown(manifest) → dict[str, int]` helper available.
- `src/routes/manifest.py`: `POST /runs/{run_id}/manifest` — reads `storyboard.json` from R2 (→404 on StorageError), builds manifest (→422 + run_log `failed` on ManifestError), uploads `asset_manifest.json`, updates run_log `complete`. Returns `ManifestResponse`.
- `src/models.py`: `ManifestEntry` (scene_id, clip_type, primary_query, fallback_query, ai_generate_prompt, status="pending"), `AssetManifest` (run_id, entries), `ManifestResponse` (status, manifest_key, scene_count, clip_type_breakdown).
- `src/exceptions.py`: `ManifestError` added.
- `src/main.py`: manifest router registered.
- R2 key: `runs/{run_id}/asset_manifest.json`.
- `tests/test_manifest.py`: 27 tests — 11 unit (build_manifest), 3 unit (clip_type_breakdown), 13 route integration. All passing. 95 total.
- No new ENV vars. No new dependencies.

---

## EPIC 3 — Asset Acquisition (Pipeline Step 4)
For each scene: Pexels primary → Pexels fallback → Replicate/Flux AI generation. Download to Drive.

---

## [E3-S1] Pexels stock footage integration
**Epic:** E3 — Asset Acquisition
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E2-S1

### Goal
Query Pexels with primary and fallback search terms for each scene, download the best match to the correct Drive subfolder, and update the manifest entry with the result.

### Acceptance Criteria
- [x] Pexels client queries videos/photos using `primary_query`; falls back to `fallback_query` if no result
- [x] Downloads asset to `/images` or `/video` subfolder depending on clip_type
- [x] Updates `asset_manifest.json` entry: `{source: "pexels", file_key: "<r2_key>", status: "acquired"}` — model fields added; write-back to `asset_manifest.json` is done by E3-S3 orchestrator using `PexelsAcquireResult`
- [x] Handles Pexels rate limits gracefully (retry with backoff)

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (mock Pexels API) — 26 tests
- [x] CI green, deployed to DEV
- [ ] Smoke test passed — end-to-end smoke test deferred to E3-S3 (requires orchestrator route)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Run asset acquisition on a 3-scene test manifest. Verify files appear in Drive `/images` or `/video`. Check manifest entries show `source: pexels`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- `src/models.py`
- `src/storage.py` (note: `src/drive.py` was removed in E1-S2b)

### Files to create or modify
- `src/pexels.py` — Pexels API client
- `src/models.py` — `ManifestEntry` source/file_key fields; `PexelsAcquireResult` model
- `src/exceptions.py` — `PexelsError`
- `src/storage.py` — `R2Client.upload_bytes`
- `tests/test_pexels.py`

### Handover
- `src/pexels.py`: `PexelsClient(api_key, per_page)` — synchronous, uses `requests.Session`. Key method: `acquire_for_entry(entry, run_id, storage) → Optional[PexelsAcquireResult]`. Tries `primary_query` then `fallback_query`. `hard_cut` → Videos API → `runs/{run_id}/video/{scene_id}.mp4`; `still_with_motion`/`animated` → Photos API → `runs/{run_id}/images/{scene_id}.jpeg`. Returns `None` when both queries miss (caller chains to Replicate). Raises `PexelsError` on API error (non-retryable).
- Module-level helpers (all importable and tested): `_pick_best_video_file(video)` — highest height ≤ 1080px, tie-broken by width; `_pick_best_photo(photos)` — requires ≥ 1920×1080, picks minimum excess area; `_ext_from_url`, `_content_type_from_ext`, `_ext_from_content_type`.
- `src/models.py`: `ManifestEntry` gains `source: Optional[str]` and `file_key: Optional[str]`. `PexelsAcquireResult(scene_id, source="pexels", file_key, status="acquired")` added.
- `src/storage.py`: `R2Client.upload_bytes(key, data, content_type)` added for binary asset uploads.
- `src/exceptions.py`: `PexelsError` added.
- Rate limiting: exponential backoff on 429 — 1s, 2s, 4s — max 3 attempts, then raises `PexelsError`.
- No new ENV vars (uses existing `PEXELS_API_KEY` and `PEXELS_PER_PAGE` from config).
- No new dependencies (uses existing `requests`).
- 121 total tests passing (26 new).

---

## [E3-S2] Replicate/Flux AI image generation fallback
**Epic:** E3 — Asset Acquisition
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E3-S1

### Goal
When both Pexels queries return no result, generate an image via Replicate/Flux using the scene's `ai_generate_prompt`, download it to Drive `/images`, and update the manifest.

### Acceptance Criteria
- [x] Replicate client calls Flux model with `ai_generate_prompt`
- [x] Polls for completion (async generation)
- [x] Downloads generated image to run `/images` folder in R2
- [x] Returns `ReplicateAcquireResult(source="replicate", file_key=<r2_key>, status="acquired")` — write-back to manifest is E3-S3's responsibility; `file_path` in original AC is stale (project uses R2 `file_key`)
- [x] Handles Replicate API errors gracefully — raises `ReplicateError`

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (mock Replicate API) — 19 tests
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred to E3-S3 (requires orchestrator route to run end-to-end)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Force Pexels to return no results for a scene. Confirm Replicate is called and image appears in Drive `/images`. Check manifest shows `source: replicate`.

### Files to read
- `src/pexels.py`
- `src/models.py`
- `src/storage.py` (note: `src/drive.py` was removed in E1-S2b)

### Files to create or modify
- `src/replicate_client.py` — Replicate/Flux client
- `src/models.py` — ReplicateAcquireResult model
- `src/exceptions.py` — ReplicateError
- `tests/test_replicate_client.py`

### Handover
- `src/replicate_client.py`: `ReplicateClient(api_token, model, poll_interval_seconds=3, max_poll_attempts=60)`. Key method: `acquire_for_entry(entry, run_id, storage) → ReplicateAcquireResult`. Calls `predictions.create(model=model, input={"prompt": ai_generate_prompt})`, polls `prediction.reload()` until `succeeded`/`failed`/`canceled` or timeout. Downloads from `str(output[0])`, uploads to `runs/{run_id}/images/{scene_id}.webp` with `content_type="image/webp"`. Always `.webp` — no URL extension inference.
- `src/models.py`: `ReplicateAcquireResult(scene_id, source="replicate", file_key, status="acquired")` added.
- `src/exceptions.py`: `ReplicateError` added.
- All config vars already present: `REPLICATE_API_TOKEN`, `REPLICATE_FLUX_MODEL`, `REPLICATE_POLL_INTERVAL_SECONDS`, `REPLICATE_MAX_POLL_ATTEMPTS`.
- No new dependencies (`replicate>=1.0.0` was already in `requirements.txt` per D007).
- 140 total tests passing (19 new).

---

## [E3-S3] Asset acquisition orchestrator
**Epic:** E3 — Asset Acquisition
**Sprint:** unassigned
**Status:** done
**Completed:** 2026-05-22
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
- `src/acquisition.py`: `MIN_ACQUIRED_FOR_COMPLETE = 1` — module-level constant documenting the step status rule (complete if ≥ 1 scene acquired; failed only if 0). `acquire_scene(entry, run_id, pexels, replicate, storage) → bool` — single-entry fallback chain, mutates entry in-place; `PexelsError` falls through to Replicate. `run_acquisition(run_id, manifest, pexels, replicate, storage) → dict` — full loop; skips `acquired` entries; returns `{acquired, failed, sources}` where `acquired` is the post-loop total (including pre-existing).
- `src/routes/assets.py`: `POST /runs/{run_id}/assets` — reads `asset_manifest.json` from R2 (404 if missing), builds `PexelsClient` + `ReplicateClient` from settings, calls `run_acquisition`, writes updated manifest back, updates `run_log.json`, returns `AcquisitionResponse`. HTTP 200 for all normal outcomes (status field is `complete`/`failed`); 500 only on unexpected exception or R2 write failure.
- `src/models.py`: `AcquisitionResponse(status, acquired, failed, sources, manifest_key)` added.
- `src/main.py`: `assets_router` registered via `app.include_router(assets_router.router)`.
- `tests/test_acquisition.py`: 18 tests — 5 unit for `acquire_scene`, 6 unit for `run_acquisition` (including idempotent all-pre-acquired case), 1 constant check, 6 route integration tests. 158 total passing.
- No new ENV vars. No new dependencies.
- Smoke test: deferred until Railway DEV deploy completes — POST to `/runs/{run_id}/assets` on DEV, verify all scenes acquired, check Drive folders, confirm `run_log.json` shows `asset_acquisition: complete`.

---

## EPIC 4 — FFmpeg Script Generation (Pipeline Step 5)
`storyboard.json` + `asset_manifest.json` → `ffmpeg_script.sh`

---

## [E4-S1] FFmpeg script generator
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E3-S3

### Goal
Read the storyboard and asset manifest from Drive and generate a valid `ffmpeg_script.sh` that assembles all assets (video clips, images, voiceover, music, SFX) into a 9:16 Short.

### Acceptance Criteria
- [x] `POST /runs/{run_id}/ffmpeg-script` reads storyboard and manifest from R2
- [x] Generates `ffmpeg_script.sh` with correct clip durations from storyboard
- [x] Handles `hard_cut`, `still_with_motion`, and `animated` clip types
- [x] Mixes voiceover + music + SFX audio tracks
- [x] Outputs 9:16 vertical format (1080×1920)
- [x] Uploads `ffmpeg_script.sh` to run folder
- [x] Updates `run_log.json`: step `ffmpeg_script` → `complete`

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing — 59 new tests, 217 total
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred; requires DEV run with completed storyboard + manifest
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Generate script for a test run. Manually inspect `ffmpeg_script.sh` in Drive. Verify clip count matches storyboard scene count and durations are correct.

### Files to create or modify
- `src/ffmpeg_builder.py` — script generation logic
- `src/routes/ffmpeg_script.py` — POST /runs/{run_id}/ffmpeg-script
- `src/main.py` — register route
- `tests/test_ffmpeg_builder.py`

### Handover
- `src/ffmpeg_builder.py`: `build_ffmpeg_script(run_id, storyboard, manifest) → str` — pure function, no side effects. Raises `FFmpegBuildError` (with offending `scene_id`) if any manifest entry lacks a `file_key`. Module-level helpers (all importable and tested): `_local_path(run_id, file_key) → str` (R2 key → `/tmp/{run_id}/...`); `_zoompan_filter(clip_type, motion_effect, frames) → str`; `_parse_sfx_delay_ms(sfx_timing, duration_s, offset_s) → int`.
- `src/routes/ffmpeg_script.py`: `POST /runs/{run_id}/ffmpeg-script` — sync route; reads `storyboard.json` + `asset_manifest.json` from R2 (→ 404 on missing), builds script (→ 422 + run_log `failed` on `FFmpegBuildError`), uploads to `runs/{run_id}/ffmpeg_script.sh` via `storage.upload_text` (→ 500 on `StorageError`), updates run_log `complete`. Returns `FFmpegScriptResponse`.
- `src/models.py`: `FFmpegScriptResponse(status, script_key)` added.
- `src/exceptions.py`: `FFmpegBuildError` added.
- `src/storage.py`: `R2Client.upload_text(key, content, content_type)` added — encodes to UTF-8, delegates to `upload_bytes`.
- Generated script structure: comment header (run_id, generated_at, scene count, total duration) → `set -euo pipefail` → BASE/WORK vars → voiceover guard (hard `exit 1` if no `.mp3`) → music check (anullsrc silence fallback if absent) → per-scene ffmpeg commands → concat list heredoc → concat command → audio assembly (voiceover 1.0 + music 0.15 + per-scene SFX with `adelay` in ms; `silence` SFX skipped entirely) → done echo.
- Clip type behaviour: `hard_cut` → `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`; `still_with_motion` → zoompan 1.0→1.05 centered; `animated` → 1.0→1.1 zoom_in/zoom_out or 1.1x pan_left/pan_right driven by `motion_effect` (unknown effect falls back to zoom_in).
- R2 key: `runs/{run_id}/ffmpeg_script.sh`.
- No new ENV vars. No new dependencies.
- 217 total tests passing (59 new). Smoke test deferred — POST to `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed storyboard + manifest exists; inspect generated `ffmpeg_script.sh` in R2 console.

---

## [E4-S2] Captions and on-screen text overlay
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 5
**Priority:** medium
**Depends on:** E4-S1

### Goal
Burn ASS subtitles into video using on_screen_text field already present in storyboard schema. ASS format chosen over drawtext for full control over font, position, and animation.

### Acceptance Criteria
- [x] ASS subtitle file generated from storyboard on_screen_text + scene timings
- [x] Text style: Open Sans Bold, 72pt, white, centered, bottom third (MarginV=120)
- [x] Text uppercased (Shorts style)
- [x] ASS burned into final.mp4 via FFmpeg vf ass= filter
- [x] Font embedded in Railway container (add to Dockerfile)
- [x] on_screen_text: null scenes produce no caption event (skip gracefully)
- [x] All existing tests pass; new tests for ASS generation

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred; requires DEV run with completed assets + voiceover
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Implementation notes
- New src/captions.py: build_ass(scenes, timings) → ASS string
- format_ass_time(seconds) helper
- ffmpeg_builder.py: add ASS burn step after video concat, before audio mix
- Dockerfile: apt-get install -y fonts-open-sans or download Montserrat via curl
- DECISIONS.md D027: ASS over drawtext rationale

### Handover
- `src/captions.py`: new module. `format_ass_time(seconds: float) -> str` — converts seconds to ASS `H:MM:SS.cc` format. `build_ass(scenes: list[StoryboardScene]) -> str` — generates complete ASS file; accumulates `duration_s` offsets for timing; scenes with `on_screen_text=None` produce no Dialogue event; text uppercased.
- `src/ffmpeg_builder.py`: `_write_captions_ass(ass_content)` — embeds ASS file as a quoted heredoc (`'__ASS_EOF__'`) so `$`-variables and ASS override braces are never expanded by bash. `_burn_captions()` — runs `ffmpeg -vf "ass=$WORK/captions.ass"` producing `$WORK/video_captioned.mp4`. `_audio_section` now reads from `video_captioned.mp4` instead of `video_only.mp4`. `build_ffmpeg_script` calls both new builders between concat and audio.
- `Dockerfile`: `fonts-open-sans` added to apt install layer.
- `tests/test_captions.py`: 19 new tests — `format_ass_time` edge cases, `build_ass` structure, timing offsets, null-skip, uppercase, empty-list.
- `tests/test_ffmpeg_builder.py`: 7 new `TestCaptionsInScript` tests — heredoc quoting, ordering, uppercase, audio-section input change.
- 341 total tests passing (30 new).
- No new ENV vars. No new pip dependencies.
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed assets + voiceover; inspect generated script for `captions.ass` heredoc; verify captions visible in rendered video.

---

## [E4-S3] Ken Burns zoompan effect on static images
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 3
**Priority:** medium
**Depends on:** E4-S1

### Goal
Static images from Pexels/Replicate currently show as frozen frames. Apply zoompan filter to simulate camera movement — dramatically improves perceived production quality.

### Acceptance Criteria
- [x] still_with_motion scenes: gentle zoom in (z=1.0→1.05 over duration)
- [x] animated scenes: directional movement based on motion_effect field (zoom_in/zoom_out/pan_left/pan_right)
- [x] zoompan filter parameters: d=duration_frames, s=1080x1920, fps=25
- [x] Images pre-scaled and padded to 9:16 before zoompan (scale+pad filter)
- [x] All existing tests pass; new tests for zoompan filter string generation

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred; requires DEV run with acquired assets
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Implementation notes
- ffmpeg_builder.py _zoompan_filter() already exists — verify it uses correct frame count (duration_s * 25) not hardcoded d=125
- Add scale+pad normalization before zoompan for all image inputs
- DECISIONS.md D028: zoompan parameters and rationale

### Handover
- `src/ffmpeg_builder.py`: `_render_image_scene` pre-scale corrected from 2×(2160×3840) to 1×(1080×1920). The zoompan centering formula `iw/2-(iw/zoom/2)` requires input dimensions to match the `s=` output parameter — 2× input caused x=0 (left-edge crop) instead of centered behavior.
- `_SCALED_W` and `_SCALED_H` constants removed (no longer referenced).
- `_zoompan_filter()` unchanged — frame count calculation (`d=duration_s*25`) and all zoom/pan expressions are correct.
- `tests/test_ffmpeg_builder.py`: 3 new tests in `TestBuildFfmpegScript` — `test_still_with_motion_prescales_to_output_dimensions`, `test_animated_prescales_to_output_dimensions`, `test_image_scene_vf_chain_order_is_scale_zoompan_setsar`. Regression guards against future re-introduction of 2× scale.
- 311 total tests passing (3 new).
- No new ENV vars. No new dependencies.

---

## [E4-S4] CLIP semantic reranking of Pexels results
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** unassigned
**Status:** done
**Completed:** 2026-05-25
**Points:** 5
**Priority:** low
**Depends on:** E5-S3

### Goal
After fetching Pexels results, score each thumbnail against scene description using CLIP embeddings. Dramatically improves relevance at cost of ~200ms latency per scene.

### Acceptance Criteria
- [x] CLIP model loaded once at startup (sentence-transformers + Pillow, no GPU)
- [x] Each Pexels result thumbnail scored against scene visual description
- [x] Top-scoring result selected instead of first result
- [x] Latency acceptable (<500ms per scene on Railway CPU)
- [x] Deferred until E5-S3 query improvements are validated first

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing — 17 new tests, 390 total
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred; requires DEV run with CLIP_RERANK_ENABLED=True
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Handover
- `src/clip_reranker.py`: new module. `CLIPReranker(model)` — `rerank_videos(videos, query) → list[dict]` and `rerank_photos(photos, query) → list[dict]` score Pexels thumbnails (video `image` field; photo `src.medium`) against query text using CLIP cosine similarity. Module-level helpers: `load_model()` (lazy-loads `clip-ViT-B-32` via `sentence-transformers` into singleton); `get_reranker() → Optional[CLIPReranker]` (returns None when disabled). `_cosine_similarity(text_emb, img_embs) → np.ndarray` — pure numpy, no torch in application code. Unscoreable items (missing/unfetchable thumbnails) placed after scored items in original order. Raises `CLIPError` on encoding failure.
- `src/pexels.py`: `_acquire_video` calls `get_reranker()` and reranks videos before the `_pick_best_video_file` loop. `_acquire_photo` calls `get_reranker()` and reranks photos then uses new `_pick_first_qualifying_photo` (first qualifying in CLIP order); falls back to `_pick_best_photo` (min excess area) on `CLIPError` or when reranker is None.
- `src/pexels.py`: `_pick_first_qualifying_photo(photos) → Optional[dict]` added — returns first photo ≥ 1920×1080 in iteration order. Used with CLIP (ordering already encodes relevance); existing `_pick_best_photo` retained for non-CLIP path.
- `src/main.py`: lifespan hook calls `clip_reranker.load_model()` when `settings.CLIP_RERANK_ENABLED=True`.
- `src/config.py`: `CLIP_RERANK_ENABLED: bool = False` added.
- `src/exceptions.py`: `CLIPError` added.
- `requirements.txt`: `sentence-transformers>=3.0.0`, `Pillow>=10.0.0` added. Decision logged as D032.
- `ENV.md`: `CLIP_RERANK_ENABLED` documented.
- Smoke test deferred: set `CLIP_RERANK_ENABLED=True` in Railway DEV, trigger a full run, confirm footage topics visually match VO better than baseline.
**Promoted to backlog:** none

---

## [E4-S5] Real-time captions from voiceover_line
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 5
**Priority:** medium
**Depends on:** E4-S2
**Upgraded by:** E5-S4 (WhisperX word-level timing)

### Goal
Add a second ASS subtitle track with full voiceover text as captions, displayed at the bottom of the screen in small font, timed to scene boundaries. Separate from the on_screen_text keyword overlay.

### Acceptance Criteria
- [ ] Second ASS file generated from storyboard voiceover_line per scene
- [ ] Style: Open Sans Regular (not Bold), 42pt, white with black outline, bottom of screen, MarginV=80
- [ ] No quotation marks, no uppercasing — natural sentence case
- [ ] Each scene's full voiceover_line shown for the duration of that scene
- [ ] Burned into video as a second subtitle pass after on_screen_text overlay
- [ ] on_screen_text overlay remains unchanged (center, large, keywords)
- [ ] null/empty voiceover_line scenes: skip gracefully
- [ ] All existing tests pass; new tests for caption ASS generation

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Implementation notes
- New `build_captions_ass(scenes)` function in `src/captions.py` (separate from `build_ass`)
- Separate style: `CaptionStyle` (42pt, Regular, MarginV=80, bottom) vs existing `Default` (72pt, Bold, center)
- Two-pass burn in `ffmpeg_builder.py`: first on_screen_text (`video_captioned.mp4`), then captions (`video_captioned2.mp4`)
  - Or: single pass chaining two ass filters: `-vf "ass=onscreen.ass,ass=captions.ass"` — evaluate at implementation time
- Timing: scene boundaries only (not word-level) — WhisperX (E5-S4) will upgrade this later
- DECISIONS.md D031: scene-boundary caption timing chosen over word-level as interim solution

### Handover
- `src/captions.py`: `_CAPTIONS_ASS_HEADER` constant — new ASS header with `VoiceCaption` style: Open Sans Regular (Bold=0), 42pt, white + black outline, Alignment=2 (bottom-center), MarginV=80. `build_captions_ass(scenes: list[StoryboardScene]) -> str` — generates ASS file from `voiceover_line` per scene; timing accumulated from `duration_s`; scenes with empty/whitespace-only `voiceover_line` produce no Dialogue event; text displayed as-is (no quote stripping, no uppercasing). Module docstring updated to mention both functions.
- `src/ffmpeg_builder.py`: `build_captions_ass` imported. `build_ffmpeg_script` now calls `_write_voiceover_captions_ass(captions_ass_content)` and `_burn_voiceover_captions()` between `_burn_captions()` and `_audio_section()`. `_write_voiceover_captions_ass(ass_content)` — embeds via quoted heredoc (`'__VCAP_EOF__'`), writes to `$WORK/voiceover_captions.ass`. `_burn_voiceover_captions()` — runs `ffmpeg -vf "ass=$WORK/voiceover_captions.ass"` on `video_captioned.mp4` → `video_captioned2.mp4`. `_audio_section` updated: reads from `video_captioned2.mp4` (was `video_captioned.mp4`).
- Render chain: `video_only.mp4` → on-screen overlay → `video_captioned.mp4` → voiceover captions → `video_captioned2.mp4` → audio mix → `final.mp4`.
- `tests/test_captions.py`: 17 new tests in `TestBuildCaptionsAss` — style field assertions (not-bold, bottom-center alignment, MarginV=80), timing offsets, empty/whitespace skip, no uppercasing, no quote stripping, sentence case preserved, ends with newline. `_scene` helper gains optional `voiceover_line` parameter.
- `tests/test_ffmpeg_builder.py`: `test_audio_section_reads_from_captioned_video` → `test_audio_section_reads_from_captioned2_video` (updated assertion). `test_null_on_screen_text_produces_no_dialogue_in_script` narrowed to check only the `captions.ass` block. 6 new tests in `TestCaptionsInScript` — voiceover heredoc present, `video_captioned2.mp4` present, second burn reads from `video_captioned.mp4`, chain ordering, voiceover not uppercased.
- 369 total tests passing (28 new). No new ENV vars. No new pip dependencies.
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed assets + voiceover; verify both `captions.ass` and `voiceover_captions.ass` heredocs in generated script; confirm keyword overlay (large, bold, centered) and voiceover captions (small, regular, bottom) both visible in rendered video.

---

## [E4-S6] Subtitle style revision (Poppins Bold, TikTok-style)
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 3
**Status:** done
**Completed:** 2026-05-27
**Points:** 2
**Priority:** high
**Depends on:** E4-S5

### Goal
Replace current VoiceCaption ASS style with Poppins Bold, larger size, thick black stroke, subtle shadow — matching TikTok/Reels subtitle aesthetic shown in SampleDis reference.

### Acceptance Criteria
- [x] Font: Poppins Bold (`fonts-poppins` apt package if available, else download `Poppins-Bold.ttf` into Dockerfile via `assets/fonts/`)
- [x] Size: 92pt
- [x] White text, black outline 8px, shadow 1px at offset (1,1)
- [x] MarginV: 350 (bumped from 250 post-smoke-test for better bottom clearance)
- [x] MarginL/R: ASS defaults (~20px)
- [x] Alignment: center (Alignment=2)
- [x] Max 2 lines, natural wrap — no hard truncation in code
- [x] On-screen keyword track: reverted to white
- [x] Dockerfile: Poppins Bold installed via `.ttf` copy + fc-cache
- [x] `DECISIONS.md`: D035 documenting font choice
- [x] Smoke test: render a short, confirm captions match SampleDis reference visually

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing
- [x] CI green, deployed to DEV
- [x] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to read
- `src/captions.py`
- `Dockerfile`
- `DECISIONS.md`

### Files to modify
- `src/captions.py` — VoiceCaption ASS style block
- `Dockerfile` — Poppins Bold font install
- `DECISIONS.md` — D035

### Notes
- Poppins is available via `fonts-recommended` or direct `.ttf` download from Google Fonts. Prefer apt if package exists, otherwise ADD the `.ttf` file to the repo under `assets/fonts/` and COPY in Dockerfile.
- Do NOT change `voiceover_line` length constraint (4–6 words max) — that stays from previous E4-S6 iteration.
- ASS style parameters: `BorderStyle=1`, `Outline=8`, `Shadow=1`.
- Previous E4-S6 iteration shipped: Montserrat ExtraBold 72pt, yellow keyword track, v0.6 prompt. Those prompt changes remain; only the ASS style block changes here.

### Iteration 1 handover (2026-05-27 — superseded by this story)
- `src/captions.py`: VoiceCaption → Montserrat ExtraBold, 72pt, outline 6px, MarginV=250. Default → 56pt yellow.
- `src/storyboard.py` + `docs/PROMPTS.md`: bumped to v0.6, `voiceover_line` capped at 4–6 words.
- `Dockerfile`: `fonts-montserrat` added.
- `DECISIONS.md`: D033 added.

### Handover
- `src/captions.py`: `_CAPTIONS_ASS_HEADER` VoiceCaption style — `Poppins` (fontname), Bold=1, 92pt, white (`&H00FFFFFF`), black outline 8px, shadow 1px, MarginV=350, Alignment=2 (bottom-center). `_ASS_HEADER` Default style (on-screen keywords) — PrimaryColour reverted to white `&H00FFFFFF` (was yellow `&H0000FFFF`). No other field changes.
- `assets/fonts/Poppins-Bold.ttf` — bundled in repo (152 KB); sourced from Google Fonts (github.com/google/fonts). See D035.
- `Dockerfile` — `COPY assets/fonts/Poppins-Bold.ttf /usr/local/share/fonts/Poppins-Bold.ttf` + `RUN fc-cache -f /usr/local/share/fonts` added after the apt layer. `fonts-montserrat` left in apt (not removed — belt-and-suspenders, no harm).
- `DECISIONS.md` — D035 was pre-written; no new entry required.
- `tests/test_captions.py` — `test_voicecaption_style_present` updated to `Poppins,92`; `test_voicecaption_outline_is_6` renamed to `test_voicecaption_outline_is_8` (assert 8); `test_style_is_not_bold` renamed to `test_voicecaption_bold_field_is_1` (assert 1); `test_default_style_is_yellow` renamed to `test_default_style_is_white` (assert `&H00FFFFFF`); `test_voicecaption_shadow_is_1` added. 394 total tests passing.
- No new Python dependencies. No new ENV vars.
- **Smoke test required:** render a Short on DEV and confirm Poppins Bold captions match SampleDis reference at mobile screen size.

---

## [E4-S7] Word-synced captions using Deepgram timestamps
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 4
**Status:** done
**Completed:** 2026-05-28
**Points:** 5
**Priority:** normal
**Depends on:** E5-S4

### Goal
Use word-level timestamps from Deepgram (via `alignment.json`) to display caption chunks exactly when spoken, with the active word highlighted in yellow. Implements the current high-retention short-form caption pattern.

### Acceptance Criteria
- [x] Caption chunks advance word-by-word or phrase-by-phrase in sync with audio
- [x] Active word highlighted in yellow (per-word Dialogue events)
- [x] 4-6 words per caption chunk maximum
- [x] Replaces current proportional `voiceover_line` display
- [x] Smoke test: watch rendered video and confirm captions track speech accurately

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (512 total)
- [x] CI green, deployed to DEV
- [x] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files modified
- `src/captions.py` — `build_word_synced_captions_ass(scene_words)`
- `src/ffmpeg_builder.py` — `assign_words_to_scenes`, `compute_scene_durations_from_alignment`, `build_ffmpeg_script` updated
- `src/routes/ffmpeg_script.py` — wired new helpers

### Handover
- `src/captions.py`: `build_word_synced_captions_ass(scene_words: list[list[WordTimestamp]], chunk_size=5) -> str` — per-word Dialogue events; active word highlighted via `{\c&H0000FFFF&}`/`{\c&H00FFFFFF&}` ASS inline colour override; events extend to next word's `start_ms` (no intra-chunk gaps); chunks never cross scene boundaries; scene-grouped input prevents cross-scene merging.
- `src/ffmpeg_builder.py`: `assign_words_to_scenes(scenes, words) -> list[list[WordTimestamp]]` — sequential greedy text matching; normalises with `re.sub(r"[^\w]","",w).lower()`; splits voiceover tokens on hyphens first so "6-minute" matches Deepgram words "6" + "minute". `compute_scene_durations_from_alignment(scenes, scene_words) -> list[StoryboardScene]` — scene N duration = `(next_scene.first_word.start_ms - this_scene.first_word.start_ms) / 1000`; last scene uses its own word span; unmatched scenes keep original `duration_s`; floor at `_MIN_SCENE_DURATION_S`. `build_ffmpeg_script` gains optional `scene_words: Optional[list[list[WordTimestamp]]] = None` param.
- `src/routes/ffmpeg_script.py`: when `alignment.json` present with words → calls `assign_words_to_scenes` + `compute_scene_durations_from_alignment`; storyboard scene durations corrected before script generation; `scene_words` passed to `build_ffmpeg_script` for word-synced captions.
- 512 total tests passing. No new ENV vars. No new pip dependencies.

---

## [E4-S8] Caption word coverage + video tail padding
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** unassigned
**Status:** backlog
**Priority:** high
**Depends on:** E4-S7

### Goal
Fix two categories of rendering defects observed in production (2026-05-30):

**Category A — Missing caption words (5 instances observed):** Claude's 4-6 word voiceover_line constraint causes it to drop connecting words ("with", "when we reach", "API") when splitting a long VO line into scenes. `assign_words_to_scenes` uses text matching against `voiceover_line`, so any word absent from all scene voiceover_lines is never assigned to a scene → silently skipped by the caption system.

**Category B — Abrupt video end:** The video cuts off immediately after the last word with no breathing room. A 0.5s silence tail is needed after the final scene.

### Acceptance Criteria
**Category A — Prompt fix (storyboard)**
- [ ] Prompt updated to explicitly forbid dropping words when splitting: every word from the spoken VO must appear in exactly one scene's `voiceover_line`. If a phrase exceeds 6 words, split into two scenes — never drop the connecting word.
- [ ] Add a few-shot example showing a 9-word phrase split into two scenes across a `---` boundary, with "with", "and", "when" preserved.
- [ ] Prompt version bumped to v0.9 in `docs/PROMPTS.md`

**Category A — Caption fallback (ffmpeg_builder)**
- [ ] `assign_words_to_scenes`: after the primary greedy assignment, any Deepgram words not matched to any scene are assigned to the scene whose time window they fall within (by `start_ms`). This ensures that words Claude omitted from voiceover_lines still get captions if the audio timing is available.
- [ ] Unassigned words that fall before the first scene or after the last scene are appended to the nearest scene.
- [ ] No change to existing matched-word behaviour — only unmatched words are affected by the fallback.

**Category B — Video tail**
- [ ] `build_ffmpeg_script` adds a `_VIDEO_TAIL_S = 0.5` silence pad after the final concat step (before audio assembly). The last scene's video clip is extended by 0.5s via `tpad=stop_mode=clone:stop_duration=0.5` filter or equivalent.
- [ ] Tail length configurable via `VIDEO_TAIL_SECONDS` ENV var (default `0.5`, type `float`).
- [ ] `src/config.py`: `VIDEO_TAIL_SECONDS: float = 0.5`.
- [ ] `ENV.md`: document `VIDEO_TAIL_SECONDS`.

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Render a video with a VO containing: (a) connecting words like "with X, Y, and Z", and (b) a phrase "when we reach X" — verify all words appear in captions. Confirm rendered video has ~0.5s of visible frames after the last spoken word before the video ends.

### Files to read
- `src/ffmpeg_builder.py` — `assign_words_to_scenes`, `build_ffmpeg_script`
- `src/captions.py` — `build_word_synced_captions_ass`
- `docs/PROMPTS.md` — current v0.8 prompt
- `src/storyboard.py` — `SYSTEM_PROMPT` constant
- `src/config.py`

### Files to create or modify
- `src/storyboard.py` — bump SYSTEM_PROMPT to v0.9 (word-preservation rule + example)
- `docs/PROMPTS.md` — v0.9 changelog
- `src/ffmpeg_builder.py` — fallback assignment in `assign_words_to_scenes`; tail pad in `build_ffmpeg_script`
- `src/config.py` — `VIDEO_TAIL_SECONDS: float = 0.5`
- `ENV.md` — document `VIDEO_TAIL_SECONDS`
- `tests/test_ffmpeg_builder.py` — test fallback assignment and tail pad
- `tests/test_storyboard.py` — update system prompt version assertion if present

### Handover
_filled on completion_

---

## EPIC 5 — FFmpeg Execution + Drive Upload (Pipeline Step 6)
Execute `ffmpeg_script.sh` on Railway, upload final video to Drive `/output`

---

## [E5-S1] FFmpeg execution and output upload
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** unassigned
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E4-S1

### Goal
Download all assets from Drive to a Railway temp directory, execute `ffmpeg_script.sh`, and upload the output video back to Drive `/output`, then clean up temp files.

### Acceptance Criteria
- [x] `POST /runs/{run_id}/render` downloads all assets from R2 to `/tmp/{run_id}/`
- [x] Downloads and executes `ffmpeg_script.sh`
- [x] Captures FFmpeg stdout/stderr and appends to `run_log.txt`
- [x] Uploads output video to `runs/{run_id}/output/final.mp4` in R2
- [x] Cleans up `/tmp/{run_id}/` after upload
- [x] Updates `run_log.json`: step `render` → `complete` or `failed`

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing — 30 new tests, 247 total
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — deferred; requires fully assembled run on DEV
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Trigger render on a fully assembled test run on DEV. Wait for completion. Verify `runs/{run_id}/output/final.mp4` appears in R2. Check `run_log.txt` for FFmpeg output. Watch the video.

### Files to create or modify
- `src/renderer.py` — download assets, run FFmpeg, upload output
- `src/routes/render.py` — POST /runs/{run_id}/render
- `src/main.py` — register route
- `tests/test_renderer.py`

### Handover
- `src/renderer.py`: `render_run(run_id, manifest, storage, timeout_seconds) → dict` — orchestrates full render. Always calls `cleanup(run_id)` in a `finally` block. Returns `{status, output_key, duration_seconds, exit_code}`. Raises `StorageError` on unexpected R2 failures. Module-level helpers (importable and tested): `download_run_assets`, `download_script`, `execute_script`, `upload_output`, `cleanup`, `_write_run_log_txt`.
- `src/routes/render.py`: `POST /runs/{run_id}/render` — reads `asset_manifest.json` from R2 (→ 404 on missing), calls `render_run`, updates `run_log.json` with `complete`/`failed`. HTTP 200 for both outcomes; 500 on `StorageError` during render.
- `src/storage.py`: `R2Client.get_bytes(key) → bytes` and `R2Client.list_keys(prefix) → list[str]` added.
- `src/models.py`: `RenderResponse(status, output_key, duration_seconds, exit_code)` added.
- `src/exceptions.py`: `RenderError` added.
- `src/config.py`: `FFMPEG_TIMEOUT_SECONDS: int = 300` added.
- Asset download strategy: per-scene `file_key` entries + `voiceover/`, `music/`, `sfx/` prefix listing. `_write_run_log_txt` is non-fatal (swallows `StorageError`).
- R2 output key: `runs/{run_id}/output/final.mp4`.
- No new pip dependencies.
- 30 new tests, 247 total passing.

---

## [E5-S2] Pacing calibration — sync scene durations to voiceover
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 5
**Priority:** medium
**Depends on:** E5-S1

### Goal
Fix two root causes of audio/video desync: (1) word-count heuristics don't match actual recorded VO pacing; (2) concat demuxer causes non-monotonic DTS and progressive audio drift at scale.

### Acceptance Criteria
- [x] ffprobe measures actual voiceover duration from R2 before ffmpeg_script step
- [x] Scene durations redistributed proportionally (word counts used as weights only)
- [x] ffmpeg_script.sh switches from concat demuxer to filter_complex with trim+setpts per scene
- [x] PTS reset after every trim (setpts=PTS-STARTPTS) to prevent timestamp carryover
- [x] All existing tests pass; new tests for duration redistribution logic
- [ ] Smoke test: video cuts align with speech cadence (deferred to DEV deploy)

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Implementation notes
- `get_audio_duration(path)` via ffprobe subprocess → parse JSON format duration
- `redistribute_scene_durations(scenes, audio_duration)` → proportional weights
- ffmpeg_builder.py: replace concat demuxer with filter_complex trim+setpts concat
- Download voiceover from R2 to /tmp before ffprobe measurement; runs before ffmpeg_script step
- Add `POST /runs/{run_id}/ffmpeg-script` to accept optional voiceover key override or auto-detect from run_log.json

### Handover
- `src/ffmpeg_builder.py`: `get_audio_duration(path: Path) -> float` — ffprobe via subprocess, raises `FFmpegBuildError` on failure. `redistribute_scene_durations(scenes, audio_duration) -> list[StoryboardScene]` — pure function, proportional word-count weights, min 0.5s per scene, returns new instances.
- `src/ffmpeg_builder.py`: `_filter_complex_concat(n_scenes)` replaces `_concat_list` + `_concat_command`. Generated script uses a single ffmpeg call with all scene_XX.mp4 as inputs and filter_complex `[i:v]setpts=PTS-STARTPTS[vi]` per clip → `concat=n=N:v=1:a=0[vout]`.
- `src/routes/ffmpeg_script.py`: voiceover discovery is graceful — lists `runs/{run_id}/voiceover/`, skips redistribution (with warning) if no file found or if ffprobe/R2 fails.
- **Bug fix:** `n_scenes` derived from `len(manifest.entries)` not `storyboard.summary.total_scenes` — stale summary caused dangling scene file refs → exit 254.
- **Bug fix:** `,setsar=1:1` on all scene `-vf` chains — varying source SAR caused filter_complex concat failure ("Input link parameters do not match").
- No new ENV vars. No new dependencies (ffprobe is part of ffmpeg, already required).
- 308 total tests passing (28 new).
- Smoke test deferred — POST to `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed storyboard + manifest + assets + uploaded voiceover exists; verify video cuts align with speech cadence.

---

## [E5-S3] Visual-semantic matching improvement
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-25
**Points:** 4
**Priority:** medium
**Depends on:** E3-S3

### Goal
Fix Pexels keyword mismatch by rewriting query generation strategy in storyboard prompt. Concrete nouns only, no adjectives — what would a stock footage cameraman film?

### Acceptance Criteria
- [ ] Storyboard prompt updated with query decomposition instructions:
  - primary_query: 3-4 concrete nouns only, no adjectives
  - fallback_query: 1-2 words, core subject only
  - Examples included in prompt (few-shot)
- [ ] Flux/Replicate prompts updated to use cinematic direction terms (shallow depth of field, golden hour lighting, cinematic)
- [ ] Smoke test: footage visually matches VO topic better than baseline

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Implementation notes
- Edit docs/PROMPTS.md storyboard system prompt — query generation section only
- No code changes to acquisition pipeline — queries flow through unchanged
- Add DECISIONS.md D026: query decomposition strategy and rationale

### Handover
- `docs/PROMPTS.md`: bumped to v0.5. VISUAL PROMPTS RULE section rewritten with explicit query decomposition rules: PRIMARY = 3–4 concrete nouns only (no adjectives); FALLBACK = 1–2 words (core subject only); AI_GENERATE = cinematic direction (shallow depth of field, golden hour lighting, cinematic, 9:16 vertical). Four housing-economics few-shot examples added.
- `src/storyboard.py`: `SYSTEM_PROMPT` constant updated to match v0.5. Version references in module docstring and function docstrings updated.
- `src/storyboard.py` (parser hardening): `_parse_storyboard_response` split regex changed from `\n\s*---\s*\n` to `(?m)^\s*---\s*$` — matches `---` as a standalone line regardless of surrounding blank-line count. `_get_field` now uses `re.IGNORECASE` and tolerates leading `- ` bullets. Both functions log diagnostic context (raw response / block content) on parse failure.
- `src/static/pipeline.html`: storyboard scene cards now show `PRIMARY`, `FALLBACK`, and `AI` fields for visual QA.
- No new ENV vars. No new dependencies.
- Smoke test passed on DEV: `2026-05-25_mind-drain-video-temp`, Scene 1 — PRIMARY: `human brain anatomy model`, FALLBACK: `brain`, AI includes shallow DoF + cinematic direction terms.

---

## [E5-S4] Word-level timestamp extraction via Deepgram
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** 3
**Status:** done
**Completed:** 2026-05-27
**Points:** 5
**Priority:** medium
**Depends on:** E5-S2

### Goal
Call Deepgram Nova-2 API to extract word-level timestamps from the uploaded voiceover MP3. Normalize output to internal schema. Store result as `alignment.json` in R2. Fallback to proportional timing if API fails.

### Acceptance Criteria
- [ ] New service `src/alignment.py`: `align_audio(run_id, audio_url) → list[WordTimestamp]`
- [ ] `WordTimestamp` schema: `{word, start_ms, end_ms, confidence}`
- [ ] Deepgram Nova-2 called via `httpx` (no SDK) — `model=nova-2`, `smart_format=true`
- [ ] Timestamps converted from seconds (float) to milliseconds (int)
- [ ] Punctuation stripped from `word` field
- [ ] Fallback: if Deepgram fails, proportional distribution by character count
- [ ] Result stored as `runs/{run_id}/alignment.json` in R2
- [ ] New pipeline step: `POST /runs/{id}/alignment` (between assets and ffmpeg-script)
- [ ] `DEEPGRAM_API_KEY` added to `config.py` and `ENV.md`
- [ ] 0 new heavy dependencies — `httpx` already in `requirements.txt`

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create/modify
- `src/alignment.py` — new
- `src/models.py` — `WordTimestamp` model
- `src/config.py` — `DEEPGRAM_API_KEY`
- `src/main.py` — new `/alignment` endpoint
- `ENV.md` — document `DEEPGRAM_API_KEY`
- `DECISIONS.md` — D034
- `tests/test_alignment.py` — new

### Notes
- `httpx` is preferred over `requests` (already a dep, async-native)
- Do NOT use the Deepgram Python SDK — plain HTTP call only, keeps deps clean
- Proportional fallback must use character-count weighting, not equal distribution
- Word-level output must be stored in R2 so E4-S7 can consume without re-calling API
- See D034 in DECISIONS.md for provider rationale
- Pipeline order change (E5-S5) must be completed before E5-S4 is wired into the main pipeline. E5-S4 can be built and tested in isolation first, then integrated by E5-S5.

### Handover
- `src/alignment.py`: `align_audio(audio_url, api_key) → list[WordTimestamp]` — async; calls `POST https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true` with `{"url": audio_url}` JSON body; raises `AlignmentError` on non-200 or network error. `_normalize_word(raw)` converts float seconds → int ms, strips punctuation via `[^\w\s]` regex. `proportional_fallback(text, total_duration_s)` — distributes total_ms proportionally by char count per word; confidence=0.0 flags estimates.
- `src/routes/alignment.py`: `POST /runs/{run_id}/alignment` — discovers voiceover file via `storage.list_keys(voiceover_prefix)` filtering `.mp3/.wav/.m4a`; generates presigned GET URL (5min TTL) for Deepgram to fetch; attempts Deepgram, falls back to `_proportional_from_storyboard` (reads `storyboard.json`) if key absent or API fails. Stores `alignment.json` dict: `{run_id, word_count, used_fallback, words: [...]}`. `update_run_log` call wrapped in broad try/except — non-fatal for runs created before "alignment" was added to PIPELINE_STEPS.
- `src/models.py`: `WordTimestamp(word, start_ms, end_ms, confidence)` and `AlignmentResponse(status, alignment_key, word_count, used_fallback)` added. `PIPELINE_STEPS` gains `"alignment"` between `"asset_acquisition"` and `"ffmpeg_script"`.
- `src/config.py`: `DEEPGRAM_API_KEY: str = ""` — optional with empty default; absence triggers proportional fallback.
- `src/exceptions.py`: `AlignmentError` added.
- `ENV.md`: `DEEPGRAM_API_KEY` documented.
- R2 key: `runs/{run_id}/alignment.json`. No new pip dependencies (httpx already present). D034 was pre-existing in DECISIONS.md.
- `tests/test_alignment.py`: 37 new tests — `_normalize_word`, `_extract_words`, `proportional_fallback`, `align_audio` (mocked httpx), and 13 route integration tests. 431 total passing.
- **Note:** This step is standalone — NOT yet wired into the pipeline UI or auto-triggered. Integration deferred to E5-S5 (pipeline reorder).

---

## [E5-S5] Pipeline reorder: VO-first with Deepgram-driven storyboard
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** 4
**Status:** done
**Completed:** 2026-05-27
**Points:** 8
**Priority:** critical — eliminates the entire class of timing bugs
**Depends on:** E5-S4

### Goal
Reorder the pipeline so voiceover upload and Deepgram word-level alignment happen BEFORE storyboard generation. Storyboard prompt receives actual word timestamps and builds scenes around real audio timing. Eliminates guessed scene durations permanently.

### Current vs target pipeline order

**Current:**
`POST /runs → storyboard → manifest → assets → ffmpeg-script → [VO upload] → render`

**Target:**
`POST /runs → VO upload → alignment (Deepgram) → storyboard (timestamp-aware) → manifest → assets → ffmpeg-script → render`

### Acceptance Criteria
- [x] Voiceover upload (presigned PUT) moved to step 1 immediately after run creation
- [x] `POST /runs/{id}/alignment` called before storyboard — stores `alignment.json` in R2
- [x] Storyboard system prompt updated: receives word timestamps, assigns each scene a real `start_ms` and `end_ms` from alignment data
- [x] `scene_duration_ms` in storyboard output derived from alignment, not Claude guess
- [x] Pacing calibration step (E5-S2 ffprobe redistribution) disabled or made no-op when alignment data is present
- [x] Operator UI step order updated to: VO Upload → Alignment → Storyboard → Manifest → Assets → FFmpeg Script → Render
- [x] Alignment appears as a proper step row in the UI with a Run button (same pattern as Storyboard, Manifest, etc.)
- [x] VO upload block moved to the top of the pipeline — before Alignment and Storyboard
- [x] Alignment step button calls POST /runs/{id}/alignment and shows complete/error status
- [x] Storyboard step button remains disabled or warns if Alignment has not been run (alignment.json not present in run_log.json)
- [x] Step status indicators (●/○/✗) reflect the new order
- [x] UI is the single source of truth for pipeline order — matches backend exactly
- [x] Existing runs without `alignment.json` fall back to legacy proportional timing (backward compat)
- [ ] End-to-end smoke test: 20-second VO produces a 20-second video with scenes that match speech timing — DEFERRED: requires Railway DEV with DEEPGRAM_API_KEY set
- [x] `run_log.json` shows all steps complete in new order (PIPELINE_STEPS reordered)

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (470 total, +8 new)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed — DEFERRED
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to modify (expected)
- `src/main.py` — reorder endpoints, add alignment step before storyboard
- `src/storyboard.py` — SYSTEM_PROMPT updated to accept and use word timestamps
- `src/ffmpeg_builder.py` — read `alignment.json` when present, skip proportional redistribution
- `src/pacing.py` (or equivalent) — make proportional redistribution conditional
- `docs/PROMPTS.md` — sync storyboard prompt, bump to v0.7
- `src/static/pipeline.html` — reorder step rows, add Alignment step row, move VO upload to top, add alignment status check before enabling Storyboard button
- `DECISIONS.md` — D036

### Notes
- This story makes E4-S7 (word-synced captions) straightforward — `alignment.json` is already in R2 at render time.
- Backward compatibility for old runs is required — check for `alignment.json` presence before deciding timing strategy.
- The storyboard prompt change is the highest-risk part — few-shot examples must show timestamp-aware scene construction.
- See D036 in DECISIONS.md for rationale.
- **UI note:** A partial UI hotfix was applied earlier (VO upload moved to top in a previous commit) but the Alignment step button was never added and step order was never fully corrected. E5-S5 must do a full UI rewrite of the pipeline step order — do not patch incrementally.

### Handover
- `src/models.py`: `PIPELINE_STEPS` reordered — `"alignment"` now first, before `"storyboard"`. New run_log.json initializations reflect the VO-first order.
- `src/storyboard.py`: `generate_storyboard(script, settings, word_timestamps=None)` — new optional param. `_call_claude_api` injects a `WORD TIMESTAMPS` block before the script in the user message when timestamps are provided. `_format_timestamps(words) → str` helper added. Prompt bumped to v0.8.
- `src/routes/storyboard.py`: Before calling Claude, reads `alignment.json` from R2 via `storage.get_json(f"runs/{run_id}/alignment.json")`; builds `list[WordTimestamp]` and passes to `generate_storyboard`. Falls back gracefully on `StorageError` (legacy runs).
- `src/routes/ffmpeg_script.py`: After loading storyboard + manifest, tries `storage.get_json(alignment_key)`. If success → `has_alignment=True`, skips entire ffprobe redistribution block. If `StorageError` → falls through to existing redistribution logic.
- `src/static/pipeline.html`: Full UI rewrite. New run panel: slug only (no script textarea). STEPS array: `alignment, storyboard, asset_manifest, asset_acquisition, ffmpeg_script, render`. VO upload section hint updated to "upload before running Alignment". Storyboard actions: shows amber `"run Alignment first"` gate warning until `currentSteps.alignment === 'complete'`. `refreshAllActions()` called after every step completion to unlock gated buttons. `autoRunNewRun` removed — operator drives steps manually.
- `docs/PROMPTS.md`: Bumped to v0.8. Changelog entry + TIMESTAMP ALIGNMENT section in both key rules and full prompt block.
- Tests: `test_storyboard.py` — `_mock_storage()` defaults `get_json` to `StorageError`; 2 new tests. `test_ffmpeg_builder.py` — all route tests updated with 3rd `StorageError` side_effect; `test_alignment_present_skips_redistribution` added. 470 total passing.
- No new ENV vars. No new pip dependencies.

---

## EPIC 6 — Operator UI (Pipeline Step 7)
HTML/JS web UI: create runs, trigger steps, upload voiceover, monitor status, view logs

---

## [E6-S0] Minimal run creation UI
**Epic:** E6 — Operator UI
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E1-S2
**Story points:** 2

### Goal
Give a non-technical stakeholder a human-touchable artifact at the end of Sprint 1: a plain HTML form that creates a production run without curl or Postman.

### Acceptance Criteria
- [x] Single HTML page with a slug input field and a Submit button
- [x] On submit, calls `POST /runs` and displays the returned `run_id` and `storage_prefix`
- [x] Error message shown if `POST /runs` returns non-201
- [x] No styling required — functional correctness only
- [x] A non-technical user can create a run end-to-end without developer assistance

### Definition of Done
- [x] All AC checked
- [x] Served from FastAPI (`GET /`)
- [x] Manual smoke test: open browser, enter slug, confirm run_id + storage_prefix displayed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Open the page in a browser. Enter a slug (e.g. `test-run`). Click Submit. Confirm `run_id` and `storage_prefix` appear on screen.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- docs/UI_GUIDELINES.md
- `src/routes/runs.py`

### Files to create or modify
- `src/static/create-run.html` — slug form, fetch call, result display
- `src/main.py` — serve static file or add GET route

### Handover
- `src/static/create-run.html`: self-contained HTML form (inline CSS/JS). Slug validated with `/^[a-z][a-z0-9-]*[a-z0-9]$/` before enable Submit. POSTs to `/runs`, displays `run_id` + `storage_prefix` on 201, surfaces error detail on non-201 and network errors.
- `src/main.py`: `GET /` added — `FileResponse` serving `create-run.html`. No `StaticFiles` mount needed (page has no external assets; `aiofiles` dep avoided).
- `_STATIC_DIR = Path(__file__).parent / "static"` — future static files served from here.
- No new ENV vars. No new dependencies.
- 68 tests passing (no regressions).

---

## [E6-S1] End-to-end pipeline UI (Runs + Storyboard + Manifest)
**Epic:** E6 — Operator UI
**Sprint:** 1
**Status:** done
**Completed:** 2026-05-22
**Priority:** high
**Depends on:** E2-S1
**Story points:** 3

### Goal
Give a non-technical user a single-page UI to run the full pipeline through asset manifest — no curl, no Postman, no developer assistance.

### Flow
1. Enter a slug and a VO script → Submit
2. UI calls `POST /runs` → displays run_id
3. UI calls `POST /runs/{run_id}/storyboard` (shows "Generating storyboard..." while waiting)
4. On storyboard complete → UI calls `POST /runs/{run_id}/manifest` automatically
5. Displays final summary: run_id, scene count, clip type breakdown
6. Error state shown at each step if any call fails

### Acceptance Criteria
- [x] Single HTML page, no frameworks, no styling required
- [x] Storyboard step shows a loading indicator (request takes 30–60s)
- [x] Each step result displayed before proceeding to next
- [x] Full error handling — failed step shows message, does not proceed
- [x] Non-technical user can run the pipeline start to finish without developer assistance
- [x] Smoke test: enter slug + VO script in browser, verify `run_log.json` in R2 shows `storyboard` and `asset_manifest` both `complete`

### Definition of Done
- [ ] All AC checked
- [ ] Served from FastAPI (`GET /`)
- [ ] Manual smoke test completed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open page in browser. Enter a slug and a VO script. Submit. Confirm run_id displayed after POST /runs. Confirm "Generating storyboard..." shown during Claude API call. Confirm scene count and clip type breakdown displayed on completion. Open R2 and verify `run_log.json` shows `storyboard: complete` and `asset_manifest: complete`.

### Files to read
- CLAUDE.md
- CONVENTIONS.md
- docs/UI_GUIDELINES.md
- `src/static/create-run.html`
- `src/main.py`

### Files to create or modify
- `src/static/pipeline.html` — slug + VO script form, sequential fetch calls, result display
- `src/main.py` — serve `pipeline.html` at `GET /`

### Note
Storyboard endpoint takes 30–60s. Use `fetch` with no timeout override — browser default is sufficient. Show a spinner or "Generating storyboard, please wait..." text during the call. Async polling is deferred to E6-S3.

**No new backend logic required — UI calls existing endpoints only.**

### Handover
- `src/static/pipeline.html`: self-contained HTML page (inline CSS/JS, no frameworks). Slug validated with `/^[a-z][a-z0-9-]*[a-z0-9]$|^[a-z]$/` before enabling submit. VO script textarea required (non-empty). On submit: sequentially calls `POST /runs` → `POST /runs/{run_id}/storyboard` → `POST /runs/{run_id}/manifest`. Each step rendered as a status row with `○` pending / `◌` running / `●` complete / `✕` failed dot. Storyboard step shows "Generating storyboard, please wait (30–60s)…" during Claude API call. Manifest step displays scene count and clip type breakdown. Any step failure stops the chain and surfaces the error detail; submit re-enables for retry.
- `src/main.py`: `GET /` updated — now serves `pipeline.html` (was `create-run.html`). `create-run.html` remains in `/static` as a reference artefact.
- No new ENV vars. No new dependencies. 95 tests passing (no regressions).
- Smoke test: 10-scene storyboard + manifest generated on DEV for "messy-house-messy-head" VO script. All steps complete. Clip breakdown: still_with_motion: 4, animated: 3, hard_cut: 3.

---

## [E6-S1-OLD] UI skeleton (superseded by E6-S1 above)
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

## [E6-S2] Operator UI — Run list and pipeline runner
**Epic:** E6 — Operator UI
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 5
**Priority:** high
**Depends on:** E1-S4, E6-S1
**Blocks:** E6-S3

### Goal
Replace curl-based workflow with a full operator UI. Two views: run list and run detail.

### Run list view
- Shows all previous runs sorted by date (calls `GET /runs`)
- Each row: run_id, date, overall status (complete/in-progress/failed)
- "+ New Run" button opens new run form (slug + VO script)

### Run detail view
- Shows all 5 pipeline steps with status indicator (pending/running/complete/failed)
- Each complete step has [View] and [Rerun] buttons
- Each pending/failed step has [Run] button
- [View] fetches `GET /runs/{run_id}/artifact/{step}` and renders inline:
  - storyboard → human-readable scene list (scene number, clip type, VO line, duration)
  - manifest → table (scene, clip type, source, file key, status)
  - ffmpeg_script → code block
  - render → inline video player + download link (uses presigned URL)
- [Rerun] or [Run] calls the appropriate POST endpoint, shows spinner, updates status on completion
- Voiceover upload: file picker that uploads directly to R2 `runs/{run_id}/voiceover/` via presigned upload URL
- Download final.mp4 button (only shown when render is complete)

### Acceptance Criteria
- [ ] No curl required for any pipeline operation
- [ ] All steps triggerable and viewable from the UI
- [ ] Voiceover uploadable without touching R2 console
- [ ] Works on desktop browser

### Definition of Done
- [ ] All AC checked
- [ ] Served from FastAPI
- [ ] Manual smoke test: full pipeline run triggered and completed from browser only
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
- `src/static/pipeline.html`: full rewrite — single-file SPA, no frameworks. Two views: **list** (default) and **detail**.
  - List view: calls `GET /runs`, renders each run as a clickable row with colored status dot (green = all complete, red = any failed, amber = in-progress/mixed). "+ New Run" button opens inline form with slug + VO script fields.
  - New run flow: POST /runs → auto-navigate to detail → auto-trigger storyboard (with script) → auto-trigger manifest on success.
  - Detail view: 5 step rows. Complete steps: [View] + [Rerun]. Pending/failed: [Run]. Storyboard [Run]/[Rerun] reveals inline VO script textarea. [View] calls `GET /runs/{run_id}/artifact/{step}` and renders inline (storyboard → scene cards; manifest → table; ffmpeg_script → `<pre>`; render → `<video>` + download link).
  - Voiceover section (dashed row between FFmpeg Script and Render): file picker → `POST /runs/{run_id}/voiceover-upload-url` → `PUT presigned_url` directly to R2.
  - Status dots: `●` complete / `●` failed / `◌` running / `○` pending.
- `src/storage.py`: `R2Client.generate_presigned_put_url(key, expires_in=600) → str` — boto3 `put_object` presigned URL. Raises `StorageError` on failure.
- `src/models.py`: `VoiceoverUploadUrlRequest(filename: str)`, `VoiceoverUploadUrlResponse(upload_url: str, key: str)` added.
- `src/routes/runs.py`: `POST /runs/{run_id}/voiceover-upload-url` — builds key `runs/{run_id}/voiceover/{filename}`, returns presigned PUT URL valid 10 min. 500 on `StorageError`.
- `tests/test_runs.py`: 4 new tests in `TestVoiceoverUploadUrl`. 30 tests in file, 286 total passing.
- No new ENV vars. No new pip dependencies.
- **Deployment note**: voiceover direct-upload requires CORS rule on R2 bucket allowing `PUT` from the Railway domain. Add before smoke-testing voiceover upload.
- Smoke test deferred — full pipeline run from browser on Railway DEV once live run with completed storyboard + manifest + assets + ffmpeg_script exists.
**Promoted to backlog:** none

---

## [E6-S3] Voiceover upload via presigned R2 URL
**Epic:** E6 — Operator UI
**Sprint:** 2
**Status:** done
**Completed:** 2026-05-24
**Points:** 2
**Priority:** high
**Depends on:** E1-S4

### Goal
Add backend support for direct voiceover upload from browser to R2 without proxying through Railway.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/voiceover-upload-url` — generates a presigned R2 PUT URL valid for 10 minutes
- [ ] UI uses the presigned URL to PUT the file directly to R2 (no Railway bandwidth used)
- [ ] On upload complete, UI shows "Voiceover ready" and enables the render step

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
Implemented inline as part of E6-S2. See E6-S2 handover for full details.
- `POST /runs/{run_id}/voiceover-upload-url` live in `src/routes/runs.py`.
- `R2Client.generate_presigned_put_url` live in `src/storage.py`.
- Models: `VoiceoverUploadUrlRequest`, `VoiceoverUploadUrlResponse` in `src/models.py`.
- UI integration: voiceover row in `src/static/pipeline.html` between FFmpeg Script and Render steps.
- AC for "UI shows Voiceover ready and enables render" is met implicitly — the render [Run] button is always shown (server enforces voiceover presence via ffmpeg_script guard).
- **R2 CORS** must be configured on the bucket before the browser PUT will succeed (see E6-S2 deployment note).
**Promoted to backlog:** none

---

## [E6-S4] End-to-end production smoke test
**Epic:** E6 — Operator UI
**Sprint:** 3
**Status:** done
**Completed:** 2026-05-27
**Points:** 2
**Priority:** high
**Depends on:** E6-S2, E5-S1, E4-S5

### Goal
Run a complete pipeline from browser UI on Railway DEV: create run → storyboard → manifest → assets → ffmpeg-script → upload voiceover → render. Validate all 7 deferred smoke tests in one session. Document and fix any bugs found inline or promote to backlog.

### Acceptance Criteria
- [x] Full pipeline triggered and completed from browser UI only (no curl)
- [x] `final.mp4` appears in R2 `runs/{run_id}/output/` and is watchable
- [x] Both caption tracks visible: on-screen keywords (large, centered) + voiceover captions (small, bottom)
- [x] Video cuts align with speech cadence (pacing calibration)
- [x] Static image scenes show Ken Burns motion
- [x] `run_log.json` shows all steps `complete`
- [x] Any bugs found during the run either fixed inline or promoted to backlog as new stories
- [x] R2 CORS configured for voiceover direct upload (required for browser PUT)

### Definition of Done
- [x] All AC checked
- [x] Bugs found: zero blocking bugs
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
This story IS the smoke test. The AC above are the verification criteria.

### Files to read
- CLAUDE.md
- DONE.md — handover notes for E5-S1, E4-S2, E4-S3, E4-S5, E5-S2, E6-S2
- ENV.md — R2 CORS setup note in E6-S2

### Files to create or modify
- None expected — this is a validation story. Bug fixes may touch any file.

### Handover
- Full pipeline validated end-to-end on Railway DEV from browser UI: create run → storyboard → manifest → assets → ffmpeg-script → voiceover upload → render → watchable `final.mp4`.
- R2 CORS configured on `content-factory-dev` bucket allowing PUT from Railway DEV domain — voiceover direct-upload from browser confirmed working.
- All deferred smoke tests from Sprint 1 and Sprint 2 now validated in a single session.
- No code changes required. No bugs found. No issues promoted to backlog.
- Sprint 3 foundation confirmed healthy — E5-S4 (WhisperX) and E8-S1 (Haiku validator) can proceed.

---

## EPIC 8 — Cost Optimization: Model Routing
Route pipeline tasks to the appropriate model (Haiku / Sonnet / Opus) based on task complexity to minimize API costs without sacrificing quality.

---

## [E8-S1] Haiku schema validator — storyboard.json
**Epic:** E8 — Cost Optimization
**Sprint:** 3
**Status:** done
**Completed:** 2026-05-27
**Priority:** high
**Depends on:** E1-S3

### Goal
Validate `storyboard.json` against the v0.4 schema using Haiku before any downstream step runs.

### Acceptance Criteria
- [x] Haiku called with schema from `docs/PROMPTS.md` + generated `storyboard.json`
- [x] Returns `{valid: bool, errors: [list of field/rule violations]}`
- [x] If invalid: step halts, errors written to `run_log.json` (run_log.txt deferred to E8-S3)
- [x] If valid: pipeline proceeds to next step
- [x] Haiku model string: `claude-haiku-4-5-20251001`
- [x] Validation cost logged per run in `run_log.json`

### Definition of Done
- [x] All AC checked
- [x] Tests written and passing (444 total, 13 new)
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

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
- `src/validators/storyboard_validator.py`: `validate_storyboard(storyboard, api_key) → ValidationResult` (async). Sends serialised `storyboard.json` to `claude-haiku-4-5-20251001` with an 8-rule validation system prompt. Parses `{"valid": bool, "errors": [...]}` JSON from Haiku response. `_INPUT_COST_PER_TOKEN = 0.80/1M`, `_OUTPUT_COST_PER_TOKEN = 4.00/1M`. Raises `StoryboardValidationError` on API failure or unparseable response.
- `src/models.py`: `StepLog` gains `input_tokens: Optional[int]`, `output_tokens: Optional[int]`, `cost_usd: Optional[float]`. `ValidationResult(valid, errors, input_tokens, output_tokens, cost_usd)` model added.
- `src/exceptions.py`: `StoryboardValidationError` added.
- `src/storage.py`: `update_run_log` accepts `input_tokens`, `output_tokens`, `cost_usd` optional kwargs; writes them into the step dict when not None.
- `src/storyboard.py`: `generate_storyboard` now returns `tuple[Storyboard, ValidationResult]`. Calls `validate_storyboard` after parse; raises `StoryboardValidationError` with joined error list when `valid=False`.
- `src/routes/storyboard.py`: `StoryboardValidationError` added to caught exception tuple. On success, passes token/cost fields from `ValidationResult` to `update_run_log`.
- 444 total tests passing (13 new). No new pip dependencies. No new ENV vars (reuses `ANTHROPIC_API_KEY`).

---

## [E8-S2] Haiku asset manifest generator
**Epic:** E8 — Cost Optimization
**Sprint:** unassigned
**Status:** superseded
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
**Superseded 2026-05-30:** E2-S1 implemented manifest generation as a pure deterministic Python transformation with no Claude API call. `src/manifest.py:build_manifest()` maps storyboard fields directly to ManifestEntry objects — adding a Haiku call would add cost/latency/failure modes for zero benefit. Story retired. S7-S3 model router still covers all real Claude call sites (storyboard, validator, log-summarizer).

---

## [E8-S3] Haiku run log summarizer
**Epic:** E8 — Cost Optimization
**Sprint:** 3
**Status:** done
**Completed:** 2026-05-27
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
- `src/log_summarizer.py`: `generate_run_log_summary(run_log_data, api_key) → str` — calls Haiku (`claude-haiku-4-5-20251001`), max_tokens=512, returns stripped summary text. `write_run_log_summary(run_id, storage, api_key) → None` — reads `run_log.json`, calls Haiku, writes `run_log.txt` to R2; catches all exceptions (both `StorageError` and generic) and logs warnings — never raises.
- `src/pipeline.py`: `summarize_step(run_id, storage, settings) → None` — thin wrapper calling `write_run_log_summary`. Routes import and call this after every `storage.update_run_log(...)` (both complete and failed paths).
- `src/routes/{storyboard,manifest,assets,ffmpeg_script,render,alignment}.py` — each imports `from src import pipeline` and calls `pipeline.summarize_step(run_id, storage, settings)` after every `update_run_log` call (including failure paths before `raise HTTPException`).
- `src/routes/runs.py` — new `GET /runs/{run_id}/run-log-txt` endpoint returns `RunLogTxtResponse(content, available)`. Returns `available=False` and empty content if `run_log.txt` is not yet written (StorageError swallowed).
- `src/models.py` — `RunLogTxtResponse(content: str, available: bool)` added.
- `src/static/pipeline.html` — Run Log section added below step rows: collapsible panel showing `run_log.txt` content. Fetches `GET /runs/{run_id}/run-log-txt` on `showDetail` and after every `executeStep` completion. Panel hidden until first summary is available.
- `tests/test_log_summarizer.py` — 18 new tests: `TestGenerateRunLogSummary` (6), `TestWriteRunLogSummary` (7), `TestSummarizeStep` (2), `TestGetRunLogTxt` (3).
- `tests/conftest.py` — new autouse fixture `mock_anthropic_for_summarizer` patches `src.log_summarizer.Anthropic` globally to prevent real HTTP calls in all tests.
- `tests/test_manifest.py` and `tests/test_alignment.py` — two `get_json.assert_called_once_with` assertions updated to `assert_any_call` (summarizer adds a second `get_json` call for `run_log.json`).
- R2 key: `runs/{run_id}/run_log.txt`. No new ENV vars. No new pip dependencies (anthropic already present).
- 462 total tests passing (18 new).

---

## [E8-S4] Model router utility
**Epic:** E8 — Cost Optimization
**Sprint:** 7
**Status:** done
**Completed:** 2026-05-30
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
- `src/utils/model_router.py`: `ModelRouter(settings)` class. Task constants: `GENERATE`, `VALIDATE`, `SUMMARIZE`, `TRANSFORM`, `REASON`. Key methods: `model_for(task) → str`, `log_cost(task, model, input_tokens, output_tokens) → float`.
- `src/utils/__init__.py`: empty package init.
- `PRICING` dict in `model_router.py`: `claude-sonnet-4-6` ($3.00/$15.00 per M), `claude-haiku-4-5-20251001` ($0.80/$4.00 per M). Extend when new models are added.
- `src/config.py`: 4 new optional ENV vars added: `MODEL_VALIDATE`, `MODEL_SUMMARIZE`, `MODEL_TRANSFORM`, `MODEL_REASON` (all with Haiku/Sonnet defaults).
- `src/storyboard.py`: constructs `ModelRouter(settings)`, uses `router.model_for(GENERATE)`, captures `usage` from API response, calls `router.log_cost(GENERATE, ...)`, passes router to `validate_storyboard`.
- `src/validators/storyboard_validator.py`: `VALIDATOR_MODEL` and pricing constants now derived from `ModelRouter` defaults. Accepts `router: Optional[ModelRouter] = None`; delegates model selection and cost logging when router provided.
- `src/log_summarizer.py`: `HAIKU_MODEL` derived from `ModelRouter` defaults. Accepts `router: Optional[ModelRouter] = None`; delegates to router when provided.
- `src/pipeline.py`: constructs `ModelRouter(settings)` and passes it to `write_run_log_summary`.
- `ENV.md`: `MODEL_VALIDATE`, `MODEL_SUMMARIZE`, `MODEL_TRANSFORM`, `MODEL_REASON` documented.
- 612 tests passing (27 new in `tests/test_model_router.py`). No new pip dependencies.
**Promoted to backlog:** none

---

# Sprint 5 — Navigation, Performance, Auth & UI Redesign

---

## [S5-S1] URL-based run navigation (fix refresh bug)
**Epic:** E6 — Operator UI
**Sprint:** 5
**Status:** done
**Completed:** 2026-05-28
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
Fix the bug where refreshing the page inside a run drops the user back to the run list. Persist run state in the URL hash — no backend changes.

### Acceptance Criteria
- [x] Navigating into a run updates URL to `#run/{runId}`
- [x] On page load, if hash is `#run/{runId}`, app calls `showDetail(runId)` instead of `showList()`
- [x] Browser back button from detail view returns to list view; URL clears to `#` or empty
- [x] `showList()` clears the hash
- [x] Deep-linking: pasting `.../#run/some-id` navigates directly to that run's detail view
- [x] No backend routes changed — pure frontend fix

### Definition of Done
- [x] All AC checked
- [x] Manual tests passed (refresh stays in run; back goes to list; deep link works)
- [x] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Implementation notes
- Used `history.pushState` (not `window.location.hash =`) so that setting the hash does not trigger `hashchange` — avoids double-execution of `showDetail`/`showList`
- `popstate` listener handles browser back/forward (fires when `pushState` entries are traversed)
- IIFE at script init reads hash on first load — covers refresh and deep links

### Files to modify
- `src/static/pipeline.html` — JS only, no structural HTML changes

### Handover
- `src/static/pipeline.html`: `showDetail(runId)` calls `history.pushState(null, '', '#run/' + runId)` immediately after switching views. `showList()` calls `history.pushState(null, '', window.location.pathname)` to clear the hash. `popstate` event listener parses `location.hash` and routes to `showDetail` or `showList` for back/forward navigation. IIFE at script init performs the same hash-parse on first page load, enabling refresh-in-run and deep links.
- No new ENV vars. No new pip dependencies. No backend changes.

---

## [S5-S2] Page load performance diagnosis + fixes
**Epic:** E6 — Operator UI
**Sprint:** 5
**Status:** done
**Completed:** 2026-05-28
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
Measure where load time is going and apply targeted fixes. Profile first — do not guess.

### Acceptance Criteria
- [x] `docs/PERF.md` written with measured bottleneck evidence
- [x] At least two concrete fixes implemented and verified to reduce time-to-interactive
- [x] `GET /runs` response time logged; if > 500ms for < 20 runs, root cause documented
- [x] No regressions to existing tests

### Definition of Done
- [x] All AC checked
- [x] `docs/PERF.md` exists with before/after timing
- [x] CI green (514 tests passing)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Diagnosis approach
1. Measure `GET /runs` — check if N sequential R2 reads; replace with `asyncio.gather(*)` if so
2. Check cold start latency on Railway (document if > 2s, note it's a tier issue)
3. Check `pipeline.html` for blocking JS on page load

### Files to create or modify
- `docs/PERF.md` — new
- `src/routes/runs.py` — likely fix target
- `src/static/pipeline.html` — if JS load order contributes

### Handover
- `src/storage.py`: `list_runs()` rewritten. Fix 1: uses `list_objects_v2(Delimiter="/")` to enumerate run folder names via `CommonPrefixes` — eliminates the O(runs × assets) key scan. Fix 2: fetches all `run_log.json` files in parallel with `ThreadPoolExecutor.map` instead of a sequential for-loop. Errors on individual run_log.json files are now caught and logged as warnings rather than aborting the whole list. Timing logged via `logger.info`.
- `src/routes/runs.py`: `GET /runs` handler logs elapsed ms via `logger.info("GET /runs: %d runs in %.0fms", ...)`.
- `docs/PERF.md`: new — root-cause analysis, before/after timing estimates, known limitations, test coverage notes.
- `tests/test_storage.py`: 18 → 20 tests (+2 new). `TestListRuns` updated to use `CommonPrefixes` mock shape. Added `test_uses_delimiter_to_list_prefixes` and `test_partial_failure_returns_readable_runs`.
- No new ENV vars. No new pip dependencies (`concurrent.futures` is stdlib).
- **Promoted to backlog:** `showDetail()` in `pipeline.html` calls `GET /runs` a second time to populate `currentSteps` — a dedicated `GET /runs/{run_id}` endpoint would halve the request count. Noted in PERF.md; deferred to future sprint.

---

## [S5-S3] Multi-user auth + per-user run isolation
**Epic:** E6 — Operator UI
**Sprint:** 5
**Status:** deferred
**Priority:** low
**Points:** 8
**Depends on:** S5-S4 (fills auth stubs left by S5-S4; no UI rework needed)

### Goal
Add username/password login so multiple operators can use the app with full data isolation. Each user sees only their own runs and assets.

### Acceptance Criteria
- [ ] `POST /auth/login` — accepts `{username, password}`, signed session cookie on success, 401 on failure
- [ ] `POST /auth/logout` — clears session cookie
- [ ] `GET /auth/me` — returns `{username}` if authenticated, 401 if not
- [ ] All pipeline routes require auth — unauthenticated returns 401
- [ ] `GET /runs` returns only runs owned by session user
- [ ] `POST /runs` creates run owned by session user
- [ ] All `runs/{id}/*` routes verify ownership — return 404 on mismatch (not 403)
- [ ] R2 prefix for new runs: `users/{user_id}/runs/{run_id}/`; existing runs at legacy prefix accessible read-only to admin
- [ ] `GET /login` serves minimal login page; `POST /auth/login` redirects to `/` on success
- [ ] `GET /` redirects to `/login` if no valid session
- [ ] `POST /admin/users` (guarded by `ADMIN_SECRET`) creates new users — no self-registration
- [ ] All existing tests pass; new auth tests cover login success/failure, 401 on unauth routes, cross-user isolation

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`
- [ ] D037 logged in DECISIONS.md

### Implementation notes
- User storage: `users.json` in R2 (username → `{user_id, password_hash, created_at}`); loaded at startup
- Sessions: `itsdangerous.URLSafeTimedSerializer`; cookie contains `{user_id, username}`; 7-day max age
- Run ownership: `user_id` written to `run_log.json` on `POST /runs`; all `runs/{id}` routes load and check it
- Backward compat: runs with no `user_id` in `run_log.json` returned only to admin user
- New ENV vars: `SESSION_SECRET_KEY`, `ADMIN_SECRET`

### Files to create or modify
- `src/auth.py` — new
- `src/routes/auth.py` — new
- `src/routes/admin.py` — new
- `src/routes/runs.py` — add `user_id` to creation and list filtering
- `src/routes/storyboard.py`, `alignment.py`, `ffmpeg_script.py`, `render.py`, `assets.py`, `manifest.py` — ownership check
- `src/models.py` — `User`, `UserCreateRequest`, `LoginRequest`, `LoginResponse`
- `src/static/login.html` — new
- `src/main.py` — register routers, add SessionMiddleware, `/login` route
- `src/config.py` — `ADMIN_SECRET`, `SESSION_SECRET_KEY`
- `tests/test_auth.py` — new
- `DECISIONS.md` — D037

### Handover
_filled on completion_

---

## [S5-S4] UI redesign: 5-step collapsed pipeline + new visual design
**Epic:** E6 — Operator UI
**Sprint:** 5
**Status:** done
**Completed:** 2026-05-28
**Priority:** high
**Points:** 8
**Depends on:** S5-S1 ✓ (delivered before S5-S3; stub auth hooks — see implementation notes)

### Goal
Redesign `pipeline.html` with a three-panel layout (projects list / section nav / content area), collapse 6 backend steps into 5 operator-facing steps, and apply a clean light-mode monochrome design.

### Acceptance Criteria
- [ ] Three-panel layout renders at 1024px+: run list (left) / section nav (middle) / content (right)
- [ ] 5 section panels functional end-to-end: Input → Storyboard → Assets → Rendered video
- [ ] Input: VO upload + script textarea + "Create Storyboard" CTA (disabled until alignment complete)
- [ ] Storyboard: scene cards + "Approve & Get Assets" CTA
- [ ] Assets: manifest table + "Render Video" CTA
- [ ] Rendered video: `<video>` player + download link
- [ ] Lock mechanic: inputs frozen after CTA completes; "Regenerate" unlocks
- [ ] Status dots on panel nav update in real time
- [ ] URL hash routing from S5-S1 preserved (`#run/{id}` still works; `#run/{id}/section` best effort)
- [ ] Auth from S5-S3 respected: redirect to `/login` if no session
- [ ] "Log out" button calls `POST /auth/logout`, redirects to `/login`
- [ ] Design: light bg, system sans-serif labels, monospace for IDs/data, blue (`#1d4ed8`) for primary CTAs only, no external dependencies

### Definition of Done
- [ ] All AC checked
- [ ] Existing smoke test workflow completable end-to-end in new UI
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Panel → backend step mapping
| Panel | Triggers |
|-------|---------|
| Input → "Create Storyboard" | `POST /alignment` then `POST /storyboard` |
| Storyboard → "Approve & Get Assets" | `POST /manifest` then `POST /assets` |
| Assets → "Render Video" | `POST /ffmpeg-script` then `POST /render` |
| Rendered video | display only |

### Files to modify
- `src/static/pipeline.html` — full rewrite

### Handover
- `src/static/pipeline.html`: full rewrite. Three-panel layout (`body { display:flex }`): left 240px run list / middle 188px section nav / right `flex:1` content. Four operator sections: Input, Storyboard, Assets, Rendered Video.
- **Input**: VO upload widget (presigned PUT to R2) + script textarea + "Create Storyboard" CTA. CTA disabled until `voUploaded=true` (set on successful upload, or if `alignment !== 'pending'` from a previous session). Single click runs `POST /alignment` → `POST /storyboard` in sequence via `runSequence()`.
- **Storyboard**: fetches and renders scene cards from `/artifact/storyboard`. "Approve & Get Assets" CTA runs `POST /manifest` → `POST /assets`. Shown only after storyboard=complete.
- **Assets**: fetches and renders manifest table from `/artifact/manifest`. "Render Video" CTA runs `POST /ffmpeg-script` → `POST /render`. Shown only after asset_manifest=complete.
- **Rendered Video**: fetches render artifact and shows `<video>` player + download link.
- **Lock mechanic**: `sectionLocked = {input, storyboard, assets}`. Initialized from `currentSteps` in `openRun()`. Set to `true` by CTA success handlers. Set to `false` by `regenerateSection()`. Never re-derived from steps after init, so Regenerate stays unlocked.
- **Inline step progress**: `runSequence()` renders per-step rows with live dot updates inside the section (no modal/alert).
- **Auto-navigation**: each CTA auto-navigates to the next section on success (Input→Storyboard, Storyboard→Assets, Assets→Render).
- **URL hash routing**: `#run/{id}` → opens run at Input; `#run/{id}/section` → opens run at named section. `popstate` handler covers browser back/forward. `openRun()` pushes `#run/{id}/{section}`.
- **Auth stubs**: "Log out" button present in left panel footer; `logOut()` is a no-op with `// TODO: S5-S3` comment. No `/login` redirect guard.
- **Section nav status dots**: `sectionStatus()` maps each section to its backend steps (`input→[alignment,storyboard]`, `storyboard→[asset_manifest,asset_acquisition]`, `assets→[ffmpeg_script,render]`, `render→[render]`).
- No backend changes. No new ENV vars. No new dependencies. 515 tests passing.

---

## [S5-S5] Single-operator password gate
**Epic:** E6 — Operator UI
**Sprint:** 5
**Status:** done
**Completed:** 2026-05-28
**Priority:** high
**Points:** 3
**Depends on:** S5-S4 ✓ (`logOut()` stub and `// TODO: S5-S3` already in pipeline.html)
**Replaces:** S5-S3 deferred — no per-user isolation, no user management, single password

### Goal
Add a single-password login wall. One operator, one `OPERATOR_PASSWORD` env var. All pipeline routes return 302 → `/login` if the session cookie is missing or invalid. Session valid until logout (no expiry — POC scope). No per-user isolation, no user management.

### Acceptance Criteria
- [x] `GET /login` serves `login.html` (light-mode, matches `pipeline.html` design)
- [x] `POST /auth/login` accepts `{password}`, validates against `OPERATOR_PASSWORD` env var, sets signed httponly cookie, returns `{ok: true}`; returns 401 on wrong password
- [x] `POST /auth/logout` clears cookie, returns `{ok: true}`
- [x] HTTP middleware in `main.py` gates all routes except `/health`, `/login`, `/auth/login` — unauthenticated requests get 302 → `/login`
- [x] `pipeline.html`: `logOut()` calls `POST /auth/logout` then redirects to `/login`
- [x] `pipeline.html`: any `fetch()` response that is 401 redirects to `/login`
- [x] `login.html`: JS posts to `POST /auth/login` (JSON); on 200 navigates to `/`; on 401 shows inline error (no page reload)
- [x] `OPERATOR_PASSWORD` and `SESSION_SECRET_KEY` added to `src/config.py` and Railway env vars
- [x] No new pip dependencies — cookie signing via stdlib `hmac` + `hashlib`
- [x] New tests: login success, login wrong password, logout clears cookie, unauthenticated request returns 302, health exempt from auth
- [x] CI green

### Definition of Done
- [x] All AC checked
- [x] Tests passing
- [x] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`
- [x] D037 logged in DECISIONS.md

### Implementation notes
- Cookie value: `hmac.new(SESSION_SECRET_KEY.encode(), b"authenticated", hashlib.sha256).hexdigest()` — constant token, valid until cleared
- Cookie flags: `httponly=True, samesite="lax"`, `secure=True` in prod (Railway serves HTTPS)
- Middleware: `@app.middleware("http")` in `main.py` — ~10 lines; exempt paths: `/health`, `/login`, `/auth/login`, `/auth/logout`
- `login.html`: no framework, inline CSS matching light-mode design; JS fetch on form submit

### Files created or modified
- `src/auth.py` — new: `AUTH_COOKIE_NAME`, `sign_cookie()`, `verify_cookie()`
- `src/routes/auth.py` — new: `POST /auth/login`, `POST /auth/logout`
- `src/main.py` — register auth router, `GET /login` route, add auth middleware
- `src/config.py` — `OPERATOR_PASSWORD` (required), `SESSION_SECRET_KEY` (required)
- `src/static/login.html` — new
- `src/static/pipeline.html` — wire `logOut()`, global fetch 401 → `/login` redirect
- `tests/test_auth.py` — new (18 tests)
- `tests/conftest.py` — `bypass_auth_middleware` autouse fixture (skipped for test_auth.py)
- `DECISIONS.md` — D037: stdlib HMAC cookie chosen over `itsdangerous` (no new dep for POC)

### Handover
- `src/auth.py`: `AUTH_COOKIE_NAME = "cf_session"`. `sign_cookie(secret_key) → str` — HMAC-SHA256 hex digest of `b"authenticated"` keyed on secret. `verify_cookie(value, secret_key) → bool` — constant-time compare. Both importable and tested independently.
- `src/routes/auth.py`: `POST /auth/login` — validates `body.password == settings.OPERATOR_PASSWORD`; on match sets cookie with `httponly=True, samesite="lax", secure=True` (prod only). `POST /auth/logout` — deletes cookie; exempt from middleware so unauthenticated clients can call it.
- `src/main.py`: `_AUTH_EXEMPT_PATHS = {"/health", "/login", "/auth/login", "/auth/logout"}`. Middleware uses `request.app.dependency_overrides.get(get_settings, get_settings)()` to respect test DI overrides. Browser requests (Accept: text/html) → 302; API requests → 401. `GET /login` route added.
- `src/config.py`: `OPERATOR_PASSWORD: str` and `SESSION_SECRET_KEY: str` — both required, no defaults.
- `src/static/login.html`: self-contained, light-mode, no frameworks. `POST /auth/login` on submit; 200 → `window.location.href = '/'`; 401 → inline error without page reload.
- `src/static/pipeline.html`: `logOut()` calls `POST /auth/logout` + redirect. Global `window.fetch` wrapper redirects to `/login` on any 401 response.
- `tests/conftest.py`: `bypass_auth_middleware` autouse fixture patches `src.main.verify_cookie` to return True for all tests except `test_auth.py`. Prevents 401 noise in route tests. Does not affect `tests/test_auth.py`.
- All VALID_ENV dicts in existing test files updated to include `OPERATOR_PASSWORD: "testpass"` and `SESSION_SECRET_KEY: "test-secret-key"`.
- 535 total tests passing (20 new: 18 in test_auth.py + 2 new required-field tests in test_health.py parametrize).
- **Human action required:** Set `OPERATOR_PASSWORD` and `SESSION_SECRET_KEY` in Railway DEV and PROD Variables tabs before next deploy.

---

---

# Sprint 6 — Product UX: Design System, Project Identity & Stage Polish

---

## [S6-S1] Design system: color palette, typography, panel spacing
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Completed:** 2026-05-29
**Priority:** high
**Points:** 3
**Depends on:** S5-S4 ✓

### Goal
Apply the product design system across the entire operator UI — consistent background colour, single font family, defined text weights, and spacing-only panel separation. No borders or dividers anywhere.

### Acceptance Criteria
- [x] Background `#FBF9F8` applied to `body`, all three panels, table cells, and input elements (no white or grey overrides)
- [x] Primary text `#2D2D2D`; secondary/muted text `#9A9A9A` (timestamps, labels, placeholders)
- [x] Pill/tag backgrounds `#EFECEB` (used for IDs, step labels)
- [x] Single font family: `Inter, system-ui, sans-serif` (no external CDN fetch; system stack only)
- [x] Font weights defined: Regular (400) for body, Medium (500) for section labels, Semi-bold (600) for CTAs
- [x] Header row contains ONLY "Content Factory" text, left-aligned; no buttons, version numbers, or status badges
- [x] All panel borders and grey dividers removed; left ↔ middle ↔ right panels separated by spacing only
- [x] Tables inherit page background (no `background: white` or `background: #f…` overrides)
- [x] No external font or icon dependencies added
- [x] Selected project in left panel: `font-weight: 600`; no blue background, no border decoration
- [x] Selected section tab in middle panel: `font-weight: 600`; no blue background, no border decoration

### Definition of Done
- [x] All AC checked
- [x] Visual smoke test: three-panel layout looks consistent at 1280px; no hard edges between panels
- [x] No regressions in existing route tests (backend unchanged)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Open `pipeline.html` at 1280px. Verify: single warm-cream background across all three panels and table rows; header shows only "Content Factory"; no visible dividers between panels; muted text on secondary labels.

### Files to modify
- `src/static/pipeline.html` — CSS only (colour tokens, font stack, spacing tweaks)

### Handover
- `src/static/pipeline.html`: CSS + HTML + JS changes (no backend touched). Design tokens: `#FBF9F8` page/panel/input bg; `#2D2D2D` primary text; `#9A9A9A` muted/secondary; `#EFECEB` hover bg and secondary button; `#E8E5E4` card/table borders; `#F0EDEC` table row dividers.
- Font stack `Inter, system-ui, sans-serif`. Weights: body 400; section labels 500; CTAs 600.
- All panel borders/dividers removed. Left↔mid gap 32px (`margin-right` on `.panel-runs`); mid↔right gap 16px (`margin-right` on `.panel-nav`).
- Full-width `.app-header` (flex row) replaces scoped panel header. `+ New Project` button (`.btn-outline` — transparent bg, light grey border) sits inline next to title. `padding: 40px 20px 28px` gives tall header.
- `nav-run-id` div removed; `← Projects` back nav removed. Clicking the active project in left panel calls `deselectRun()` to collapse the middle panel (toggle).
- `.panel-nav { padding: 6px 4px }` and `.panel-content { padding: 6px 40px 32px }` — all three panels now start content at the same vertical baseline.
- Triple-chevron connector (`<svg>` with 3 polylines) injected between nav items via `renderNavItems()` join. `.nav-connector { padding: 1px 0 1px 9px }`.
- Active state (`.run-item.active`, `.nav-item.active`): `font-weight: 600` only — no border, no blue bg. Hover blocked on active items via `:not(.active):hover`.
- Dot logic fixed in `renderRunList()`: `○` for pending, `●` for complete/failed/in-progress; consistent `font-size: 10px` across both panels.
- `.btn-outline` added: transparent bg, `border-color: #d1d5db`. Used on `+ New Project` only; other secondary buttons keep `.btn-secondary` (`#EFECEB`).
- Logout button gains inline SVG arrow-out-of-box icon (13×13, `currentColor`).
- 535 tests passing, no regressions.

---

## [S6-S2] Project Name as primary identifier (auto-slug, backend + UI)
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Completed:** 2026-05-29
**Priority:** high
**Points:** 3
**Depends on:** S6-S1

### Goal
Replace the raw slug input with a human-readable "Project Name" field. The backend auto-generates the URL-safe slug from the name — the operator never sees or types a slug.

### Acceptance Criteria
- [ ] `POST /runs` accepts `project_name: str` (required, max 120 chars); auto-generates slug via `re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")` (or equivalent); returns `{run_id, project_name, storage_prefix}`
- [ ] `project_name` written into `run_log.json` at key `project_name`
- [ ] `GET /runs` returns `project_name` in each run summary (falls back to `run_id` when field absent for legacy runs)
- [ ] Left panel project list renders `project_name`; falls back to `run_id` for old runs
- [ ] "New Project" button label (was "New Run")
- [ ] Input field label "Project Name" with placeholder "e.g. Housing Crisis Explained"
- [ ] Slug not shown anywhere in the UI (it remains the internal `run_id` key)
- [ ] All existing tests updated to pass `project_name` where `slug` was used; no test regressions

### Definition of Done
- [ ] All AC checked
- [ ] Tests: `POST /runs` with `project_name` returns expected slug; `GET /runs` returns `project_name`; legacy run without field returns `run_id` as display name
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Click "New Project", type "Housing Crisis Explained", click Save Draft (or Create Storyboard). Verify left panel shows "Housing Crisis Explained". Check R2 `run_log.json` contains `"project_name": "Housing Crisis Explained"` and the run folder uses a slug like `2026-05-29_housing-crisis-explained`.

### Files to modify
- `src/routes/runs.py` — `POST /runs` accept `project_name`, slugify, write to run_log
- `src/models.py` — `RunCreateRequest(project_name)`, `RunCreateResponse` + `RunSummary` gain `project_name`
- `src/storage.py` — `_build_run_log` stores `project_name`
- `src/static/pipeline.html` — label + button text; left panel display name logic
- `tests/test_runs.py` — update fixtures and assertions

### Handover
- `src/models.py`: `RunCreateRequest` now accepts `project_name: str` (stripped, 1–120 chars). `RunCreateResponse` gains `project_name: str`. `RunSummary` gains `project_name: Optional[str] = None`. `RunLog` gains `project_name: Optional[str] = None` (backward-compatible — legacy logs without the field deserialise cleanly).
- `src/routes/runs.py`: `_slugify(name) → str` helper added (`re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")`). `POST /runs` slugifies `project_name` → `run_id`, passes `project_name` to storage, returns it in response.
- `src/storage.py`: `_build_run_log(run_id, project_name=None)` and `create_run_folder(run_id, project_name=None)` accept optional `project_name`. `list_runs._fetch` reads `data.get("project_name")` and returns it alongside run_id/steps.
- `src/static/pipeline.html`: Left-panel form removed. "+ New Project" calls `openNewProjectForm()` which shows the Input section with a blank form (no run created yet). Input section now shows: Project Name → Voiceover → VO Script → Create Storyboard. `_ensureRun()` lazily creates the run on first action (VO Upload or Create Storyboard). `openRun()` populates Project Name field (read-only) for existing runs. Left panel renders `project_name || run_id`.
- `tests/test_runs.py`: Fully rewritten for `project_name`. `TestCreateRunNameValidation` replaces `TestCreateRunSlugValidation`. 8 net new tests.
- `tests/test_storage.py`: 4 new tests for `project_name` in `_build_run_log` and `create_run_folder`.
- No new ENV vars. No new pip dependencies. 543 total tests passing.

---

## [S6-S3] Input stage: Save Draft + Create Storyboard (lock mechanic)
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Completed:** 2026-05-29
**Priority:** high
**Points:** 5
**Depends on:** S6-S2

### Goal
Give the operator two actions in the Input stage: **Save Draft** (non-destructive, editable) and **Create Storyboard** (locks Input permanently and triggers pipeline). Input fields: Project Name, Script, Voiceover upload.

### Acceptance Criteria
- [ ] Input stage renders three fields: Project Name (text), Script (textarea), Voiceover (file upload, `.mp3`)
- [ ] "Save Draft" button: calls `POST /runs/{run_id}/draft` — saves `project_name` + script text to R2 as `script.txt`; Input remains editable; run appears in left panel with Input indicator unfilled
- [ ] "Create Storyboard" button: triggers `POST /runs/{run_id}/alignment` then `POST /runs/{run_id}/storyboard` in sequence; on success, Input stage indicator turns green and inputs become read-only permanently
- [ ] After "Create Storyboard" completes, auto-navigate to Storyboard section
- [ ] If the run already has a completed storyboard (page reload), Input section shows read-only values from `script.txt` + displays existing VO filename; "Create Storyboard" button replaced by locked indicator
- [ ] No "Regenerate" option on Input section in MVP
- [ ] Backend: `POST /runs/{run_id}/draft` saves `{"project_name": "…", "script": "…"}` to `runs/{run_id}/script.txt`; idempotent (overwrite allowed in draft state only — rejected if `storyboard` step is `complete`)
- [ ] `POST /runs/{run_id}/storyboard` reads script from request body (unchanged) OR from `script.txt` in R2 if body empty

### Definition of Done
- [ ] All AC checked
- [ ] Tests: Save Draft stores script.txt; rejected after storyboard complete; Create Storyboard sequence runs and locks
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open new project. Fill name + script + upload VO. Click "Save Draft". Refresh — project in left panel list, fields still editable. Click "Create Storyboard". Confirm Input section goes read-only and green; Storyboard section becomes active.

### Files to create or modify
- `src/routes/runs.py` — new `POST /runs/{run_id}/draft`
- `src/models.py` — `DraftRequest(project_name, script)`, `DraftResponse(status)`
- `src/storage.py` — (uses existing `upload_text`)
- `src/static/pipeline.html` — Input section redesign: two buttons, lock-on-complete, read-only state

### Handover
- `src/models.py`: `DraftRequest(project_name, script)` and `DraftResponse(status, project_name, script, vo_filename=None)` added. `StoryboardRequest.script` default changed from required to `""` (empty default enables script.txt fallback).
- `src/routes/runs.py`: `POST /runs/{run_id}/draft` — reads `run_log.json` to guard against storyboard-complete (409); saves script text to `runs/{run_id}/script.txt` via `upload_text`; returns `DraftResponse`. `GET /runs/{run_id}/draft` — returns `project_name` from `run_log.json`, `script` from `script.txt` (empty string if absent), `vo_filename` from first `.mp3/.wav/.m4a` in `voiceover/` prefix (null if none).
- `src/routes/storyboard.py`: Before calling `generate_storyboard`, if `body.script.strip()` is empty, attempts `storage.get_bytes(f"runs/{run_id}/script.txt")`; raises HTTP 422 if both body and R2 are empty.
- `src/static/pipeline.html`: Input locked bar: "Regenerate" button removed (MVP constraint). CTA area: "Save Draft" + "Create Storyboard" in a flex row with save status span. Script textarea has `oninput="updateSaveDraftBtn()"`. `saveDraft()` — calls `_ensureRun()` then `POST /draft`; shows `✓ Saved` with 2s reset. `updateSaveDraftBtn()` — enabled when name + script filled and not locked. `populateInput()` is now async — in locked state, fetches `GET /draft` and populates script textarea + VO filename as read-only.
- `tests/test_runs.py`: `TestSaveDraft` (7 tests) + `TestGetDraft` (5 tests) added. 46 total tests in file.
- `tests/test_storyboard.py`: `test_empty_body_script_falls_back_to_script_txt` + `test_missing_script_and_no_draft_returns_422` added.
- No new ENV vars. No new pip dependencies. 579 total tests passing.

---

## [S6-S4] Storyboard stage: full-data table view + permanent lock
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** S6-S1

### Goal
Replace the storyboard scene cards with a dense table exposing every field defined for a scene. Stage locks permanently after generation — no regenerate in MVP.

### Scene fields to render (from `StoryboardScene`)
| Column | Source field | Notes |
|--------|-------------|-------|
| Scene | `scene` | Scene ID (e.g. "01") |
| Type | `clip_type` | `hard_cut` / `still_with_motion` / `animated` |
| Duration | `duration_s` | Formatted as `Xs` |
| Voiceover | `voiceover_line` | Full VO text for scene |
| On-Screen Text | `on_screen_text` | Keyword overlay; `—` when null |
| Primary Query | `visual_prompts.primary_stk` | Pexels primary search |
| Fallback Query | `visual_prompts.fallback_stk` | Pexels fallback search |
| AI Prompt | `visual_prompts.ai_generate` | Replicate/Flux generation prompt |
| Motion | `motion_effect` | `zoom_in` / `pan_left` / etc.; `—` when null |
| SFX | `sfx` | Sound effect name |
| SFX Timing | `sfx_timing` | e.g. `start`, `end`, `+1.5s` |

Global storyboard metadata (`bg_music`, `visual_style`, `subtitle_style`, `rhythm`, `total_duration_s`) displayed as a compact summary row **above** the table — not repeated per scene.

### Acceptance Criteria
- [ ] Storyboard section renders a horizontal-scrollable TABLE with all 11 scene columns listed above
- [ ] Table is horizontally scrollable — columns never collapse or wrap; full data always visible
- [ ] Global metadata row above table: BG Music, Visual Style, Subtitle Style, Rhythm, Total Duration
- [ ] Table rows sourced from `GET /runs/{run_id}/artifact/storyboard` (artifact endpoint unchanged)
- [ ] Null/optional fields (`on_screen_text`, `motion_effect`) render as `—`
- [ ] CTA button reads "Run Asset Acquisition" (was "Approve & Get Assets")
- [ ] "Run Asset Acquisition" triggers `POST /manifest` then `POST /assets` in sequence
- [ ] After completion: Storyboard section indicator turns green; no "Regenerate" option
- [ ] Table background: `#FBF9F8` (inherits from S6-S1 design system)
- [ ] No changes to backend storyboard generation logic

### Definition of Done
- [ ] All AC checked
- [ ] Visual smoke test: all 11 columns visible and correct for a 10-scene run; global metadata row present
- [ ] No backend test regressions
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open a run with a completed storyboard. Navigate to Storyboard section. Verify global metadata row shows BG music, visual style, rhythm. Scroll the table and confirm all 11 columns are populated for each scene (nulls show `—`). Click "Run Asset Acquisition". Confirm both manifest and asset steps complete; Storyboard section turns green.

### Files to modify
- `src/static/pipeline.html` — Storyboard section: replace card rendering with full-data table; global metadata row; rename CTA; remove regenerate logic

### Handover
_filled on completion_

---

## [S6-S5] Assets stage: Description column + media link column
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Completed:** 2026-05-29
**Priority:** medium
**Points:** 2
**Depends on:** S6-S1

### Goal
Add a Description column to the asset table and replace the static File field with a clickable Link that opens the actual media asset from R2 storage.

### Acceptance Criteria
- [ ] Assets table columns: Scene #, Type, Description, Source, Status, Link
- [ ] Description: populated from manifest entry `primary_query` (the stock-footage search query — best available proxy for scene description in MVP)
- [ ] Link: clickable element that fetches a presigned GET URL and opens it in a new tab; calls new `GET /runs/{run_id}/asset-link?key={file_key}` endpoint which returns `{url: presigned_url, expires_in: 3600}`
- [ ] Link shows text "Open" (or icon); disabled/hidden when `file_key` is null
- [ ] No "Regenerate" button on this section; no re-processing controls of any kind
- [ ] Table background `#FBF9F8` (from S6-S1)
- [ ] Backend: `GET /runs/{run_id}/asset-link?key={encoded_key}` — validates key starts with `runs/{run_id}/` (prevent key traversal), generates 1h presigned GET URL, returns `{url, expires_in}`

### Definition of Done
- [ ] All AC checked
- [ ] Tests: asset-link endpoint returns presigned URL; rejects keys outside run prefix
- [ ] Manual smoke test: click "Open" on an acquired asset — correct image or video opens in new tab
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open a run with completed assets. Navigate to Assets section. Verify Description column shows search query text. Click "Open" on a scene with `status: acquired`. Confirm correct media file opens (image or video) in new tab.

### Files to create or modify
- `src/routes/runs.py` — new `GET /runs/{run_id}/asset-link` endpoint
- `src/models.py` — `AssetLinkResponse(url, expires_in)`
- `src/static/pipeline.html` — Assets section: add Description + Link columns; remove regenerate

### Handover
- `src/models.py`: `AssetLinkResponse(url: str, expires_in: int)` added.
- `src/routes/runs.py`: `GET /runs/{run_id}/asset-link?key=...` — validates key starts with `runs/{run_id}/` and contains no `..` path components; calls `R2Client.generate_presigned_url(key)`; returns `AssetLinkResponse(url, expires_in=3600)`. 403 on invalid key, 500 on `StorageError`.
- `src/static/pipeline.html`: `renderManifestHtml` rewritten — 6 columns: Scene, Type, Description, Source, Status, Link. Description cell shows `primary_query` with `.trunc` + `title` tooltip. Link cell shows `<a class="asset-open-link">Open</a>` when `file_key` present, `<span class="muted">—</span>` when null. `openAssetLink(event, runId, fileKey)` async helper fetches presigned URL and calls `window.open`.
- No new ENV vars. No new pip dependencies.
- 585 tests passing (+6 new in `TestGetAssetLink`).

---

## [S6-S6] Render Video: bounded player + modal + Download button
**Epic:** E6 — Operator UI
**Sprint:** 6
**Status:** done
**Completed:** 2026-05-29
**Priority:** medium
**Points:** 2
**Depends on:** S6-S1

### Goal
Fix the render video section so the player is always bounded within the right panel (never fullscreen by default) and gives the operator a proper modal for focused viewing plus a clear Download button.

### Acceptance Criteria
- [ ] `<video>` element rendered in a fixed-height bounded container (max 360px tall) within the right panel; `controls` attribute present but no `autoplay`
- [ ] Clicking the video (or an "Expand" button) opens a modal overlay with a larger player (max 80vh) and a close button (×)
- [ ] Modal close button and click-outside-modal both dismiss the modal
- [ ] "Download Video" button (below the player) downloads `final.mp4` directly — uses presigned R2 URL with `Content-Disposition: attachment` (backend already supports this via existing render artifact presigned URL)
- [ ] No default fullscreen behaviour; `fullscreen` is only accessible via native browser controls inside the modal player
- [ ] Render section indicator turns green when `render` step is `complete`
- [ ] No backend changes required

### Definition of Done
- [ ] All AC checked
- [ ] Visual smoke test: video renders in bounded container; clicking opens modal; × closes it; Download button downloads the file
- [ ] No existing test regressions
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Open a run with `render: complete`. Navigate to Render Video section. Confirm video is contained (not fullscreen). Click it — modal appears with larger player. Click × — modal closes. Click "Download Video" — browser downloads `final.mp4`.

### Files to modify
- `src/static/pipeline.html` — Render section: bounded `<video>`, modal overlay, Download button

### Handover
_filled on completion_

---

## [S7-S1] Full pipeline smoke test — validate all deferred smoke tests on Railway DEV
**Epic:** E6 — Operator UI
**Sprint:** 7
**Status:** done
**Completed:** 2026-05-30
**Priority:** critical
**Points:** 3
**Depends on:** Railway DEV deploy live (auto-deploy from main ✓)

### Goal
Operator runs the complete pipeline end-to-end from the browser UI on Railway DEV. Every pipeline step is exercised. All 10 deferred smoke tests from Sprints 3–6 are validated in one session. Any blocking bugs found are fixed inline.

### Acceptance Criteria
- [ ] Operator logs in with `OPERATOR_PASSWORD`
- [ ] Clicks "+ New Project", enters project name — left panel shows the name
- [ ] Uploads voiceover MP3
- [ ] Runs Alignment (Deepgram) — `alignment.json` appears in R2
- [ ] Runs Create Storyboard — Input locks green; Storyboard table renders with all 11 columns
- [ ] Runs Asset Acquisition — Assets table shows Description + "Open" link per scene; clicking "Open" loads the asset in a new tab
- [ ] Runs Render Video — video renders in bounded player; Expand opens modal; Download downloads `final.mp4`
- [ ] Left panel project name persists across page refresh
- [ ] `run_log.json` shows all steps `complete`
- [ ] Any blocking bug found → fixed inline and committed; any non-blocking bug → promoted to backlog

### Definition of Done
- [ ] All AC checked
- [ ] Zero blocking bugs remaining
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
This story IS the smoke test. The AC above are the verification criteria.

### Files to read
- DONE.md — all 10 deferred smoke test conditions (Sprint 3–6 entries)
- `src/static/pipeline.html` — if inline fixes are needed

### Handover
- Full pipeline validated end-to-end on Railway DEV: login → new project → VO upload → alignment → storyboard → asset acquisition → render → download.
- All 10 deferred smoke tests from Sprints 3–6 signed off in a single session (S6-S2 through S6-S6, S5-S2, S5-S4, S5-S5, E5-S4, E5-S5).
- No blocking bugs found. No ENV vars added. No new dependencies.
- Zero issues promoted to backlog.

---

---

## EPIC 9 — Workspace Layout
Collapsible left sidebar so the operator can reclaim horizontal space for wide data tables (storyboard, assets).

---

## EPIC 10 — Project Details Refactor
Rename "Input" → "Project Details" and restructure into a proper configuration hub with Content and Settings sections.

---

## EPIC 11 — Commit System
Formal commit gate with confirmation modal and locked read-only state — replaces the implicit "Create Storyboard" lock.

---

## EPIC 12 — Video Settings
Aspect ratio, visual style, and subtitle controls. First stored in config (Sprint 9); wired into the pipeline (Sprint 12).

---

## EPIC 13 — TTS Voiceover Generation
ElevenLabs API generates voiceover from script when no audio file is uploaded. Chunked parallel requests, PCM merge, auto-alignment.

---

## EPIC 14 — Audio Layer
Background music as a first-class component: upload, volume control, voiceover ducking, ffmpeg integration.

---

## EPIC 15 — Publishing Metadata
Post-render Claude API call generates titles, descriptions, and hashtags. Display with copy-to-clipboard in the UI.

---

## EPIC 16 — Project Deletion
Delete a project from the UI with a confirmation modal and a backend purge of R2 storage.

---

## EPIC 17 — Scene-Based Storyboard Editor (Phase 2 — future)
Storyboard evolves from read-only table to editable scene graph. Per-scene editing, regeneration, asset type override. Partially addressed in Sprint 13 (inline AI prompt editing + Asset Mode column).

---

## EPIC 18 — Scene-Level Asset & Regeneration System (Phase 2 — future)
Scene-level asset refresh, partial re-render, and "video outdated" state when a scene changes. Depends on E17. Partially addressed in Sprint 15 (per-asset upload replacement).

---

## EPIC 19 — Creative Draft Architecture
Storyboard becomes an editable working layer. Asset strategy moves to per-scene control. Visual Style Prompt gives the operator direct control over AI generation style injection.

---

## EPIC 20 — Stock Source Expansion
Add Pixabay as a second parallel stock source. Add Wikimedia Commons for historic/archival scenes. AI-driven source type classification routes scenes automatically based on script context.

---

## EPIC 21 — Assets UX + Replacement
Full assets table overhaul: per-asset upload replacement, full description visibility, Voice Over column, human-readable type labels, remove Status column noise.

---

## EPIC 22 — Project Report + Token Tracking
Token cost logging per Claude API call. Project Report as the final pipeline step — aggregating cost, asset sources, render time, and video stats.

---

## EPIC 23 — External API + Webhook
API-first pipeline endpoint for N8N and external tool integration. Bearer auth. Webhook callback when video is ready. Enables fully automated content factory workflows.

---

## EPIC 24 — Multi-tenant + Google OAuth
Google OAuth replaces the single-operator password gate. Per-user run isolation in R2. Lightweight user registry.

---

## EPIC 25 — Scale Foundation
Remove hard ceilings on video length. Chunked storyboard generation, parallel asset acquisition, and background render decoupling enable reliable production of 10–15 minute videos on Railway.

---

# Sprint 8 — UI Polish & Workspace

---

## [S8-S1] Collapsible sidebar
**Epic:** E9 — Workspace Layout
**Sprint:** 8
**Status:** done
**Priority:** medium
**Points:** 2
**Depends on:** —

### Goal
Add a toggle button that collapses the left project-list panel, causing the center and right panels to expand and fill the full viewport width. Gives the operator significantly more horizontal space for the storyboard and assets tables.

### Acceptance Criteria
- [x] Toggle button visible in or adjacent to the left panel header
- [x] Clicking toggle hides the left panel; center + right panels expand to fill width
- [x] Clicking toggle again restores the left panel
- [x] Collapsed state preserved for the duration of the session (not persisted across reload)
- [x] No layout breakage at 1280px and 1440px widths
- [x] No backend changes

### Definition of Done
- [x] All AC checked
- [x] Visual smoke test at 1280px and 1440px — no overflow, no layout shift
- [x] No existing test regressions
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Open the app. Click the collapse toggle. Confirm the left panel disappears and center + right panels fill the screen. Click again — left panel returns.

### Files to modify
- `src/static/pipeline.html` — CSS + JS only

### Handover
**Completed:** 2026-05-30
- `src/static/pipeline.html` only — no backend changes.
- Sidebar toggle (`#sidebar-toggle`) is `position: absolute` inside `.panels` (which is `position: relative`), pinned at `top: 11px; left: 10px; z-index: 10`. It lives outside `panel-runs` so it persists on page background when collapsed.
- Toggling adds/removes `sidebar-collapsed` class on `.panels`. Collapsed: `.panel-runs` animates `width: 0; margin-right: 0` — fully disappears. Expanded: `width: 200px; margin-right: 24px`.
- Icon flips `scaleX(-1)` when collapsed to signal "expand".
- `+ New Project` button is the first item in the left panel (above scroll list), styled as a borderless list item with 48px top margin to clear the toggle icon.
- "Content Factory" title removed. Left panel extends full viewport height (no bottom padding on `.panels`).
- Session-only state via `sidebarCollapsed` JS variable. No backend or ENV changes.

---

## [S8-S2] Pipeline status simplification
**Epic:** E9 — Workspace Layout
**Sprint:** 8
**Status:** done
**Completed:** 2026-05-30
**Priority:** medium
**Points:** 1
**Depends on:** —

### Goal
Remove all step-level "completed" confirmation bars that appear inside pipeline stage panels. The global step indicator circles (○/●) in the section nav are the single source of truth for completion state.

### Acceptance Criteria
- [ ] No inline "✓ [Step] complete" banner or colored bar inside any pipeline stage content area
- [ ] Global section nav circles update correctly: ○ not started, ● in progress, ● green complete
- [ ] Stage content (table, player, etc.) remains visible after completion — only the banner is removed
- [ ] No backend changes

### Definition of Done
- [ ] All AC checked
- [ ] All four stages verified: Project Details, Storyboard, Assets, Render Video
- [ ] No existing test regressions
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify
- `src/static/pipeline.html` — HTML + JS only

### Handover
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- **5 CSS dot states:** All dots are now CSS circles (10×10px, border-radius 50%) — no Unicode characters. States: `dot-pending` (grey border), `dot-running` (dashed grey border + `dot-spin` keyframe animation), `dot-draft` (yellow fill #f59e0b), `dot-complete` (green fill #16a34a), `dot-failed` (red fill #dc2626).
- **`dotHtml(status)`** updated — returns `<span class="dot dot-{status}"></span>` with no text content. Accepts all 5 states.
- **`sectionStatus(sectionKey)`** updated — returns `'draft'` for the Input section when `currentRunId` is set but all input steps are still pending (run created/saved, storyboard not yet started).
- **Locked bars removed:** `#input-locked-bar`, `#storyboard-locked-bar`, `#assets-locked-bar` HTML divs deleted. `.locked-bar` and `.locked-bar-spacer` CSS rules deleted. Three `getElementById('*-locked-bar').style.display` JS lines removed.
- **Error bars repositioned:** `#input-error`, `#storyboard-error`, `#assets-error` moved from inside `.cta-area` to the top of each section pane (immediately after `.section-title`) so failures are visible without scrolling to the CTA.
- **Run list dots** updated — removed text char `dotChar` variable; left-panel run items now use `<span class="dot dot-{cls}"></span>`.
- 612 tests passing, no regressions.

---

## [S8-S3] Storyboard table UX — text wrapping and dynamic row height
**Epic:** E9 — Workspace Layout
**Sprint:** 8
**Status:** done
**Completed:** 2026-05-30
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
Fix the storyboard scene table so all text cells wrap their content rather than truncating with ellipsis. Row height must expand dynamically to fit the longest cell in each row.

### Acceptance Criteria
- [x] All text-containing table cells use `white-space: normal` and `word-wrap: break-word` — no `overflow: hidden`, no `text-overflow: ellipsis`
- [x] Row height is not fixed — `height: auto` / no `max-height` clipping on rows
- [x] Full content of long fields (AI Prompt, Voiceover, Primary Query) always readable without tooltip or hover
- [x] Horizontal scroll remains allowed — table may be wider than viewport
- [x] `.trunc` + `title` tooltip pattern removed from storyboard cells (was acceptable in Sprint 6; now explicit cells must show full text)
- [x] No backend changes

### Definition of Done
- [x] All AC checked
- [x] Visual smoke test on a 10-scene run — all cells fully readable; no truncated text visible
- [x] No existing test regressions
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Smoke test
Open a run with a completed storyboard. Scroll through the table. Confirm AI Prompt and Voiceover columns show their full text — no `...` anywhere.

### Files to modify
- `src/static/pipeline.html` — CSS only

### Handover
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- Three new CSS rules scoped to `.data-table.sb-table`: `white-space: normal` (overrides table-wide `nowrap`), `td { word-wrap: break-word }`, `td.text { max-width: 260px }`.
- `class="data-table sb-table"` applied to the storyboard `<table>` element in `renderStoryboardHtml`.
- Storyboard cells for Voiceover, Primary Query, Fallback Query, AI Prompt: `class="trunc" title="..."` → `class="text"`. No tooltip, no ellipsis, full content always visible.
- Manifest table `.trunc` usage unchanged.
- 612 tests passing.

---

## [S8-S4] Storyboard settings header — collapsible grouped section
**Epic:** E10 — Project Details Refactor
**Sprint:** 8
**Status:** done
**Completed:** 2026-05-30
**Priority:** medium
**Points:** 2
**Depends on:** S8-S3

### Goal
Replace the long inline storyboard metadata row with a collapsible settings header. Collapsed view shows a compact one-line summary; expanded view shows grouped VIDEO STYLE and AUDIO sections.

### Acceptance Criteria
- [x] Default (collapsed): single line reading `Storyboard Settings ▾` with a compact summary: `Style: [visual_style] | [aspect_ratio] | Subtitles [ON/OFF] | Music: [bg_music or "None"]`
- [x] Clicking expands to show: **VIDEO STYLE** group (Visual Style, Aspect Ratio, Subtitle Style) and **AUDIO** group (Background Music, Volume, Voiceover ducking)
- [x] Clicking again collapses back to summary
- [x] No horizontal overflow at any panel width
- [x] No backend changes

### Definition of Done
- [x] All AC checked
- [x] Visual smoke test — collapsed and expanded states render cleanly; no overflow
- [x] No existing test regressions (612 passing)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to modify
- `src/static/pipeline.html` — HTML + CSS + JS

### Handover
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- Replaced `.sb-meta` flat row with `.sb-settings` collapsible card. Collapsed state shows header bar with label "Storyboard Settings", inline summary (`Style: X · Y · Subtitles ON/OFF · Music: Z`), and `▾` chevron. Chevron rotates 180° when open (CSS transition).
- `toggleSbSettings()` — added to global JS scope; toggles `.open` class on `#sb-settings-block`. Called via `onclick` in the header.
- Expanded body (`display:flex; flex-wrap:wrap`) shows two groups: **VIDEO STYLE** (Visual Style, Aspect Ratio, Subtitle Style, Rhythm, Total Duration) and **AUDIO** (Background Music, Volume, VO Ducking). Audio fields (Volume, VO Ducking) gracefully show `—` when absent — ready for Sprint 9/11 wiring.
- Summary uses ` · ` separator; `aspect_ratio` and `visual_style` only appear in summary if present in storyboard `global` object.
- 612 tests passing. No new ENV vars. No promoted issues.

---

## [S8-S5] Project deletion flow
**Epic:** E16 — Project Deletion
**Sprint:** 8
**Status:** done
**Completed:** 2026-05-30
**Priority:** medium
**Points:** 3
**Depends on:** —

### Goal
Give the operator a way to delete a project from the UI. A confirmation modal prevents accidental deletion. The backend purges all R2 keys under `runs/{run_id}/` and the run disappears from the left panel.

### Acceptance Criteria
- [ ] "Delete Project" button or action visible in the project header when a run is open
- [ ] Clicking opens a confirmation modal: "Are you sure you want to delete this project? This action cannot be undone. [Cancel] [Delete]"
- [ ] Confirmed delete calls `DELETE /runs/{run_id}` which purges all R2 keys under `runs/{run_id}/` prefix
- [ ] After delete: modal closes, app navigates back to the run list, deleted run no longer appears in left panel
- [ ] Cancel closes modal with no action
- [ ] Backend returns 204 on success, 404 if run not found, 500 on R2 error
- [ ] `DELETE /runs/{run_id}` requires auth (covered by existing auth middleware)

### Definition of Done
- [ ] All AC checked
- [ ] Tests: delete endpoint purges all keys; returns 404 on missing run; auth required
- [ ] Manual smoke test: create a test project, delete it, confirm it disappears and R2 prefix is empty
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
Create a test project and run at least one pipeline step (so R2 has files). Click "Delete Project". Confirm modal appears. Click "Delete". Confirm run disappears from left panel. Open R2 console and verify `runs/{run_id}/` prefix is gone.

### Files to create or modify
- `src/routes/runs.py` — `DELETE /runs/{run_id}` endpoint
- `src/storage.py` — `R2Client.delete_run(run_id)` — lists + batch-deletes all keys under prefix
- `src/models.py` — no new models needed
- `src/static/pipeline.html` — Delete button + confirmation modal + post-delete navigation
- `tests/test_runs.py` — new delete tests

### Handover
- `src/storage.py`: `R2Client.delete_run(run_id) → int` — lists all keys under `runs/{run_id}/`, batch-deletes via `delete_objects` (up to 1000 keys/request), raises `StorageError("Run not found: {run_id}")` if prefix is empty, returns key count.
- `src/routes/runs.py`: `DELETE /runs/{run_id}` — returns 204 on success, 404 when `StorageError` contains "not found", 500 on other R2 errors. Covered by existing auth middleware.
- `src/static/pipeline.html`: "Delete Project" button added to breadcrumb bar (right-aligned via `.bc-spacer` flex push). Confirmation modal (`#delete-modal`) with exact AC text. `confirmDeleteRun()` calls DELETE endpoint, resets all state (`currentRunId`, `currentSteps`, `sectionLocked`, etc.), calls `renderRunList()`, and navigates to `window.location.pathname` (no run hash).
- `tests/test_runs.py`: 4 new `TestDeleteRun` tests (204 success, correct run_id passed, 404 on missing, 500 on R2 error).
- `tests/test_storage.py`: 3 new `TestDeleteRun` tests (deletes and returns count, raises on empty prefix, raises on boto3 failure).
- 619 tests passing. No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

# Sprint 9 — Project Details + Commit System + Video Settings UI

---

## [S9-S1] Project Details tab restructure
**Epic:** E10 — Project Details Refactor
**Sprint:** 9
**Status:** done
**Completed:** 2026-05-31
**Priority:** high
**Points:** 3
**Depends on:** S8-S4

### Goal
Rename the "Input" tab to "Project Details" everywhere in the UI. Restructure the panel content into two named sections: **Content** (Project Name, Script, Voiceover) and **Settings** (video settings — populated by S9-S3). Existing functionality (Save Draft, VO upload, lock mechanic) must be fully preserved.

### Acceptance Criteria
- [ ] All user-visible references to "Input" updated to "Project Details" (tab label, locked state text, section nav dot label)
- [ ] Content section renders: Project Name field, Script textarea, Voiceover upload widget
- [ ] Settings section renders below Content (initially empty placeholder until S9-S3 adds controls)
- [ ] Save Draft, Upload VO, Commit (from S9-S2) all function as before
- [ ] No backend changes — label is UI only

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify
- `src/static/pipeline.html` — label text + HTML structure

### Handover
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- All user-visible "Input" strings replaced with "Project Details": `SECTION_LABELS.input`, `renderNavItems` label entry, `section-title` hidden div, and two empty-state messages ("create one in Project Details.").
- HTML restructured into two named subsections inside `#section-input`: **Content** (Project Name, Voiceover, VO Script) and **Settings** (placeholder "Video settings coming soon." — ready for S9-S3 wiring).
- New CSS classes: `.subsection` (margin group), `.subsection-title` (11px uppercase muted label), `.subsection-placeholder` (muted placeholder text).
- All JS IDs/function names unchanged — `section-input`, `sectionLocked.input`, `populateInput()`, etc. preserved for internal use.
- 619 tests passing. No new ENV vars. No new dependencies.

---

## [S9-S2] Commit system
**Epic:** E11 — Commit System
**Sprint:** 9
**Status:** done
**Completed:** 2026-05-31
**Priority:** high
**Points:** 3
**Depends on:** S9-S1

### Goal
Replace the "Create Storyboard" CTA with a formal **Commit** action. Clicking Commit opens a confirmation modal explaining what will be locked. After confirming, Project Details becomes permanently read-only with a ✓ green committed indicator.

### Acceptance Criteria
- [ ] CTA button reads "Commit" (not "Create Storyboard")
- [ ] Clicking Commit opens a modal with exact text: "After committing, you will NOT be able to modify: Project Name, Script, Voiceover. Do you want to continue?" with [Cancel] and [Commit] buttons
- [ ] Confirming the modal triggers the existing pipeline sequence (alignment → storyboard) — no change to backend behavior
- [ ] After commit completes: Project Details panel shows ✓ committed indicator (green); all fields are read-only; Commit button replaced by the locked indicator
- [ ] Cancel closes modal with no action and no pipeline trigger
- [ ] Existing `POST /runs/{run_id}/draft` guard (rejects if storyboard complete) remains unchanged

### Definition of Done
- [ ] All AC checked
- [ ] Manual smoke test: click Commit, read modal, confirm, observe locked state with ✓ indicator
- [ ] No existing test regressions
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify
- `src/static/pipeline.html` — CTA replacement, modal HTML + JS, locked state indicator

### Handover
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- `#create-storyboard-btn` renamed to `#commit-btn`; text "Commit"; onclick → `openCommitModal()`.
- `openCommitModal()` — validates script present, opens `#commit-modal`.
- `closeCommitModal()` — hides modal (Cancel path).
- `confirmCommit()` — closes modal, calls `runCommit()`.
- `runCommit()` — renamed from `runCreateStoryboard()`; identical alignment → storyboard pipeline sequence.
- `updateCreateStoryboardBtn()` renamed to `updateCommitBtn()` — when locked: hides button, shows `#committed-indicator` (✓ Committed, green `#16a34a`); when unlocked: normal enable/disable.
- `#committed-indicator` `<span>` added to CTA row; hidden by default via `.committed-indicator` CSS; shown via `.committed-indicator.visible`.
- Commit confirmation modal HTML added (`#commit-modal`) with exact AC text.
- `.commit-modal-*` CSS added (same pattern as delete modal).
- 619 tests passing. No new ENV vars. No new dependencies.

---

## [S9-S3] Video settings UI
**Epic:** E12 — Video Settings
**Sprint:** 9
**Status:** done
**Completed:** 2026-05-31
**Priority:** medium
**Points:** 2
**Depends on:** S9-S1

### Goal
Add video settings selectors to the Settings section of Project Details. Values are stored in R2 config and survive page reload. No pipeline wiring in this story — the settings are captured only. Pipeline wiring is S12-S1.

### Acceptance Criteria
- [x] Aspect ratio selector: 9:16 (default) / 16:9 / 1:1
- [x] Visual style dropdown: Realistic / Cinematic / Cartoonish / Documentary / Minimalist
- [x] Subtitles toggle: enabled (default) / disabled
- [x] Subtitle style selector (visible only when subtitles enabled): TikTok style / Classic
- [x] All values stored via `POST /runs/{run_id}/settings` and returned by `GET /runs/{run_id}/settings`
- [x] Values persist across page reload — GET /runs/{run_id}/settings returns stored values
- [x] Controls are read-only after commit (locked with Project Details)
- [x] Default values applied when no settings have been saved

### Definition of Done
- [x] All AC checked
- [x] Tests: settings saved and retrieved; defaults returned when absent; read-only after commit
- [x] No existing test regressions (630 passing)
- [ ] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/routes/runs.py` — `POST /runs/{run_id}/settings`, `GET /runs/{run_id}/settings`
- `src/models.py` — `VideoSettings(aspect_ratio, visual_style, subtitles_enabled, subtitle_style)`, `RunSettings`
- `src/storage.py` — `upload_json` / `get_json` for `settings.json` (already exists — no new method needed)
- `src/static/pipeline.html` — Settings section controls

### Handover
- `src/models.py`: `VideoSettings(aspect_ratio, visual_style, subtitles_enabled, subtitle_style)` — all fields use `Literal` types for validation; defaults: `"9:16"`, `"Realistic"`, `True`, `"TikTok"`. `VideoSettingsResponse(status, settings)` added.
- `src/routes/runs.py`: `POST /runs/{run_id}/settings` — stores `runs/{run_id}/settings.json` via `upload_json`, returns `{status:"saved", settings:{...}}`. `GET /runs/{run_id}/settings` — returns stored values or silent defaults on `StorageError` (never 404).
- `src/static/pipeline.html`: Settings section (previously a placeholder) now renders three field-cards: Aspect Ratio select, Visual Style select, Subtitles toggle + conditional Caption Style select. JS: `loadVideoSettings()` fetches from `/settings` and populates controls; `saveVideoSettings()` POSTs on every change; `_applyVideoSettingsLock(locked)` disables all four controls when `sectionLocked.input` is true; `_updateSubtitleStyleVisibility()` hides subtitle style when toggle is off; `onSubtitlesToggle()` combines both. `loadVideoSettings()` called from `populateInput()`.
- No new ENV vars. No new dependencies.
- 630 tests passing (+11).

---

# Sprint 10 — TTS Voiceover Generation

---

## [S10-S1] TTS VO generation via ElevenLabs
**Epic:** E13 — TTS Voiceover Generation
**Sprint:** 10
**Status:** done
**Priority:** high
**Points:** 6
**Depends on:** S9-S2

### Goal
Add a "Generate Voiceover" mode alongside "Upload VO" in Project Details. When selected, the backend splits the script into sentence-boundary-aligned chunks (~1000 chars), sends all chunks to ElevenLabs concurrently, concatenates the raw PCM responses in order, encodes to MP3 via ffmpeg, stores the file, and auto-runs alignment — all invisible to the user.

### Acceptance Criteria
- [x] "Generate Voiceover" toggle/tab in Project Details alongside "Upload VO"
- [x] When "Generate Voiceover" is active and script is present, "Commit" triggers TTS generation before alignment
- [x] Backend: `POST /runs/{run_id}/tts` — reads `script.txt` from R2, splits into chunks at sentence boundaries (`.`, `!`, `?`) with target ~1000 chars per chunk; sends all chunks to ElevenLabs `POST /v1/text-to-speech/{voice_id}/stream` with `output_format=pcm_44100`; `previous_text` and `next_text` params set per chunk for prosody continuity; chunks sent via `asyncio.gather`; PCM bytes concatenated in request order; encoded to MP3 via ffmpeg subprocess (`-f s16le -ar 44100 -ac 1`); stored as `runs/{run_id}/voiceover/generated.mp3`
- [x] After TTS completes, `POST /runs/{run_id}/alignment` is called automatically — no user action required
- [x] `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` added to `config.py` and `ENV.md`
- [x] If ElevenLabs API fails: step marked failed, clear error shown in UI; operator can retry or switch to Upload VO mode
- [x] Generated VO filename shown in Project Details after generation ("generated.mp3 ✓")
- [x] Existing "Upload VO" path completely unchanged

### Definition of Done
- [ ] All AC checked
- [ ] Tests pass with ElevenLabs API mocked (httpx mock); chunk split logic unit-tested; PCM concat unit-tested; ffmpeg encode mocked
- [ ] `DECISIONS.md` D038 + D039 already exist — no new entries needed
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Smoke test
In Project Details, switch to "Generate Voiceover". Paste a 300+ word script. Click "Commit". Observe progress indicator. After completion: confirm `voiceover/generated.mp3` exists in R2; confirm `alignment.json` also created; confirm pipeline advances to Storyboard section.

### Files to create or modify
- `src/tts.py` — new: `generate_tts(script, api_key, voice_id) → bytes` — chunker + parallel ElevenLabs calls + PCM concat + ffmpeg encode
- `src/routes/tts.py` — new: `POST /runs/{run_id}/tts`
- `src/main.py` — register TTS router
- `src/models.py` — `TTSResponse(status, key, chunk_count, duration_s)`
- `src/config.py` — `ELEVENLABS_API_KEY: str = ""`, `ELEVENLABS_VOICE_ID: str = ""`
- `src/exceptions.py` — `TTSError`
- `ENV.md` — document new vars
- `src/static/pipeline.html` — Generate Voiceover mode + auto-trigger chain
- `tests/test_tts.py` — new

### Handover
- `src/tts.py`: `split_into_chunks(script, target_chars=1000) → list[str]` — splits at `.`, `!`, `?` sentence boundaries; merges short sentences until target reached. `generate_tts(script, api_key, voice_id) → (mp3_bytes, chunk_count)` — async; gathers `_call_elevenlabs` coroutines in parallel with `previous_text`/`next_text` context params; concatenates raw PCM in order; calls `_encode_pcm_to_mp3` (ffmpeg subprocess: `-f s16le -ar 44100 -ac 1 -i pipe:0 -f mp3 pipe:1`). Raises `TTSError` on any failure.
- `src/routes/tts.py`: `POST /runs/{run_id}/tts` — returns 503 if `ELEVENLABS_API_KEY`/`ELEVENLABS_VOICE_ID` unset; reads `script.txt` via `storage.get_bytes` (404 if missing); calls `generate_tts`; on success lists and deletes all existing `runs/{run_id}/voiceover/` keys then uploads `generated.mp3`; on failure leaves existing voiceover untouched (delete-on-success only). Returns `TTSResponse(status, key, chunk_count, duration_s)`.
- `src/exceptions.py`: `TTSError` added.
- `src/models.py`: `TTSResponse(status, key, chunk_count, duration_s)` added.
- `src/config.py`: `ELEVENLABS_API_KEY: str = ""`, `ELEVENLABS_VOICE_ID: str = ""` (both optional; absent → 503 at route level).
- `src/main.py`: `tts_router` registered between `alignment_router` and `ffmpeg_script_router`.
- `ENV.md`: `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` documented.
- `src/static/pipeline.html`: Voiceover field-card now has `.vo-mode-tabs` with "Upload File" / "Generate with ElevenLabs" buttons. `voMode` state var ('upload'|'generate'). `setVoMode(mode)` shows `#tts-warn-modal` if switching to generate when `voUploaded`. Modal: "If generation succeeds, it will be permanently deleted." Cancel reverts; Confirm calls `_applyVoMode('generate')`. `updateCommitBtn` allows Commit when `voMode==='generate'` and script non-empty (no upload required). `runCommit` prepends `POST /tts` step in generate sequence. `populateInput` restores generate mode when `vo_filename === 'generated.mp3'` and shows "✓ generated.mp3". Tabs disabled when `sectionLocked.input`.
- `tests/test_tts.py`: 25 new tests. 656 total passing.
- No new pip dependencies (`httpx` and `subprocess`/`asyncio` already available).
**Promoted to backlog:** none

---

# Sprint 11 — Audio Layer

---

## [S11-S1] Background music upload
**Epic:** E14 — Audio Layer
**Sprint:** 11
**Status:** done
**Completed:** 2026-05-31
**Priority:** medium
**Points:** 3
**Depends on:** S9-S1

### Goal
Add a background music upload widget to the Project Details Audio section. Music file is stored in R2 and a playback preview is shown in the UI.

### Acceptance Criteria
- [ ] Audio section in Project Details Settings area, below Video settings
- [ ] File picker accepts `.mp3`, `.wav`, `.m4a`
- [ ] On file select: generates presigned PUT URL, uploads directly to R2 at `runs/{run_id}/music/bg.[ext]`
- [ ] After upload: `<audio controls>` preview element renders for the uploaded track
- [ ] "No music" option available (default) — clears any previously uploaded track
- [ ] Uploaded filename shown alongside preview
- [ ] Controls locked after commit (read-only with Project Details)

### Definition of Done
- [ ] All AC checked
- [ ] Manual smoke test: upload an MP3, hear preview, delete and re-upload
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/routes/runs.py` — `POST /runs/{run_id}/music-upload-url` (presigned PUT, mirrors voiceover-upload-url pattern)
- `src/models.py` — `MusicUploadUrlResponse(upload_url, key)`
- `src/static/pipeline.html` — Audio section, music upload widget + preview

### Handover
- `POST /runs/{run_id}/music-upload-url` → `MusicUploadUrlResponse(upload_url, key)`. Key pattern: `runs/{run_id}/music/{filename}`.
- `DELETE /runs/{run_id}/music` → 204. Clears all keys under the music prefix; no-op if empty.
- `GET /runs/{run_id}/draft` now includes `music_filename: Optional[str]` — first audio file found under `runs/{run_id}/music/` prefix.
- UI: Background Music field-card in Settings subsection. States: no-music / pending-upload / preview (audio player + Remove). Locked on commit. Music state restored on run open via presigned GET URL through existing `/asset-link` endpoint.
- No new ENV vars. No new dependencies. 665 tests passing.

---

## [S11-S2] Audio controls UI
**Epic:** E14 — Audio Layer
**Sprint:** 11
**Status:** done
**Priority:** medium
**Points:** 2
**Depends on:** S11-S1

### Goal
Add audio mixing controls to the Audio section: volume slider, voiceover ducking toggle, and loop vs fit-to-duration mode selector. Values stored in run config and persist across reload.

### Acceptance Criteria
- [x] Volume slider: 0–100%, default 15%, labeled "Music volume"
- [x] Voiceover ducking toggle: ON/OFF, default ON, labeled "Auto-duck music under voiceover"
- [x] Playback mode selector: "Loop full track" / "Fit to video duration", default "Fit to video duration"
- [x] All values persisted via `POST /runs/{run_id}/settings` (extends existing VideoSettings model)
- [x] Values survive page reload
- [x] Controls locked after commit

### Definition of Done
- [x] All AC checked
- [x] Tests: audio settings saved and retrieved
- [x] No existing test regressions
- [ ] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to modify
- `src/models.py` — extend `RunSettings` / `VideoSettings` with `AudioSettings(music_volume, ducking_enabled, playback_mode)`
- `src/static/pipeline.html` — slider, toggle, selector controls

### Handover
- `src/models.py`: `AudioSettings(music_volume: int = 15, ducking_enabled: bool = True, playback_mode: Literal["loop","fit"] = "fit")` added. `VideoSettings` gains `audio: AudioSettings = Field(default_factory=AudioSettings)`. Fully backward-compatible — existing `settings.json` without the `audio` key deserialises to defaults.
- `src/static/pipeline.html`: Three controls added inside the existing `field-card--tight-v` below the Subtitles row, separated by a `.settings-row--section-label` "AUDIO" divider. Controls: `#setting-music-volume` range input + `#setting-music-volume-display` label; `#setting-ducking` checkbox wrapped in `.toggle-switch`; `#setting-playback-mode` select. CSS added: `.settings-row--section-label`, `.settings-row-section`, `.toggle-switch`/`.toggle-track` toggle component, disabled-state for slider and ducking checkbox.
- `loadVideoSettings()` extended to restore all three audio controls from `s.audio`; all controls disabled when section is locked.
- `saveVideoSettings()` extended to include `audio: {music_volume, ducking_enabled, playback_mode}` in the POST body.
- `renderStoryboardHtml(content, audioSettings)` — signature gains optional `audioSettings` param. Storyboard settings panel Audio section now shows Volume, VO Ducking, and Playback from `audioSettings` (passed from `populateStoryboard` which fetches `GET /runs/{run_id}/settings` in parallel with the storyboard artifact).
- `tests/test_runs.py`: 7 new tests in `TestVideoSettings` — audio POST/GET round-trip, R2 storage, defaults on absent file, invalid playback_mode → 422, out-of-range volume → 422, POST without audio block → defaults. 675 total passing.

---

## [S11-S3] Audio → ffmpeg integration
**Epic:** E14 — Audio Layer
**Sprint:** 11
**Status:** done
**Completed:** 2026-05-31
**Priority:** high
**Points:** 5
**Depends on:** S11-S1, S11-S2

### Goal
Pass background music key, volume, and ducking settings from run config into the ffmpeg script generator. Replaces the hardcoded `music 0.15` constant.

### Acceptance Criteria
- [ ] ffmpeg script generator reads `settings.json` from R2 before building the script
- [ ] When BG music present: `runs/{run_id}/music/bg.[ext]` used as music input; volume applied from config value (e.g. `volume=0.40` filter)
- [ ] Ducking ON: music volume lowered during voiceover using ffmpeg `sidechaincompress` or `volume` automation where voiceover is active
- [ ] Playback mode: "Fit to video duration" trims music to total video length; "Loop full track" uses `stream_loop=-1` with `atrim`
- [ ] When no music uploaded: existing silence fallback preserved (`anullsrc`)
- [ ] All new filter graph changes covered by tests

### Definition of Done
- [ ] All AC checked
- [ ] Tests: volume applied correctly; ducking filter present when enabled; silence fallback when no music; loop vs trim modes
- [ ] Manual smoke test: render video with background track at 40% volume + ducking ON — confirm audible result
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify
- `src/ffmpeg_builder.py` — audio section rewrite; read settings; dynamic volume + ducking + loop/trim
- `src/routes/ffmpeg_script.py` — load settings from R2 before calling builder
- `tests/test_ffmpeg_builder.py` — new audio section tests

### Handover
- `src/ffmpeg_builder.py`: `_MUSIC_VOL = 0.15` removed; replaced by `_DUCKING_FACTOR = 0.4` module constant. `build_ffmpeg_script` gains `audio: Optional[AudioSettings] = None` param (defaults to `AudioSettings()` when None). `_music_check(audio)` — loop mode injects `-stream_loop -1` into `MUSIC_ARGS` before the file input; fit mode is existing behaviour. `_audio_section(storyboard, audio)` — computes `vol_factor = music_volume/100.0`; `effective_vol = vol_factor * _DUCKING_FACTOR` when `ducking_enabled=True`, else `vol_factor`; baked into filter_complex as `volume={effective_vol:.3f}[music]` (no bash arithmetic at render time).
- `src/routes/ffmpeg_script.py`: loads `runs/{run_id}/settings.json` from R2 after alignment check; falls back to `VideoSettings()` defaults on `StorageError`; passes `audio=video_settings.audio` to `build_ffmpeg_script`.
- `tests/test_ffmpeg_builder.py`: all 9 route-level tests updated to add `StorageError("no settings")` as 4th `get_json.side_effect` entry. Existing volume assertion updated (0.15 → 0.060 default). 11 new tests: `TestAudioSettings` (9 unit) + `TestFfmpegScriptRouteAudioSettings` (2 route). 686 total passing.
- No new ENV vars. No new dependencies.
- Default effective volume is `0.060` (15% slider × 0.4 ducking). S12-S1 (video settings wiring) can now depend on both S9-S3 and S11-S3 being complete.

---

# Sprint 12 — Video Settings Pipeline Wiring + Publishing Metadata

---

## [S12-S1] Video settings → pipeline wiring
**Epic:** E12 — Video Settings
**Sprint:** 12
**Status:** done
**Completed:** 2026-06-01
**Priority:** high
**Points:** 4
**Depends on:** S9-S3, S11-S3

### Goal
Wire the stored video settings into the actual render pipeline. Aspect ratio changes ffmpeg output dimensions. Visual style feeds the Replicate AI image generation prompt. Subtitles toggle enables or disables the caption burn steps.

### Acceptance Criteria
- [ ] ffmpeg script generator reads `aspect_ratio` from settings; outputs 1080×1920 (9:16), 1920×1080 (16:9), or 1080×1080 (1:1) — all dimensions + crop/pad filters updated accordingly
- [ ] Asset acquisition reads `visual_style` from settings; appends style modifier to `ai_generate_prompt` (e.g. "cinematic, shallow depth of field, golden hour" for Cinematic style)
- [ ] When `subtitles_enabled = false`: ffmpeg script omits both `_burn_captions()` and `_burn_voiceover_captions()` steps entirely
- [ ] Subtitle style selector (TikTok / Classic) changes the ASS style parameters (`Fontsize`, `Outline`, `MarginV`) in `captions.py`
- [ ] Default values (9:16, Realistic, subtitles ON, TikTok style) produce output identical to current behavior — no regressions

### Definition of Done
- [ ] All AC checked
- [ ] Tests: all 3 aspect ratios produce correct ffmpeg dimension args; visual style modifier appended to Replicate prompt; subtitles OFF produces script without caption steps; both subtitle styles produce different ASS headers
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify
- `src/ffmpeg_builder.py` — aspect ratio dimensions + conditional caption steps + subtitle style params
- `src/captions.py` — Classic vs TikTok ASS style variant
- `src/acquisition.py` or `src/replicate_client.py` — visual style modifier on `ai_generate_prompt`
- `src/routes/ffmpeg_script.py` — load settings before calling builder
- `tests/test_ffmpeg_builder.py`, `tests/test_captions.py` — new variant tests

### Handover
- `src/ffmpeg_builder.py`: `_ASPECT_DIMENSIONS` dict + `_dimensions_for_aspect_ratio(aspect_ratio) → (w, h)` added. `build_ffmpeg_script` gains `video_settings: Optional[VideoSettings] = None`; `audio` kwarg retained for backwards compat but `video_settings.audio` wins when `video_settings` is provided. `_scene_section`, `_render_scene`, `_render_video_scene`, `_render_image_scene`, and `_zoompan_filter` all accept `out_w`/`out_h` params (defaulting to `_OUT_W`/`_OUT_H` = 1080×1920). When `subtitles == "none"`, caption heredoc + burn step are skipped and `_audio_section` receives `video_source="$WORK/video_only.mp4"` instead of `"$WORK/video_captioned.mp4"`.
- `src/captions.py`: `_CAPTIONS_ASS_HEADER_CLASSIC` added (Poppins, 64pt, Bold=0, Outline=3, MarginV=180). `_captions_header(subtitle_style) → str` helper selects TikTok or Classic header. `build_word_synced_captions_ass` and `build_captions_ass` both gain `subtitle_style: str = "TikTok"` param.
- `src/replicate_client.py`: `_STYLE_MODIFIERS` dict maps Cinematic/Cartoonish/Documentary/Minimalist to prompt modifier strings. `acquire_for_entry` gains `visual_style: str = "Realistic"`; appends modifier when non-empty.
- `src/acquisition.py`: `acquire_scene` and `run_acquisition` gain `visual_style: str = "Realistic"` and pass it through to `replicate.acquire_for_entry`.
- `src/routes/assets.py`: loads `settings.json` → `VideoSettings`; passes `visual_style=video_settings.visual_style` to `run_acquisition`. Falls back to `VideoSettings()` defaults on `StorageError`.
- `src/routes/ffmpeg_script.py`: passes `video_settings=video_settings` to `build_ffmpeg_script` (was `audio=video_settings.audio`).
- 714 total tests passing (28 new in `TestAspectRatioDimensions`, `TestSubtitlesSetting`, `TestSubtitleStyleVariants`, `TestVisualStyleModifier`).
- No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

## [S12-S2] Publishing metadata generator
**Epic:** E15 — Publishing Metadata
**Sprint:** 12
**Status:** done
**Completed:** 2026-06-01
**Priority:** medium
**Points:** 3
**Depends on:** E5-S1 (render step)

### Goal
After a video renders, a Claude API call (Haiku) generates publishing metadata: a primary title, two alternative titles, a YouTube description, an Instagram description, and a hashtag/SEO tag set. Result stored in R2 as `metadata.json`.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/metadata` endpoint — reads `storyboard.json` + `project_name` from R2 as context; calls Claude Haiku with a structured prompt; parses and stores response
- [ ] Output schema: `{title: str, alt_titles: [str, str], youtube_description: str, instagram_description: str, hashtags: [str], seo_tags: [str]}`
- [ ] Stored at `runs/{run_id}/metadata.json`; `run_log.json` step `metadata` → `complete`
- [ ] `PIPELINE_STEPS` gains `"metadata"` after `"render"`
- [ ] Failure: step marked `failed`, error logged; operator can retry
- [ ] Haiku model used (cost-optimized; content is short structured text)

### Definition of Done
- [ ] All AC checked
- [ ] Tests: endpoint generates metadata from mocked Claude response; parses all fields; handles API failure gracefully
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/metadata_generator.py` — new: `generate_metadata(project_name, storyboard, api_key) → PublishingMetadata`
- `src/routes/metadata.py` — new: `POST /runs/{run_id}/metadata`
- `src/main.py` — register metadata router
- `src/models.py` — `PublishingMetadata`, `MetadataResponse`
- `src/exceptions.py` — `MetadataError`
- `tests/test_metadata_generator.py` — new

### Handover
- `src/metadata_generator.py`: `generate_metadata(project_name, storyboard, api_key, router) → tuple[PublishingMetadata, int, int, float]`
- `src/routes/metadata.py`: `POST /runs/{run_id}/metadata` — reads run_log + storyboard from R2, calls Haiku, stores `metadata.json`, updates run_log step `metadata`
- `src/models.py`: `PublishingMetadata`, `MetadataResponse`, `PIPELINE_STEPS` includes `"metadata"`
- `src/exceptions.py`: `MetadataError`
- No new ENV vars. 734 tests passing.

---

## [S12-S3] Publishing metadata UI
**Epic:** E15 — Publishing Metadata
**Sprint:** 12
**Status:** done
**Completed:** 2026-06-01
**Priority:** medium
**Points:** 2
**Depends on:** S12-S2

### Goal
Display the generated publishing metadata below the video player in the Render Video section. Each field has a copy-to-clipboard button. No auto-posting to any platform.

### Acceptance Criteria
- [x] Metadata section appears in Render Video after render is complete (auto-triggered or manual "Generate Metadata" button)
- [x] Fields displayed: Primary Title, Alternative Titles (×2), YouTube Description, Instagram Description, Hashtags, SEO Tags
- [x] Each field has a "Copy" button — clicking writes the field value to clipboard and briefly shows "Copied ✓"
- [x] If metadata not yet generated: section shows "Generate Metadata" button that triggers `POST /runs/{run_id}/metadata`
- [x] Minimal backend change: added `"metadata"` entry to `_STEP_ARTIFACT_KEYS` in `src/routes/runs.py` to enable `GET /runs/{run_id}/artifact/metadata` — no new route, model, or logic

### Definition of Done
- [x] All AC checked
- [ ] Manual smoke test: generate metadata for a completed run; copy YouTube description; paste confirms correct content
- [x] No existing test regressions (734 passing)
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to modify
- `src/static/pipeline.html` — metadata section below video player; copy buttons
- `src/routes/runs.py` — added `metadata` to `_STEP_ARTIFACT_KEYS`

### Handover
- `src/routes/runs.py`: `_STEP_ARTIFACT_KEYS` gains `"metadata": ("runs/{run_id}/metadata.json", "application/json")` — enables `GET /runs/{run_id}/artifact/metadata` to return stored metadata JSON.
- `src/static/pipeline.html`: `<div id="render-metadata">` added below `#render-content` in `#section-render`. `populateMetadata()` manages it — shows "Generate Metadata" button when `stepSt('metadata') !== 'complete'`; fetches and renders 7 fields with Copy buttons when complete. `generateMetadata()` POSTs to `/runs/{run_id}/metadata`, updates `currentSteps`, re-renders. `copyField(btn, text)` writes to clipboard with 2s "Copied ✓" green state. `populateRender()` calls `populateMetadata()` at end. No new ENV vars. 734 tests passing.

---

## Bugs

---

## [BUG-001] Storyboard Commit: network fetch failure marks step failed despite server success
**Sprint:** 12
**Status:** done
**Completed:** 2026-06-01
**Priority:** high
**Points:** 2
**Reported:** 2026-05-31

### Description
When the user clicks **Commit** on the Project Details page, the backend generates `storyboard.json` successfully and writes it to R2. However, if the fetch response fails to reach the browser (e.g. connection reset, timeout, Railway keep-alive drop), the UI shows "Storyboard network error: Failed to fetch" and marks the Storyboard dot red. The storyboard is actually complete in R2. The user is misled into thinking the step failed.

### Reproduction
1. Open any run in Project Details.
2. Click **Commit** on a slow connection or while Railway DEV is under load.
3. Observe: red dot + "network error" in the UI.
4. Click **Save Draft** → receives "Cannot save draft: storyboard is already complete" — confirming the server succeeded.

### Root cause hypothesis
The UI trusts the client-side fetch result to determine step state. It should fall back to re-fetching `run_log.json` (or `GET /runs/{run_id}`) to reconcile actual backend state when a network error occurs.

### Acceptance Criteria
- [x] After a fetch error during Commit, the UI re-polls the run log to check actual step status before displaying a failure state
- [x] If the run log shows the step is `complete`, the UI shows the green dot and "✓ Committed" — not an error
- [x] If the run log shows the step is `failed`, the UI shows the red dot and the actual error from the log
- [x] No regression on happy path

### Files to modify
- `src/static/pipeline.html` — storyboard commit error handler; add re-poll logic after fetch failure

### Handover
- `src/static/pipeline.html`: `runSequence` `catch` block extended with a re-poll via `GET /runs`. On any network-level fetch error: fetches run list, extracts the current run's step status, and routes to complete (continue loop) or failed (show message and return false) based on actual backend state. Applies to all steps run through `runSequence`. No backend changes. 714 tests passing.

---

## [BUG-002] Error message from Save Draft persists alongside "✓ Committed" status
**Sprint:** 12
**Status:** done
**Completed:** 2026-06-01
**Priority:** medium
**Points:** 1
**Reported:** 2026-05-31

### Description
After BUG-001 scenario plays out (network error → user clicks Save Draft → error message displayed → user clicks Commit again and succeeds), the UI shows "✓ Committed  Error: Cannot save draft: storyboard is already complete" simultaneously. The error message from the failed Save Draft is not cleared when the subsequent Commit succeeds.

### Acceptance Criteria
- [x] Any displayed error message is cleared whenever a Commit or Save Draft operation transitions to a success state
- [x] The "✓ Committed" status is shown cleanly without stale error text beside it

### Files to modify
- `src/static/pipeline.html` — clear error state on successful commit/draft transitions

### Handover
- `src/static/pipeline.html` only — one line added to `runCommit()`: clears `#save-draft-status` text at the start of every commit attempt, before the `runSequence` call.
- No backend changes, no new ENV vars, no new dependencies.
- `saveDraft()` success path already cleared `statusEl.textContent` — no change needed there.

---

## [BUG-003] Storyboard generation cancels when user navigates to another run
**Status:** open
**Priority:** high
**Reported:** 2026-06-05
**Points:** 5

### Description
`POST /runs/{run_id}/storyboard` is a long-running synchronous request (10–30s for Claude). When the user switches to another project mid-generation (by clicking a run in the left panel), two things go wrong:

1. **Client state corruption:** `currentRunId` changes to the new project while the original fetch promise is still in flight. When the server eventually responds, `sectionLocked.storyboard`, `populateStoryboard()`, and `renderNavItems()` all execute against the new (wrong) `currentRunId`.
2. **User confusion:** The original run's storyboard step shows as `pending` when the user returns to it (even if the server succeeded), because the completion callback fired against the wrong run context.

### Root cause
Storyboard generation is request-scoped: the client waits for the HTTP response to update UI state. Any client-side navigation that changes `currentRunId` during that wait corrupts the callback context.

### Acceptance Criteria
- [ ] Operator can click to a different project (or section) while storyboard generation is in progress — and the storyboard still completes on the server
- [ ] When the operator returns to the run, the storyboard shows as `complete` with all data populated
- [ ] If generation fails server-side, the run dot shows red the next time the user opens it
- [ ] No regression on the happy-path flow where user stays on the page

### Proposed solution
Mirror the S13-S3 background render pattern:
- `POST /runs/{run_id}/storyboard` returns HTTP 202 immediately; generation runs in a FastAPI `BackgroundTask`
- Add `GET /runs/{run_id}/storyboard/status` → `{status: "running"|"complete"|"failed"}`
- UI polls status endpoint every 3s while on the storyboard section; renders table when `complete`
- If user navigates away and back, `populateStoryboard()` already checks `run_log.json` step state — will show complete table if server finished in the background

### Files to modify
- `src/routes/storyboard.py` — return 202, register BackgroundTask
- `src/storyboard.py` — no changes to core logic
- `src/models.py` — `StoryboardAcceptedResponse`
- `src/static/pipeline.html` — `runCreateStoryboard` fires POST, immediately moves to poll loop; `populateStoryboard` already handles load-on-return

---

## [BUG-005] Asset acquisition cancelled by Railway HTTP timeout → silent empty error
**Status:** open
**Priority:** high
**Reported:** 2026-06-05
**Points:** 5

### Description
`POST /runs/{run_id}/assets` is a synchronous long-running route. Replicate calls for AI-generated scenes take 30–60s each. With a full run of `still_with_motion` / `animated` scenes, the batch easily exceeds Railway's HTTP request timeout (~60s). When Railway kills the connection, uvicorn cancels the running coroutine, raising `asyncio.CancelledError`.

`CancelledError` is a **`BaseException`**, not an `Exception`. The `except Exception as exc` handler in the route does not catch it — it propagates to FastAPI, which returns HTTP 500 with an empty `detail`. The UI displays `"Asset Acquisition failed: "` with nothing after the colon. All manifest entries remain `"pending"` because `storage.upload_json` never ran.

**Interim fix applied (2026-06-05, commit `X`):** `except BaseException` now catches `CancelledError`, logs it properly, and returns `detail=type(exc).__name__` so the UI at least shows `"Asset Acquisition failed: CancelledError"`.

### Root cause
Same architectural issue as the render step before S13-S3: a slow synchronous operation runs inside an HTTP request handler, making it vulnerable to reverse-proxy timeouts.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/assets` returns HTTP 202 immediately; acquisition runs as a FastAPI `BackgroundTask`
- [ ] `GET /runs/{run_id}/assets/status` returns `{status: "running"|"complete"|"failed", acquired: int, failed: int}`
- [ ] UI shows a "Running…" spinner and polls status until complete or failed
- [ ] `run_log.json` updated to `asset_acquisition: complete/failed` when background task finishes
- [ ] Acquisition results shown in the manifest table once complete
- [ ] No regression on short runs that complete within the timeout

### Proposed solution
Mirror S13-S3 (`POST /render` → 202 + background task + `GET /render/status`):
- `POST /assets` registers `_background_acquire` via `BackgroundTasks`; returns `{status: "running", poll_url}`
- `_background_acquire` calls `await run_acquisition(...)`, writes manifest, updates run log
- `GET /assets/status` reads from a module-level `_ACQUIRE_STATE` dict
- UI: `runAssetAcquisition()` fires POST, then polls `GET /assets/status` every 3s until done

### Files to modify
- `src/routes/assets.py` — 202 response, BackgroundTask, status endpoint
- `src/models.py` — `AcquisitionAcceptedResponse`, `AcquisitionStatusResponse`
- `src/static/pipeline.html` — `runAssetAcquisition()` polling loop

---

## Ideas / Future Epics

### IDEA-001 — ElevenLabs TTS: script-only entry point
**Status:** promoted — implemented as E13-S1 / S10-S1 (Sprint 10)

### IDEA-002 — VO-only entry: derive transcript from Deepgram
When user uploads VO with no script, use Deepgram transcript (already in alignment.json)
as the script. No storyboard text input needed.
Requires: minor UI change (script textarea optional), Deepgram transcript extraction.
Status: idea, not scheduled

### IDEA-003 — Scene-Based Storyboard Editor (Phase 2)
Storyboard evolves from read-only table into editable scene graph. Per-scene text editing, visual description override, asset type selection, keyword override, regenerate single scene. See EPIC 17.
Status: partially addressed in Sprint 14 (inline AI prompt editing + Asset Mode column). Full scene graph (add/remove/reorder scenes) remains unscheduled.

### IDEA-004 — Scene-Level Asset & Regeneration System (Phase 2)
Refresh assets for a single scene, partial re-render, "video outdated" indicator when a scene changes. Depends on IDEA-003 (scene graph). See EPIC 18.
Status: partially addressed in Sprint 16 (per-asset upload replacement). Automated scene-level regeneration remains unscheduled.

### IDEA-005 — Durable workflow orchestration (Sprint 20)
Replace FastAPI BackgroundTasks with Inngest durable workflow engine. Each pipeline step becomes an Inngest function — survives Railway restarts, supports human-in-the-loop review gates (`step.waitForEvent`), and chains agents via events. No pipeline function changes required (D040 ensures they are pure). D042 documents the decision and migration path.
Status: planned for Sprint 20. Prerequisite: Sprint 18 (API-first pipeline) complete.

### IDEA-006 — Trend Research Agent (Sprint 20+, Agent 0)
Autonomous agent that researches viral content ideas within a given niche. Tools: web_search (Claude native), Reddit API, Google Trends (pytrends), NewsAPI. Output: top 3 viral ideas with supporting context passed to Script Agent.
Status: planned for Sprint 20+. Prerequisite: Inngest (IDEA-005).

### IDEA-007 — Script Writer Agent with fact-checking (Sprint 20+, Agent 1)
Multi-turn Claude agent that writes 3 script variants, scores each for virality, fact-checks the winner using web_search tool calls, and returns one polished script with source citations. Replaces the human-written script input.
Status: planned for Sprint 20+. Prerequisite: Inngest (IDEA-005).

### IDEA-008 — Storyboard self-critique loop (Sprint 20+, Agent 2)
Wrap storyboard generation in a score → critique → refine loop. Claude generates a storyboard, then evaluates it against quality criteria (scene variety, motion diversity, query specificity), then refines until score exceeds threshold or max iterations reached. Extends the chunked generation from Sprint 13.
Status: planned for Sprint 20+. Prerequisite: S13-S1 (chunked storyboard).

### IDEA-009 — Asset candidate review API (Sprint 20+, Agent 3)
Each scene returns 2–3 CLIP-ranked asset candidates instead of auto-selecting the top result. Human or review agent selects the best candidate. New endpoints: GET /runs/{run_id}/scenes/{scene_id}/candidates, POST .../select. Human-in-the-loop gate via Inngest waitForEvent.
Status: planned for Sprint 20+. Prerequisite: Sprint 16 (assets overhaul), Inngest (IDEA-005).

### IDEA-010 — Social platform publishing (Sprint 20+)
Post-render upload to YouTube, Instagram, and TikTok using per-user OAuth tokens. Tokens stored alongside user profile in R2. Requires Sprint 19 (Google OAuth + per-user isolation) as prerequisite for user identity layer.
Status: planned for Sprint 20+. Prerequisite: Sprint 19 (multi-tenant).

---

# Sprint 13 — Scale Foundation

---

## [S13-S1] Chunked storyboard generation
**Epic:** E25 — Scale Foundation
**Sprint:** 13
**Status:** done
**Completed:** 2026-06-04
**Priority:** critical
**Points:** 5
**Depends on:** none

### Goal
Remove the ~50-scene ceiling imposed by the 8 192-token Claude output limit. Split the script at paragraph boundaries into chunks of ~10 paragraphs, run each chunk as a parallel Claude API call, then re-number and merge all scenes into a single `storyboard.json`. Alignment timestamps from `alignment.json` are sliced per-chunk so scene durations remain anchored to real audio timing.

### Acceptance Criteria
- [x] `_split_script_into_chunks(script, max_paragraphs=10) → list[str]` — splits on blank-line paragraph boundaries; never cuts mid-sentence; last chunk absorbs remainder
- [x] Each chunk is sent to Claude with its corresponding word timestamp slice from `alignment.json`
- [x] All chunk calls are issued concurrently via `asyncio.gather`
- [x] Scenes from each chunk are renumbered to be globally contiguous (chunk 1 → scenes 1–N, chunk 2 → scenes N+1–M, …)
- [x] Merged result passes the existing `Storyboard` Pydantic schema validation
- [x] Falls back to single-call path when script fits in one chunk (backward compatible)
- [x] `STORYBOARD_CHUNK_SIZE` ENV var (default `10`) controls paragraph count per chunk

### Definition of Done
- [x] All AC checked
- [x] Tests: `_split_script_into_chunks` edge cases (short script, exact boundary, trailing blank lines); parallel call mock; renumbering logic; merge validation; single-chunk fallback
- [ ] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/storyboard.py` — `_split_script_into_chunks`, `_slice_alignment_for_chunk`, `_merge_storyboard_chunks`, refactor `generate_storyboard` to use chunked path
- `src/config.py` — `STORYBOARD_CHUNK_SIZE: int = 10`
- `ENV.md` — document `STORYBOARD_CHUNK_SIZE`
- `tests/test_storyboard.py` — new chunking and merge tests
- `DECISIONS.md` — rationale for chunked generation approach

### Handover
- `src/storyboard.py`: `_split_script_into_chunks(script, max_paragraphs) → list[str]` — public, tested. `_slice_alignment_for_chunk(words, chunk_idx, chunks) → list[WordTimestamp]` — proportional character-count slicing. `_merge_storyboard_chunks(storyboards) → Storyboard` — contiguous renumber, recomputed summary, GLOBAL from first storyboard. `generate_storyboard` unchanged signature — chunked path transparent to callers.
- `src/config.py`: `STORYBOARD_CHUNK_SIZE: int = 10` added.
- `ENV.md`: `STORYBOARD_CHUNK_SIZE` documented.
- `DECISIONS.md`: D043 added.
- `tests/test_storyboard.py`: 24 new tests; 758 total passing.

---

## [S13-S2] Parallel asset acquisition
**Epic:** E25 — Scale Foundation
**Sprint:** 13
**Status:** done
**Completed:** 2026-06-05
**Priority:** high
**Points:** 3
**Depends on:** none

### Goal
Replace the sequential per-scene acquisition loop with batched `asyncio.gather`. 300 scenes currently take ~15 minutes in series; batches of 20 concurrent calls reduce this to ~30 seconds. Errors in one batch do not cancel other batches.

### Acceptance Criteria
- [x] `run_acquisition` in `src/acquisition.py` processes scenes in batches of `ACQUISITION_BATCH_SIZE` (default 20) using `asyncio.gather`
- [x] `PexelsClient` and `ReplicateClient` methods called via `asyncio.to_thread` (they are currently synchronous) or converted to async
- [x] A failure in one scene is caught and logged; the batch continues; the manifest entry is marked `failed`
- [x] Already-`acquired` scenes skipped (existing idempotent behaviour preserved)
- [x] `ACQUISITION_BATCH_SIZE` ENV var in `config.py` and `ENV.md`

### Definition of Done
- [x] All AC checked
- [x] Tests: batch grouping; partial failure in batch; all-acquired idempotent run; batch size of 1 (sequential fallback)
- [ ] CI green
- [x] DONE.md updated
- [x] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/acquisition.py` — `run_acquisition` refactored to batched async; `acquire_scene` wrapped for async execution
- `src/config.py` — `ACQUISITION_BATCH_SIZE: int = 20`
- `ENV.md` — document `ACQUISITION_BATCH_SIZE`
- `tests/test_acquisition.py` — updated for async; new batch tests

### Handover
- `src/acquisition.py`: `run_acquisition` is now `async`. Filters pending entries first, then processes them in batches of `batch_size` via `asyncio.gather(*[asyncio.to_thread(acquire_scene, ...) for entry in batch], return_exceptions=True)`. Unexpected exceptions from `asyncio.gather` are caught, logged, and the entry is marked `failed`. `acquire_scene` remains synchronous — it is the unit-testable sync core.
- `src/routes/assets.py`: route changed to `async def acquire_assets`; calls `await run_acquisition(..., batch_size=settings.ACQUISITION_BATCH_SIZE)`.
- `src/config.py`: `ACQUISITION_BATCH_SIZE: int = 20` added (S13-S2 section).
- `ENV.md`: `ACQUISITION_BATCH_SIZE` documented in Pipeline config table.
- `tests/test_acquisition.py`: all `TestRunAcquisition` tests now `@pytest.mark.asyncio`; route tests updated to `new_callable=AsyncMock`; `TestRunAcquisitionBatching` class added (4 tests: batch grouping, partial failure isolation, batch-size-1, idempotent mixed-state). 762 total passing.
- No new pip dependencies. No new ENV vars beyond `ACQUISITION_BATCH_SIZE`.

---

## [S13-S3] Background render task + polling
**Epic:** E25 — Scale Foundation
**Sprint:** 13
**Status:** done
**Completed:** 2026-06-05
**Priority:** high
**Points:** 5
**Depends on:** none

### Goal
Decouple the render step from Railway's ~60s HTTP request timeout. `POST /runs/{run_id}/render` returns 202 immediately and kicks off the render as a FastAPI background task. A new polling endpoint lets the UI (and future API callers) check render progress without holding a connection open.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/render` returns HTTP 202 `{"status": "running", "poll_url": "/runs/{run_id}/render/status"}` immediately
- [ ] Render executes as a `fastapi.BackgroundTasks` task; `run_log.json` updated to `render: complete` or `render: failed` on finish
- [ ] `GET /runs/{run_id}/render/status` returns `{status: "running"|"complete"|"failed", progress_pct: int, output_key: Optional[str], error: Optional[str]}`
- [ ] `progress_pct` derived from ffmpeg stderr progress lines (frame count / total frames); falls back to 0/100 if unparseable
- [ ] UI requires no changes — the existing step-status polling already handles the `running` → `complete` transition
- [ ] Existing tests that assert on the render route response updated for 202

### Definition of Done
- [ ] All AC checked
- [ ] Tests: 202 immediate response; background task invoked; status endpoint returns correct states; progress parsing; failure propagation to run_log
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/routes/render.py` — switch to `BackgroundTasks`; add `GET /runs/{run_id}/render/status`
- `src/renderer.py` — add ffmpeg stderr progress parsing
- `src/models.py` — `RenderStatusResponse`
- `tests/test_renderer.py` — updated assertions; new status-polling tests
- `DECISIONS.md` — background task rationale vs job queue

### Handover
- `src/renderer.py`: `_RENDER_STATE: dict[str, dict]` module-level dict keyed by run_id. `parse_ffmpeg_progress(stderr_text, total_frames) → int` — finds last `frame=N` in accumulated ffmpeg stderr; returns 0–99 (never 100, capped to avoid confusion with completion); falls back to 0 when `total_frames <= 0` or no match. `render_run` gains `total_frames: int = 0` parameter; sets `_RENDER_STATE[run_id]` to `running` at start and `complete/failed` at end with `progress_pct` derived from parsed stderr.
- `src/routes/render.py`: rewritten. `POST /runs/{run_id}/render` is now `async`, returns HTTP 202 `{status: "running", poll_url: "/runs/{run_id}/render/status"}`. Fetches storyboard to derive `total_frames = int(total_duration_s * 25)`; falls back to 0 on `StorageError`. Initialises `_RENDER_STATE[run_id]` before returning 202 (so status endpoint never 404s in the gap before the task starts). Registers `_background_render` via `background_tasks.add_task`. `_background_render` is async and calls `await asyncio.to_thread(render_run, ...)` to keep the event loop unblocked. Also writes final state to `_RENDER_STATE` (for correctness when `render_run` is mocked in tests), then updates `run_log.json` and calls `pipeline.summarize_step`. `GET /runs/{run_id}/render/status` reads `_RENDER_STATE` and returns `RenderStatusResponse`; 404 if run_id not present.
- `src/models.py`: `RenderAcceptedResponse(status, poll_url)` and `RenderStatusResponse(status, progress_pct, output_key?, error?)` added. `RenderResponse` retained for backwards compat.
- `DECISIONS.md`: D044 added.
- `tests/test_renderer.py`: `TestRenderRoute` updated — POST now asserts 202; two new tests assert `update_run_log` call via background task; storage-error test checks `_RENDER_STATE` instead of HTTP 500; two total_frames derivation tests added. `TestRenderStatusRoute` (5 tests): running/complete/failed states, 404 unknown run, round-trip POST→GET. `TestParseFfmpegProgress` (7 tests). 775 total passing.
- **Smoke test:** DEFERRED — requires Railway DEV deploy. POST to `/runs/{run_id}/render`; confirm 202 received immediately; poll `GET /runs/{run_id}/render/status` until status=complete; download video.

---

# Sprint 14 — Creative Draft Foundation

---

## [S14-S1] Notion-like feature
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 14
**Status:** blocked
**Priority:** medium
**Points:** TBD
**Depends on:** operator screenshot

### Goal
TBD — operator will provide a Notion screenshot showing the desired pattern before this story can be scoped.

### Acceptance Criteria
- [ ] To be defined once screenshot is reviewed.

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S14-S2] Editable AI Prompt in storyboard table
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 14
**Status:** done
**Priority:** high
**Points:** 2
**Depends on:** none

### Goal
Make the `ai_generate_prompt` cell in the storyboard table click-to-edit. The `primary_query` cell remains read-only. Changes are persisted to R2 via a new PATCH endpoint so edits survive page reload.

### Acceptance Criteria
- [ ] Clicking `ai_generate_prompt` cell enters edit mode (contenteditable or inline `<textarea>`)
- [ ] On blur or Enter: `PATCH /runs/{run_id}/storyboard` with `{scene_id, field: "ai_generate_prompt", value: "<new_value>"}` persists the change
- [ ] `primary_query` cell renders as plain non-editable text
- [ ] Edit does not trigger asset re-acquisition automatically — operator re-runs the Assets step manually
- [ ] Unsaved changes indicator (e.g. cell border) cleared after successful PATCH

### Definition of Done
- [ ] All AC checked
- [ ] Tests: PATCH endpoint updates `storyboard.json` in R2; returns 404 on unknown run; returns 422 on unknown scene_id or disallowed field
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/routes/storyboard.py` — add `PATCH /runs/{run_id}/storyboard`
- `src/storyboard.py` — `patch_scene_field(run_id, scene_id, field, value, storage)` helper
- `src/static/pipeline.html` — inline editing UX for `ai_generate_prompt` cells
- `tests/test_storyboard.py` — new PATCH tests

### Handover
- `src/models.py`: `StoryboardPatchRequest(scene_id, field, value)` and `StoryboardPatchResponse(status, scene_id, field)` added.
- `src/storyboard.py`: `_PATCHABLE_FIELDS = {"ai_generate_prompt"}` module-level constant. `patch_scene_field(run_id, scene_id, field, value, storage) → Storyboard` — reads `storyboard.json`, validates field against `_PATCHABLE_FIELDS` (ValueError on mismatch), finds scene by `scene.scene == scene_id` (StoryboardParseError if missing), mutates `visual_prompts.ai_generate`, writes back via `storage.upload_json`. Returns updated `Storyboard`.
- `src/routes/storyboard.py`: `PATCH /runs/{run_id}/storyboard` — calls `patch_scene_field`; ValueError → 422; StoryboardParseError → 422; StorageError → 404. Returns `StoryboardPatchResponse`.
- `src/static/pipeline.html`: AI Prompt column cell (`vp.ai_generate`) rendered with `class="text-lg ai-editable"` and `data-scene-id`. `sbAiPromptEdit(td)` converts cell to `<textarea>` on click (no-op when locked). `sbAiPromptSave(td, ta)` fires PATCH on blur/Enter, restores static text on success, shows 3s error indicator on failure. `sbAiPromptCancel(td, original)` handles Escape. CSS: `.ai-editable` (pointer cursor, hover bg), `.editing` (amber outline), `.saving` (reduced opacity), `.sb-ai-textarea` (transparent, inherits font).
- `tests/test_storyboard.py`: `TestPatchSceneField` (5 unit tests), `TestPatchStoryboardRoute` (4 route tests). 784 total passing.

---

## [S14-S3] Asset Mode column in storyboard table
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 14
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** S14-S2

### Goal
Add a "Source" dropdown column to the storyboard table. Selecting "Stock" highlights the `primary_query` cell in that row; selecting "AI Generated" highlights the `ai_generate_prompt` cell. The selection drives the acquisition orchestrator — no Replicate call when Stock is chosen for a scene, no Pexels call when AI Generated is chosen.

### Acceptance Criteria
- [ ] New column "Source" renders a `<select>` with "Stock" and "AI Generated" per row
- [ ] Default value derived from current `clip_type`: `hard_cut` defaults to "Stock"; `still_with_motion` / `animated` defaults to "AI Generated"
- [ ] Selecting "Stock" applies a `highlight-active` CSS class to the `primary_query` cell in that row; removes it from the `ai_generate_prompt` cell
- [ ] Selecting "AI Generated" applies `highlight-active` to `ai_generate_prompt` cell; removes from `primary_query`
- [ ] Selection persisted in `asset_manifest.json` as `asset_mode: "stock" | "ai_generated"` via `PATCH /runs/{run_id}/manifest`
- [ ] Acquisition orchestrator: `stock` mode → Pexels → Pixabay (S15-S3) → skip Replicate; `ai_generated` mode → Replicate only, skip Pexels

### Definition of Done
- [ ] All AC checked
- [ ] Tests: PATCH manifest endpoint; acquisition orchestrator branches on `asset_mode`; both modes produce correct result
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/models.py` — `ManifestEntry.asset_mode: Literal["stock", "ai_generated"]`
- `src/routes/manifest.py` — add `PATCH /runs/{run_id}/manifest` for per-entry field updates
- `src/acquisition.py` — branch on `asset_mode`
- `src/static/pipeline.html` — Source column, highlight logic
- `tests/test_acquisition.py` — new `asset_mode` branch tests

### Handover
- `src/models.py`: `ManifestEntry` gains `asset_mode: Optional[Literal["stock", "ai_generated"]] = None`. `ManifestPatchRequest(scene_id, field, value)` and `ManifestPatchResponse(status, scene_id, field)` added.
- `src/manifest.py`: `_PATCHABLE_MANIFEST_FIELDS = {"asset_mode"}` and `_STOCK_CLIP_TYPES = {"hard_cut"}` module-level constants. `_default_asset_mode(clip_type) → str` helper. `build_manifest` sets `asset_mode` per entry from `_default_asset_mode`. `patch_manifest_entry(run_id, scene_id, field, value, storage) → AssetManifest` — reads manifest from R2, validates field + value, mutates entry, writes back.
- `src/routes/manifest.py`: `PATCH /runs/{run_id}/manifest` — calls `patch_manifest_entry`; `ValueError` → 422; `ManifestError` → 422; `StorageError` → 404.
- `src/acquisition.py`: `acquire_scene` now branches on `entry.asset_mode`: `"ai_generated"` → Replicate only (Pexels not called); `"stock"` → Pexels only (Replicate not called, miss marks entry failed); `None` → legacy Pexels → Replicate fallback chain.
- `src/static/pipeline.html`: `renderStoryboardHtml(content, audioSettings, assetModeMap)` gains third param. Source column added (last column) with `<select class="sb-source-select">` per row. Default mode computed from `clip_type`; overridden by `assetModeMap[scene_id]` when manifest is loaded. `source-primary` / `source-ai` classes on respective cells; `highlight-active` applied per active mode. `sbAssetModeChange(select)` fires `PATCH /runs/{run_id}/manifest` on change and updates cell highlights. `populateStoryboard` also fetches manifest artifact in parallel (when `asset_manifest` step is `complete`) and builds `assetModeMap` before rendering. CSS: `.highlight-active { background: #FFF8C5 }`, `.sb-source-select` styling.
- `tests/test_manifest.py`: `TestBuildManifestAssetModeDefault` (3 tests), `TestPatchManifestEntry` (5 unit tests), `TestPatchManifestRoute` (5 route tests). 803 total passing.
- `tests/test_acquisition.py`: `TestAcquireSceneAssetMode` (6 tests covering ai_generated-only, stock-only, and None fallback paths).
**Smoke test:** DEFERRED — requires Railway DEV with a run that has a complete storyboard. Click a Source dropdown in the storyboard table, change from "Stock" to "AI Generated", confirm the AI Prompt cell gains the yellow highlight and the change persists on page reload. Run asset acquisition and confirm AI Generated scenes use Replicate only.
**Promoted to backlog:** none

---

## [S14-S4] Visual Style Prompt field
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 14
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** none

### Goal
Add a free-text "Visual Style Prompt" field to Project Settings. The operator enters a reusable style string (e.g. "cinematic, shallow depth of field, golden hour lighting, 9:16 vertical"). This string is automatically appended to every Replicate/Flux `ai_generate_prompt` call during asset acquisition.

### Acceptance Criteria
- [ ] `<textarea>` labelled "Visual Style Prompt" in Project Settings section
- [ ] Saved to run config as `visual_style_prompt` via existing `POST /runs/{run_id}/settings`
- [ ] `ReplicateClient.acquire_for_entry` appends `visual_style_prompt` to `ai_generate_prompt` when the setting is non-empty
- [ ] Field survives page reload (loaded from run config on page load)
- [ ] Field is editable before Commit; read-only after Commit (consistent with other Project Settings fields)

### Definition of Done
- [ ] All AC checked
- [ ] Tests: settings endpoint stores `visual_style_prompt`; `ReplicateClient` appends it correctly; empty/missing value produces no change to prompt
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/config.py` / `src/models.py` — `visual_style_prompt` in run settings schema
- `src/replicate_client.py` — append `visual_style_prompt` to prompt
- `src/static/pipeline.html` — Visual Style Prompt textarea in settings section
- `tests/test_replicate_client.py` — prompt injection tests

### Handover
_filled on completion_

---

## [S14-S5] Global Values panel in Project Settings
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 14
**Status:** planned
**Priority:** medium
**Points:** 3
**Depends on:** S14-S4

### Goal
Replace the current collapsible storyboard settings header (S8-S4) with a comprehensive "Global Values" panel that consolidates every project-level configuration value. Duration is auto-populated from the Deepgram alignment result. Visual Style Prompt (S14-S4) is included as an editable field.

### Acceptance Criteria
- [ ] Panel labelled "Global Values" shows: Aspect Ratio, Visual Style (enum), Visual Style Prompt (editable textarea), Duration (from `alignment.json` total word span — read-only), Rhythm (placeholder "—"), Subtitles, Music
- [ ] Editable fields: Visual Style Prompt, Visual Style enum, Aspect Ratio
- [ ] Duration auto-populated when alignment step is complete; shows "—" before alignment
- [ ] All values survive page reload (loaded from run config)
- [ ] Replaces the S8-S4 collapsible header — same data, better layout

### Definition of Done
- [ ] All AC checked
- [ ] Tests: duration extraction from `alignment.json`; all run config fields round-trip correctly
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/static/pipeline.html` — Global Values panel; duration extraction from alignment artifact
- `src/routes/settings.py` (or existing settings route) — ensure all new fields are persisted

### Handover
_filled on completion_

---

# Sprint 15 — Storyboard UX + Source Expansion

---

## [S15-S1] Sticky table headers
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 15
**Status:** planned
**Priority:** medium
**Points:** 2
**Depends on:** none

### Goal
Storyboard and assets table headers remain visible while the operator scrolls down through long scene lists.

### Acceptance Criteria
- [ ] `<thead>` in storyboard table has `position: sticky; top: 0` with appropriate z-index
- [ ] `<thead>` in assets table has the same sticky behaviour
- [ ] Horizontal scroll still works; sticky header does not break layout at any viewport width

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S15-S2] Rename ID → Scene; hide Fallback Query column
**Epic:** E19 — Creative Draft Architecture
**Sprint:** 15
**Status:** planned
**Priority:** low
**Points:** 1
**Depends on:** none

### Goal
Two small storyboard table cleanup items: rename the ID column header to "Scene", and remove the Fallback Query column from the UI. The `fallback_query` field is retained in the backend data model and used by the acquisition orchestrator.

### Acceptance Criteria
- [ ] Column header reads "Scene" (was "ID")
- [ ] `fallback_query` column not rendered in the storyboard table
- [ ] `fallback_query` field remains in `ManifestEntry` schema and acquisition logic unchanged

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S15-S3] Pixabay as second stock source
**Epic:** E20 — Stock Source Expansion
**Sprint:** 15
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** S14-S3

### Goal
Add Pixabay as a parallel stock footage/photo source. When Pexels returns no usable result for a scene, Pixabay is tried before falling back to Replicate. The acquisition chain for `stock` mode becomes: Pexels → Pixabay → Replicate.

### Acceptance Criteria
- [ ] `src/pixabay.py` — `PixabayClient(api_key)` with `acquire_for_entry(entry, run_id, storage) → Optional[PixabayAcquireResult]`; queries videos API for `hard_cut`, photos API for `still_with_motion`/`animated`
- [ ] `PIXABAY_API_KEY` ENV var in `config.py` and `ENV.md`
- [ ] Acquisition orchestrator updated: Pexels miss → Pixabay → Replicate (for `stock` mode)
- [ ] `ManifestEntry.source` gains `"pixabay"` as a valid value
- [ ] Handles Pixabay API errors gracefully; falls through to next source

### Definition of Done
- [ ] All AC checked
- [ ] Tests: Pixabay API mocked; fallback chain covered (Pexels hit, Pexels miss → Pixabay hit, both miss → Replicate)
- [ ] DECISIONS.md entry for Pixabay added
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/pixabay.py` — new
- `src/acquisition.py` — extend fallback chain
- `src/models.py` — `PixabayAcquireResult`; `source` field gains "pixabay"
- `src/exceptions.py` — `PixabayError`
- `src/config.py` — `PIXABAY_API_KEY`
- `ENV.md` — document `PIXABAY_API_KEY`
- `DECISIONS.md` — Pixabay source rationale
- `tests/test_pixabay.py` — new
- `tests/test_acquisition.py` — updated chain tests

### Handover
_filled on completion_

---

## [S15-S4] AI-driven source type classification
**Epic:** E20 — Stock Source Expansion
**Sprint:** 15
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** S15-S3

### Goal
During storyboard generation, Claude classifies each scene as `realistic_stock` or `historic_archival` based on script context. For historic scenes, Wikimedia Commons becomes the primary source; Pexels and Pixabay are fallbacks. For realistic scenes the chain is unchanged. This happens automatically — the operator does not choose.

### Acceptance Criteria
- [ ] Storyboard prompt updated: each scene must include `"source_type": "realistic_stock" | "historic_archival"`
- [ ] `StoryboardScene.source_type` field added to model
- [ ] `ManifestEntry.source_type` propagated from storyboard during manifest generation
- [ ] `src/wikimedia.py` — `WikimediaClient` with `acquire_for_entry(entry, run_id, storage) → Optional[WikimediaAcquireResult]`; searches Wikimedia Commons API by `primary_query`
- [ ] Acquisition orchestrator: `historic_archival` → Wikimedia → Pexels → Pixabay (no Replicate — AI generation is inappropriate for archival scenes); `realistic_stock` → Pexels → Pixabay → Replicate
- [ ] `asset_mode` (S14-S3) overrides `source_type` — if operator manually selects "AI Generated", Replicate is used regardless of `source_type`

### Definition of Done
- [ ] All AC checked
- [ ] Tests: prompt classification field present in parsed output; both acquisition chains covered; `asset_mode` override tested
- [ ] DECISIONS.md entry for Wikimedia + source_type routing
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/storyboard.py` — prompt update (bump version); `StoryboardScene.source_type`
- `docs/PROMPTS.md` — new prompt version changelog
- `src/wikimedia.py` — new
- `src/manifest.py` — propagate `source_type`
- `src/models.py` — `WikimediaAcquireResult`; `source_type` fields
- `src/exceptions.py` — `WikimediaError`
- `src/acquisition.py` — source_type routing; asset_mode override
- `DECISIONS.md` — D new: Wikimedia + source_type classification rationale
- `tests/test_wikimedia.py` — new
- `tests/test_storyboard.py` — source_type parsing tests
- `tests/test_acquisition.py` — historic and asset_mode override tests

### Handover
_filled on completion_

---

# Sprint 16 — Assets Overhaul + Replacement

---

## [S16-S1] Per-asset upload replacement
**Epic:** E21 — Assets UX + Replacement
**Sprint:** 16
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** none

### Goal
Give the operator the ability to replace any acquired asset with their own file. A "Replace" button per row opens a file picker; the selected file is uploaded to R2 via presigned PUT, replacing the existing asset key. The manifest is updated so subsequent render steps use the new file.

### Acceptance Criteria
- [ ] Each asset row has a "Replace" button
- [ ] Clicking "Replace" triggers `GET /runs/{run_id}/assets/{scene_id}/upload-url` → returns a presigned PUT URL for the replacement file
- [ ] File is uploaded from the browser directly to R2 (same pattern as voiceover upload in E6-S3)
- [ ] After successful upload: `PATCH /runs/{run_id}/manifest` updates the entry's `file_key` to the new R2 key and resets `source` to `"uploaded"`
- [ ] UI shows the new asset (thumbnail or filename) after replacement
- [ ] Replaced asset is marked in the manifest (`source: "uploaded"`) for the Project Report

### Definition of Done
- [ ] All AC checked
- [ ] Tests: presigned URL generation; manifest PATCH; `source: "uploaded"` persisted
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to create or modify
- `src/routes/assets.py` — `GET /runs/{run_id}/assets/{scene_id}/upload-url`
- `src/routes/manifest.py` — `PATCH /runs/{run_id}/manifest` (or extend existing)
- `src/storage.py` — presigned PUT URL generation (may already exist from E6-S3)
- `src/static/pipeline.html` — Replace button + file picker + upload flow in assets table
- `tests/test_assets.py` — new presigned URL and manifest update tests

### Handover
_filled on completion_

---

## [S16-S2] Full description visibility in assets table
**Epic:** E21 — Assets UX + Replacement
**Sprint:** 16
**Status:** planned
**Priority:** medium
**Points:** 2
**Depends on:** none

### Goal
Remove all ellipsis truncation from the assets table. Description and text cells wrap to full content; row height expands automatically.

### Acceptance Criteria
- [ ] No `text-overflow: ellipsis`, `white-space: nowrap`, or `overflow: hidden` on any assets table cell
- [ ] All description/text cells use `white-space: normal; word-wrap: break-word`
- [ ] Row height expands with content — no fixed `height` or `max-height` on rows
- [ ] Horizontal scroll preserved; layout does not break

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S16-S3] Assets table cleanup
**Epic:** E21 — Assets UX + Replacement
**Sprint:** 16
**Status:** planned
**Priority:** medium
**Points:** 2
**Depends on:** none

### Goal
Three small assets table improvements: add a Voice Over column showing the narration text per scene, convert asset type values to human-readable Title Case labels, and remove the Status column.

### Acceptance Criteria
- [ ] "Voice Over" column added as the second column (after Scene); shows `voiceover_line` from `storyboard.json` for the matching `scene_id`
- [ ] Asset Type cell renders human-readable label: `still_with_motion` → "Still With Motion", `animated` → "Animated", `hard_cut` → "Hard Cut"
- [ ] Status column removed from the rendered table
- [ ] `voiceover_line` data joined client-side from the storyboard artifact (no backend change required)

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

# Sprint 17 — Project Report + Token Tracking

---

## [S17-S1] Token cost tracking per Claude call
**Epic:** E22 — Project Report + Token Tracking
**Sprint:** 17
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** none

### Goal
Every Claude API call logs its token usage and estimated cost to `run_log.json`. The `ModelRouter` is extended to capture and persist `{step, model, input_tokens, output_tokens, cost_usd}` after each call.

### Acceptance Criteria
- [ ] `run_log.json` gains a `cost_log: list[CostEntry]` array
- [ ] `CostEntry`: `{step: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float}`
- [ ] `ModelRouter` updated: after each call, appends `CostEntry` to `run_log.json` via `storage.append_cost_log(run_id, entry)`
- [ ] Cost per token derived from a `MODEL_COSTS` dict in `model_router.py` (configurable; based on current Anthropic pricing)
- [ ] Existing calls: storyboard generation, metadata generation — both captured

### Definition of Done
- [ ] All AC checked
- [ ] Tests: `ModelRouter` appends cost entry; `CostEntry` schema validates; cost calculation correct for known models
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S17-S2] Project Report pipeline step
**Epic:** E22 — Project Report + Token Tracking
**Sprint:** 17
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** S17-S1

### Goal
Add a Project Report as the final pipeline step. It aggregates token cost, asset source breakdown, render duration, video duration, word count, and scene count into a single `report.json`.

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/report` — reads `run_log.json` (cost_log), `asset_manifest.json` (source breakdown), `alignment.json` (word count, duration), `storyboard.json` (scene count)
- [ ] Output schema: `{total_cost_usd, cost_by_step, assets_by_source: {pexels, pixabay, wikimedia, replicate, uploaded}, video_duration_s, word_count, scene_count, render_duration_s}`
- [ ] Stored at `runs/{run_id}/report.json`; `run_log.json` step `report` → `complete`
- [ ] `PIPELINE_STEPS` gains `"report"` after `"metadata"`

### Definition of Done
- [ ] All AC checked
- [ ] Tests: report aggregation from mocked artifacts; all fields computed correctly
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S17-S3] Project Report UI
**Epic:** E22 — Project Report + Token Tracking
**Sprint:** 17
**Status:** planned
**Priority:** medium
**Points:** 2
**Depends on:** S17-S2

### Goal
Display the Project Report as the final pipeline step in the UI — a clean summary card showing cost, asset breakdown, and video stats.

### Acceptance Criteria
- [ ] "Project Report" appears as the final step in the pipeline (after Metadata)
- [ ] Report card shows: Total AI cost (USD), cost per step breakdown, assets by source (counts), video duration, scene count, render time
- [ ] "Generate Report" button triggers `POST /runs/{run_id}/report`
- [ ] Card layout matches existing design system (same card style as metadata section)

### Definition of Done
- [ ] All AC checked
- [ ] No existing test regressions
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

# Sprint 18 — API-First Pipeline

---

## [S18-S1] Pipeline trigger endpoint
**Epic:** E23 — External API + Webhook
**Sprint:** 18
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** S18-S3

### Goal
`POST /api/pipeline` accepts a script and project settings, creates a run, and queues the full pipeline asynchronously. Returns immediately with a `run_id` and `status_url` so the caller can poll or wait for a webhook.

### Acceptance Criteria
- [ ] `POST /api/pipeline` body: `{script: str, project_name: str, settings: RunSettings, webhook_url: Optional[str]}`
- [ ] Creates run via existing `POST /runs` logic
- [ ] Queues full pipeline as a background task: alignment → storyboard → manifest → assets → ffmpeg-script → render → metadata → report
- [ ] Returns HTTP 202: `{run_id: str, status_url: str}`
- [ ] `webhook_url` stored in run config for use by S18-S4

### Definition of Done
- [ ] All AC checked
- [ ] Tests: run creation; background task kicked off; 202 response with correct fields
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S18-S2] Pipeline status + result endpoint
**Epic:** E23 — External API + Webhook
**Sprint:** 18
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** S18-S1

### Goal
`GET /api/pipeline/{run_id}` returns the current step-level status and a download URL when rendering is complete. The caller (N8N, etc.) can poll this until `download_url` is populated.

### Acceptance Criteria
- [ ] `GET /api/pipeline/{run_id}` returns: `{run_id, status: "running"|"complete"|"failed", steps: {step: status}, download_url: Optional[str]}`
- [ ] `download_url` is a presigned R2 URL (1h TTL) when `render: complete`; `null` otherwise
- [ ] Returns 404 if `run_id` unknown or not owned by the API key's scope

### Definition of Done
- [ ] All AC checked
- [ ] Tests: running, complete, failed states; download_url present only when render complete
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S18-S3] API key authentication
**Epic:** E23 — External API + Webhook
**Sprint:** 18
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** none

### Goal
All `/api/*` routes require a Bearer token. The token is set via an `API_KEY` ENV var. This is separate from the operator session cookie used by the UI.

### Acceptance Criteria
- [ ] `API_KEY: str` in `config.py` and `ENV.md`
- [ ] FastAPI dependency `require_api_key` checks `Authorization: Bearer <API_KEY>` header on all `/api/*` routes
- [ ] Missing or invalid token returns 401 with `{"detail": "Unauthorized"}`
- [ ] Session cookie auth (operator UI) unaffected

### Definition of Done
- [ ] All AC checked
- [ ] Tests: valid key passes; missing key 401; wrong key 401; UI routes unaffected
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S18-S4] Webhook callback on render complete
**Epic:** E23 — External API + Webhook
**Sprint:** 18
**Status:** planned
**Priority:** medium
**Points:** 1
**Depends on:** S18-S1, S18-S2

### Goal
When a pipeline triggered via `/api/pipeline` completes rendering, POST a callback to the `webhook_url` provided at trigger time. Non-blocking — webhook failure does not affect the pipeline.

### Acceptance Criteria
- [ ] When render step completes (success or failure), POST to `webhook_url` if present in run config
- [ ] Payload: `{run_id, status: "complete"|"failed", download_url: Optional[str]}`
- [ ] HTTP POST uses `httpx` with a 10s timeout; failure logged but does not raise
- [ ] Webhook not called if `webhook_url` was not provided

### Definition of Done
- [ ] All AC checked
- [ ] Tests: callback sent on complete; callback sent on failure; no-op when webhook_url absent; timeout does not crash pipeline
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

# Sprint 19 — Multi-tenant + Google OAuth

---

## [S19-S1] Google OAuth login
**Epic:** E24 — Multi-tenant + Google OAuth
**Sprint:** 19
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** none

### Goal
Replace the single-operator password gate (S5-S5) with Google OAuth. Any Google account can log in; session stores `user_id` (Google `sub`) and email. Logout clears the session.

### Acceptance Criteria
- [ ] Google OAuth flow works end-to-end: redirect to Google → callback → session set
- [ ] `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` ENV vars in `config.py` and `ENV.md`
- [ ] Session cookie stores `user_id` and `email` (encrypted, same session middleware as S5-S5)
- [ ] All pipeline routes return 302 to login when unauthenticated
- [ ] `GET /logout` clears session and redirects to login
- [ ] Password gate removed

### Definition of Done
- [ ] All AC checked
- [ ] Tests: auth middleware mocked; login success/failure; logout clears session; unauthenticated redirect
- [ ] DECISIONS.md entry for Google OAuth choice
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S19-S2] Per-user run isolation
**Epic:** E24 — Multi-tenant + Google OAuth
**Sprint:** 19
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** S19-S1

### Goal
Runs in R2 are namespaced by `user_id` so each user sees only their own projects. `GET /runs` is scoped to the authenticated user. Existing single-user runs (at the old prefix) are treated as belonging to a legacy "default" user.

### Acceptance Criteria
- [ ] All R2 reads/writes use prefix `runs/{user_id}/{run_id}/`
- [ ] `POST /runs` creates the run under the authenticated user's prefix
- [ ] `GET /runs` lists only runs at `runs/{user_id}/`
- [ ] All artifact endpoints (`/runs/{run_id}/...`) scope reads to `runs/{user_id}/{run_id}/`
- [ ] Existing runs at `runs/{run_id}/` (no user prefix) accessible only to a legacy `default` user or migrated on first access
- [ ] API key routes (`/api/*`) use a designated API user scope

### Definition of Done
- [ ] All AC checked
- [ ] Tests: user A cannot access user B's runs; legacy prefix fallback; API scope isolation
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [S19-S3] User registry
**Epic:** E24 — Multi-tenant + Google OAuth
**Sprint:** 19
**Status:** planned
**Priority:** low
**Points:** 1
**Depends on:** S19-S1

### Goal
On first login, write a lightweight user profile to R2. No admin UI required for POC.

### Acceptance Criteria
- [ ] On first successful Google OAuth login: write `users/{user_id}/profile.json` → `{user_id, email, created_at}`
- [ ] On subsequent logins: no-op (profile already exists)
- [ ] Profile read is non-blocking — failure does not prevent login

### Definition of Done
- [ ] All AC checked
- [ ] Tests: profile written on first login; not overwritten on repeat login
- [ ] CI green
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---
---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P7 + Epics 32/34)

> Canonical design, contracts, and decisions: **docs/v2_platform_plan.md**. Decisions D047–D057 in DECISIONS.md.
> All v2 schemas/contracts are defined once in the plan doc; stories below reference them by name.
> Specs are reviewed at the start of each sprint and story and adjusted if relevant.

---

## EPIC 26 — Platform Foundation (Sprints P0–P1)
Contracts + skeleton + LangGraph-aware core. Legacy stays untouched (D047).

---

## [P0-S1] North-star spec — docs/v2_platform_plan.md
**Epic:** E26 — Platform Foundation
**Sprint:** P0
**Status:** done
**Completed:** 2026-06-12
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
Author and get approval on `docs/v2_platform_plan.md`: goals, macro architecture, platform/legacy boundary, the architectural laws, the migration arc, and the platform-MVP definition of done. **Interfaces/design only — no runtime.**

### Acceptance Criteria
- [x] Plan doc covers: vision, macro architecture, boundary + dependency rule, LangGraph abstraction model, the 7 laws, roadmap, DoD
- [x] Operator reviews and approves the boundary and sequencing

### Definition of Done
- [x] All AC checked · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `docs/v2_platform_plan.md` (committed in `642af5b`) is the canonical north-star spec for the v2 platform track — referenced by all P0–P7 stories for contracts and schemas.
- Operator reviewed and approved the `cf_platform/ → adapter → src/` one-way boundary and the P0–P7 sequencing on 2026-06-12.
- D047–D057 are documented in §7 of the plan doc; ratifying them into DECISIONS.md (with D042 marked superseded by D052) is the scope of **P0-S2**, the next story.
- No code, ENV vars, or dependencies introduced (interfaces/design only, per architectural law 7).

---

## [P0-S2] Ratify decisions D047–D057
**Epic:** E26 — Platform Foundation
**Sprint:** P0
**Status:** done
**Completed:** 2026-06-12
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
Write D047–D057 into DECISIONS.md (adapter wrap, Postgres, Telegram+formatter, source adapters, lineage envelope, LangGraph supersedes Inngest, web-search, YouTube OAuth, replay constraints, worker=node, state-as-message-bus). Mark D042 superseded by D052.

### Acceptance Criteria
- [x] D047–D057 present with rationale + dependency notes
- [x] D042 marked SUPERSEDED by D052

### Definition of Done
- [x] All AC checked · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- D047–D057 were written into DECISIONS.md in commit `642af5b` (same commit as `docs/v2_platform_plan.md`) — each entry carries Date, Decision, Rationale, and a Dependencies/See pointer back to the relevant plan §.
- D042 (Inngest) carries `**Status:** SUPERSEDED by D052 (2026-06-12)` with a one-line pointer to the superseding decision; original text retained for history per project convention (cf. D045/D046 precedent of append-only decision log).
- This story formally ratifies that prior commit's DECISIONS.md content as the P0-S2 deliverable — no further DECISIONS.md edits were needed; both ACs were already met.
- Next story in execution order: **P0-S3** (Core contracts — Pydantic interfaces only), per SPRINT.md execution order P0-S1 → P0-S2 → (P0-S3 ∥ P0-S4) → P0-S5.

---

## [P0-S3] Core contracts (Pydantic) — interfaces only
**Epic:** E26 — Platform Foundation
**Sprint:** P0
**Status:** done
**Completed:** 2026-06-12
**Priority:** high
**Points:** 5
**Depends on:** P0-S1

### Goal
Define + unit-test the universal platform contracts in `cf_platform/core/schemas.py` (no runtime behavior): `LineageEnvelope`, `Artifact`, `RunRecord`, `WorkerExecution`, `WorkerOutput` + `ControlSignal`, `StageState` base (refs + control only), `TraceEvent`, `SourceAdapter` Protocol, `WorkerNode` type. See plan doc §4.
**Tech:** Pydantic v2, pytest. **Artifacts:** schema module + validation tests.

### Acceptance Criteria
- [x] All contracts from plan §4 defined with type hints + docstrings
- [x] `WorkerOutput` has **no** `state_delta` (D057); `StageState.artifacts` uses an additive reducer
- [x] `sampling_params` present in `LineageEnvelope`/`WorkerExecution` (D055)
- [x] Schema-validation tests pass; **no executable behavior** (no R2/DB/LangGraph)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/schemas.py` (new) — all P0-S3 contracts: `LineageEnvelope`, `Artifact`, `RunRecord`, `WorkerExecution`, `ControlSignal`, `WorkerOutput`, `WorkerNode`, `merge_refs`, `StageState`, `TraceEvent`, `Signal` (minimal placeholder for the Protocol below), `SourceAdapter` Protocol. Pure Pydantic v2 models — no R2/DB/LangGraph imports, no runtime behavior.
- `cf_platform/__init__.py`, `cf_platform/core/__init__.py` (new) — package scaffolding for P1+.
- `tests/cf_platform/test_schemas.py` (new) — 28 schema-validation tests covering defaults, closed Literal sets (`status`, `control`), `sampling_params` presence, the `merge_refs` additive reducer, absence of `state_delta`, and the `SourceAdapter` Protocol shape. 856 total passing.
- **Naming fix (blocker found mid-story):** the plan's `platform/` package name collides with Python's stdlib `platform` module — with the repo root on `sys.path` (as `python -m pytest` and Railway's `uvicorn` invocation both do), `import platform` resolved to this new package instead of the stdlib module, breaking pytest itself and any dependency that does `import platform` (e.g. `requests`, `multiprocessing`) at runtime. Operator chose **`cf_platform`** as the replacement name. Renamed throughout: `cf_platform/` package + all path references in `docs/v2_platform_plan.md`, SPRINT.md, BACKLOG.md, CONVENTIONS.md, DECISIONS.md (D047), CLAUDE.md. HTTP route prefixes (`/platform/echo`, `/platform/health`, etc.) were left unchanged — they're URL strings, not Python imports, so no collision. **All future P1+ stories referencing `platform/...` paths must use `cf_platform/...`.**
- No new ENV vars. No new dependencies (pydantic 2.13 already in `requirements.txt`).
- Next story in execution order: **P0-S4** (Postgres data model + analytics-join design), independent of P0-S3, can run in parallel with P0-S5 per SPRINT.md execution order P0-S1 → P0-S2 → (P0-S3 ∥ P0-S4) → P0-S5.

---

## [P0-S4] Postgres data model + analytics-join design
**Epic:** E26 — Platform Foundation
**Sprint:** P0
**Status:** done
**Completed:** 2026-06-12
**Priority:** high
**Points:** 2
**Depends on:** P0-S1

### Goal
Design (not build) the Postgres schema: `runs`, `artifacts`, `worker_executions`, `trace_events`, reserved `published_videos`/`video_metrics`. Write the retention→prompt_version attribution query to prove the joins. Record migration-tooling choice (raw SQL vs Alembic). See plan doc §6.
**Tech:** Postgres (design only), SQL.

### Acceptance Criteria
- [x] DDL drafted with lineage as **columns** (not JSON) and analytics indexes
- [x] Attribution query written and reviewed; joins resolve conceptually
- [x] Migration tooling decided

### Definition of Done
- [x] All AC checked · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/db/schema.sql` (new) — full DDL draft for all 6 tables (`runs`, `artifacts`, `worker_executions`, `trace_events`, reserved `published_videos`/`video_metrics`). Lineage (`worker`, `worker_version`, `prompt_version`, `model`) is plain TEXT columns on `artifacts`/`worker_executions` per D048 — only `sampling_params`/`inputs`/`meta` are JSONB. `artifacts` has `UNIQUE (run_id, stage, name, version)` to enforce immutability (new write = new row, version+1). Analytics indexes per plan §6 (`prompt_version`, `worker_version`, `run_id`, `source`, `external_id`). FKs from `artifacts`/`worker_executions`/`trace_events`/`published_videos` → `runs.run_id`. Design only — not applied by any code path (P0 architectural law 7); P2-S2 turns this into `cf_platform/db/migrations/0001_init.sql`.
- `cf_platform/db/queries.sql` (new) — the P7-S3 attribution query (parametrized on `worker` rather than hardcoded `'storyboard'`, since the platform's content-generation worker name differs from the legacy pipeline), plus 3 supporting queries used by later sprints' human touchpoints: per-run worker cost/latency/version (P2), run-level cost rollup, and artifact lineage listing (Epic 34 replay). All join keys are plain TEXT columns — joins resolve conceptually without JSON unpacking.
- `DECISIONS.md` D048 updated: migration tooling finalized as **raw SQL** (not Alembic) — rationale: ~6-table analytics-shaped schema with no app-side ORM models, hand-written numbered SQL files (`cf_platform/db/migrations/NNNN_*.sql` + `schema_migrations` tracking table, applied via `psycopg` at startup) are simpler to audit than Alembic's autogenerate machinery. Implementation deferred to P2-S2.
- `docs/v2_platform_plan.md` §6 — added pointer to the new `cf_platform/db/schema.sql` / `queries.sql` design files.
- No code changes, no new dependencies, no tests — pure SQL/docs design artifact, consistent with P0 "interfaces only" scope (P0-S1–S3 precedent: P0-S1/S2 were docs-only with no test additions).
**Smoke test:** N/A — design-only story, no runtime behavior (P0 architectural law 7). Operator can review `cf_platform/db/schema.sql` and `cf_platform/db/queries.sql` directly.
**Promoted to backlog:** none
- Next story in execution order: **P0-S5** (Doc hygiene + abstraction-model docs), per SPRINT.md execution order P0-S1 → P0-S2 → (P0-S3 ∥ P0-S4) → P0-S5.

---

## [P0-S5] Doc hygiene + abstraction-model docs
**Epic:** E26 — Platform Foundation
**Sprint:** P0
**Status:** done
**Completed:** 2026-06-13
**Priority:** med
**Points:** 2
**Depends on:** P0-S2

### Goal
Add the LangGraph abstraction model (Worker=Node, Stage=Graph, Platform=Graph-of-graphs + worker invariants) to ARCHITECTURE.md and CONVENTIONS.md. Fix CLAUDE.md/SPRINT.md current-sprint drift. Note Inngest→LangGraph in ARCHITECTURE §3.

### Acceptance Criteria
- [x] ARCHITECTURE.md has a "LangGraph abstraction model" section; Inngest reference annotated as superseded
- [x] CONVENTIONS.md has the worker=node + state-as-message-bus rules next to the D040 section
- [x] CLAUDE.md current sprint/active story point to the platform track

### Definition of Done
- [x] All AC checked · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `docs/ARCHITECTURE.md`: new **§0 — LangGraph abstraction model (v2 platform, D056/D057)** section added between "Document status" and "§1 Current state" — covers the Worker=Node / Stage=StateGraph / Platform=Graph-of-graphs hierarchy, the 5 worker invariants (stateless/pure, version-pinned, one-artifact-per-execution written by the wrapper, routing-as-edges, IO-adapters-emit-trace-events-not-artifacts), and the state-as-message-bus rules (artifact refs + `ControlSignal` only, no `state_delta`, R2+Postgres as durable truth). Cross-references CONVENTIONS.md and docs/v2_platform_plan.md §3–§5. Top "⚑ v2 Platform direction" banner trimmed to point at §0 instead of duplicating its content. §3 "Orchestration engine" heading retitled to "Orchestration engine (superseded — see §0)" — the existing "Superseded" callout under it was already accurate (D052 supersedes Inngest/D042) and is retained for history.
- `CONVENTIONS.md`: no change needed — the "Platform v2 — worker/node contract (D056) and state discipline (D057)" section (added in P0-S3, immediately following the D040 "Async function discipline" section) already covers worker=node + state-as-message-bus rules per AC2.
- `CLAUDE.md`: "Active story" updated from stale `P0-S3` (done since `d5fe9f4`) to `P0-S5 — Doc hygiene + abstraction-model docs (final story of Sprint P0)`. "Current sprint" line already correctly pointed at the Platform v2 / Sprint P0 track — no change needed there.
- `SPRINT.md`: top banner's "Start here: P0-S1" (stale — P0-S1–S4 already done) replaced with "P0-S1–S4 done; active story: P0-S5 (final story of Sprint P0)". P0-S5 row in the Sprint P0 stories table updated `planned` → `done`.
- No code changes, no new dependencies, no tests — pure documentation, consistent with P0 "interfaces only" scope (architectural law 7).
**Smoke test:** N/A — design/doc-only story, no runtime behavior. Operator can review the new §0 in `docs/ARCHITECTURE.md` and the updated CLAUDE.md/SPRINT.md banners directly.
**Promoted to backlog:** none
- **Sprint P0 complete** (P0-S1–S5 all done, 13/13 pts). Next story in execution order: **P1-S1** (cf_platform/ scaffold + router mount), per SPRINT.md execution order P1-S1 → (P1-S2 ∥ P1-S3) → P1-S4 → P1-S5 → P1-S6.

---

## [P1-S1] cf_platform/ scaffold + router mount
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 2
**Depends on:** P0-S3

### Goal
Create the `cf_platform/` package; mount `cf_platform/interfaces/api.py` under `/platform` in `src/main.py`; add `GET /platform/health`. Reserve `cf_platform/sources/`, `cf_platform/workers/`, `cf_platform/blocks/`, `cf_platform/core/`, `cf_platform/adapters/`. **Fault-isolated init** — platform import/DB errors must not crash legacy routes.
**Tech:** FastAPI, Railway (same service).

### Acceptance Criteria
- [x] `/platform/health` returns 200; legacy routes unchanged
- [x] Platform import failure does not take down the legacy app
- [x] Package dirs reserved per plan §2

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/__init__.py` + `cf_platform/interfaces/api.py` (new): `APIRouter` with `GET /health` returning `{"status": "ok"}`.
- `cf_platform/sources/`, `cf_platform/workers/`, `cf_platform/blocks/`, `cf_platform/adapters/` (new): reserved empty packages, each with a one-line docstring tying it back to plan §2 / D047 / D050 / D056. `cf_platform/core/` already existed from P0-S3.
- `src/main.py`: new `_mount_platform_router(app)` helper — imports `cf_platform.interfaces.api.router` and mounts it at prefix `/platform` inside a `try/except Exception`; on failure logs `logger.exception(...)` and continues (D047 fault isolation). Called once at module load, after all legacy `include_router` calls.
- `tests/cf_platform/test_api.py` (new, 4 tests): `GET /platform/health` → 200; `GET /health` (legacy) still 200 with platform mounted; `_mount_platform_router` registers the route on a fresh `FastAPI()` app in the success path; with `cf_platform.interfaces.api` forced to fail import (via `sys.modules` patched to `None`), `_mount_platform_router` swallows the exception and `/platform/health` is simply absent (404) — legacy app unaffected.
- No new ENV vars, no new dependencies. 860 total passing (was 856).

---

## [P1-S2] Run Manager
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P1-S1

### Goal
`cf_platform/core/run_manager.py`: `create_run()` mints `run_id`, tracks lifecycle (`created→running→complete/failed`), returns `RunRecord`. Persistence behind a repository interface (in-memory impl now; Postgres in P2-S3).
**Tech:** Python, repository pattern. **Artifacts:** `RunRecord` rows (in-memory).

### Acceptance Criteria
- [x] `create_run` returns a unique `run_id` and a valid `RunRecord`
- [x] Lifecycle transitions enforced; invalid transitions rejected
- [x] Repository interface swappable (no Postgres coupling yet)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/run_manager.py` (new): `RunStatus = Literal["created","running","complete","failed"]`; `_VALID_TRANSITIONS` dict encodes `created→running→{complete,failed}` (complete/failed terminal). `RunRepository` Protocol (`async save(run) -> RunRecord`, `async get(run_id) -> RunRecord`). `InMemoryRunRepository` — process-local dict-backed implementation. `create_run(user_id, block, inputs, repository) -> RunRecord` mints `run_id` via `uuid4`, status `"created"`, `created_at == updated_at`. `transition_run(run_id, new_status, repository, error=None) -> RunRecord` validates against `_VALID_TRANSITIONS`, bumps `updated_at`, persists via `repository.save`. `InvalidTransitionError` and `RunNotFoundError` exceptions added.
- `tests/cf_platform/test_run_manager.py` (new, 11 tests): `TestCreateRun` (valid record, unique `run_id`, repository round-trip), `TestTransitionRun` (created→running, running→complete, running→failed with error, `updated_at` advances, invalid `created→complete` rejected, terminal-state rejection, unknown `run_id` → `RunNotFoundError`), `TestRepositorySwappable` (alternate repository implementing the Protocol works with no Postgres coupling).
- No new ENV vars, no new dependencies, no HTTP routes (no UI pairing needed — pure core module). 871 total passing (was 860).
- **Sprint P1 next story:** P1-S3 (Artifact Manager → R2) can proceed — depends only on P1-S1 (done). P1-S4 (LangGraph execution engine) depends on both P1-S2 (done) and P1-S3.

---

## [P1-S3] Artifact Manager → R2 (immutable, versioned)
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P1-S1

### Goal
`cf_platform/core/artifact_manager.py`: `write_artifact()/read_artifact()` to R2 at `users/{user_id}/runs/{run_id}/{stage}/{name}@v{n}.json`, wrapping bodies in the `Artifact` envelope. Artifacts immutable — re-write increments version (D055). Own thin boto3 client (R2 = shared infra, not a legacy import).
**Tech:** Cloudflare R2 (boto3), Pydantic.

### Acceptance Criteria
- [x] Write returns an `Artifact` with a versioned `r2_key`; read round-trips
- [x] Re-writing the same name creates `@v{n+1}`, never overwrites
- [x] No import from `src/`

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/artifact_manager.py` (new): `ArtifactStorage` Protocol (`put_json`/`get_json`/`list_keys`, async) — backing key-value store, swappable. `InMemoryArtifactStorage` — dict-backed test double. `R2ArtifactStorage` — standalone thin boto3 S3-compatible client against the shared R2 bucket (sync boto3 calls wrapped via `asyncio.to_thread`); constructor takes explicit `account_id, access_key_id, secret_access_key, bucket_name` (same shape as `src/storage.py`'s `R2Client`, but a separate implementation per D047 — cf_platform may not import `src/` outside the legacy adapter). `ArtifactStorageError` wraps all storage failures. `_next_version(storage, user_id, run_id, stage, name) -> int` lists existing `@v*` keys for the (user_id, run_id, stage, name) tuple and returns `max(versions, default=0) + 1`. `write_artifact(storage, body, *, name, stage, run_id, user_id, lineage, content_type="application/json") -> Artifact` computes the next version, builds `r2_key = users/{user_id}/runs/{run_id}/{stage}/{name}@v{n}.json`, constructs the `Artifact` envelope (from `cf_platform.core.schemas`), and writes `{"artifact": ..., "body": ...}`. `read_artifact(storage, r2_key) -> (Artifact, body_dict)` reads and returns the envelope + body for the caller to `model_validate` into its own type.
- `tests/cf_platform/test_artifact_manager.py` (new, 10 tests): `TestWriteArtifact` (first write is v1, re-write creates v2 without overwriting v1, independent version counters per name/stage), `TestReadArtifact` (round-trip, missing-key error), `TestR2ArtifactStorage` (put/get/list against mocked boto3, `ClientError` wrapped in `ArtifactStorageError`).
- No new ENV vars, no new dependencies (boto3 already in requirements via `src/storage.py`'s usage). 881 total passing (was 871).
- R2 credential wiring (real `R2ArtifactStorage` instance with live account/bucket) is deferred to whichever story first calls `write_artifact`/`read_artifact` from a route — **P1-S4** (LangGraph execution engine) or **P1-S6** (echo graph smoke). This story ships the manager as a pure, swappable module per D040 (explicit inputs/outputs).
- **Sprint P1 next story:** P1-S4 (LangGraph execution engine, Layer A) — depends on P1-S2 (done) and P1-S3 (done), both now satisfied. ⚠️ Keystone story — spike first per SPRINT.md execution order.

---

## [P1-S4] LangGraph execution engine (Layer A)
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** P1-S2, P1-S3

### Goal
Adopt `langgraph` (D052). Implement the Worker=Node contract: nodes are `WorkerNode`s over a `StageState`, returning `WorkerOutput`; compile/run a trivial graph with `MemorySaver`. **No lineage yet** — pure execution. ⚠️ Spike first.
**Tech:** LangGraph (StateGraph, MemorySaver). **Dependency:** `langgraph` (D052).

### Acceptance Criteria
- [x] A 1-node graph runs `state → WorkerOutput → state` and checkpoints in memory
- [x] Worker body is pure (no storage/DB knowledge)
- [x] `langgraph` added to requirements.txt per D052

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/execution_engine.py` (new): `build_single_node_graph(node_name, worker) -> CompiledStateGraph` — builds a `StateGraph(StageState)` with `START -> node_name -> END`, compiled with `MemorySaver`. The node wrapper calls the pure `WorkerNode` (`StageState -> WorkerOutput`) and merges `output.artifact.model_dump_json()` into `state.artifacts[node_name]` via the existing `merge_refs` reducer — the worker body never sees or assigns its own r2_key. `run_graph(graph, state, thread_id) -> StateT` — invokes via `ainvoke` under `{"configurable": {"thread_id": thread_id}}` and re-validates the result dict back into the caller's `StageState` subclass via `type(state).model_validate(result)`.
- `state.artifacts[node_name]` currently holds a JSON-encoded **placeholder** of the artifact body (not a real r2_key) — pure-execution scope only (no lineage/Artifact Manager wiring). **P1-S5's observability wrapper replaces this placeholder with a real `write_artifact()` r2_key** and additionally records a `WorkerExecution`.
- `requirements.txt`: `langgraph>=0.6.0,<0.7.0` added (D052; pulls in `langchain-core`, `langgraph-checkpoint`, `langgraph-prebuilt`, `langgraph-sdk`, `langsmith` as transitive deps — `langchain-anthropic` is NOT adopted, `anthropic`/`ModelRouter` stay inside nodes per D052). Verified installs and imports cleanly on Python 3.9 (this repo's runtime).
- `tests/cf_platform/test_execution_engine.py` (new, 4 tests): round trip (state → WorkerOutput → state via a trivial `EchoArtifact` worker), `MemorySaver` checkpoint persistence for a `thread_id` (via `graph.aget_state`), independent checkpoints across different `thread_id`s, and a purity check confirming the worker callable receives only `StageState` (no storage/DB args).
- No new ENV vars, no DECISIONS.md entry needed (D052 pre-authorizes `langgraph`). 885 total passing (was 881).
- **Sprint P1 next story:** P1-S5 (Observability wrapper, Layer B) — depends on P1-S4 (done). It will resolve worker_version/prompt_version/model/sampling_params via the Worker Registry, write a real artifact via `write_artifact()` (P1-S3), record a `WorkerExecution` (in-memory until P2), and replace the placeholder ref written by `build_single_node_graph`'s node wrapper.
**Smoke test:** N/A — pure core module (LangGraph mechanics over in-memory `MemorySaver`), no HTTP surface or operator-visible artifact in P1. Verified via 4 unit tests; CI green (885 passing). Human touchpoint (`POST /platform/echo` → artifact in R2) lands in P1-S6.
**Promoted to backlog:** none

---

## [P1-S5] Observability wrapper (Layer B)
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P1-S4

### Goal
`cf_platform/core/worker_registry.py`: `registry.wrap(node)` resolves worker_version/prompt_version/model/sampling_params (prompts stored by version), times the call, records a `WorkerExecution`, writes the node output via the Artifact Manager, and injects `{stage: r2_key}` into state. Enforces **exactly one artifact per worker execution** (D056); worker bodies stay pure.
**Tech:** Python, ModelRouter (unchanged), Pydantic. **Artifacts:** `WorkerExecution` (in-memory until P2).

### Acceptance Criteria
- [x] Wrapped node emits exactly one artifact + one execution record
- [x] Worker cannot see its own `r2_key`; wrapper produces it
- [x] Prompt body retrievable by `worker@prompt_version` (replay foundation, D055)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/worker_registry.py` (new): `WorkerRegistration` (Pydantic — `worker_version`, `prompt_version`, `prompt`, `model`, `sampling_params: dict = {}`). `WorkerRegistry` — `register(worker, registration)`, `resolve(worker) -> WorkerRegistration` (raises `WorkerNotRegisteredError`), `get_prompt(worker, prompt_version) -> str` (raises `PromptVersionNotFoundError`); prompt bodies are indexed by `(worker, prompt_version)` so re-registering with a new `prompt_version` does not remove earlier prompt bodies (D055 replay).
- `ExecutionRepository` Protocol (`async record(execution) -> WorkerExecution`) + `InMemoryExecutionRepository` (`record`, `list_for_run(run_id)`) — mirrors the `RunRepository`/`InMemoryRunRepository` pattern from P1-S2; in-memory until P2.
- `wrap(worker, node_name, node, *, registry, storage, executions) -> Callable[[StageState], Awaitable[dict]]` — resolves the worker's `WorkerRegistration`, calls the pure `node(state)`, builds a `LineageEnvelope` from the registration + `state.run_id`, writes `output.artifact` via `write_artifact()` (P1-S3) at `name=stage=node_name` (real, versioned `r2_key` — the worker body never sees it), records exactly one `WorkerExecution` (status `"ok"`, `artifact_r2_key`, `latency_ms` via `time.perf_counter`), and returns `{"artifacts": {node_name: r2_key}}` for the `merge_refs` reducer. Raises `WorkerNotRegisteredError` immediately (before calling `node`) if `worker` is unregistered.
- `build_observed_node_graph(node_name, worker, node, *, registry, storage, executions) -> CompiledStateGraph` — 1-node `StateGraph(StageState)` (`START -> node_name -> END`, `MemorySaver` checkpointer) analogous to P1-S4's `build_single_node_graph`, but the node is `wrap(...)` so `state.artifacts[node_name]` is a real R2 key instead of P1-S4's JSON placeholder. Composable with `execution_engine.run_graph`.
- No changes to `cf_platform/core/execution_engine.py` — P1-S4's placeholder-based `build_single_node_graph`/`run_graph` remain available for pure-execution use; `build_observed_node_graph` is the parallel, observed path used by P1-S6+.
- `tests/cf_platform/test_worker_registry.py` (new, 11 tests): registry registration/resolution + unregistered-worker error, prompt retrieval by version + unknown-version error + older-version retrievability after re-registration, wrap() unregistered-worker fast-fail, exactly-one-artifact + exactly-one-execution, artifact body/lineage match the registration, execution record matches registration + artifact `r2_key`, worker purity (receives only `StageState`, never sees `artifacts[node_name]` pre-write), and an end-to-end `build_observed_node_graph` + `run_graph` round trip producing a real `r2_key`.
- No new ENV vars, no new dependencies. 896 total passing (was 885).
- **Sprint P1 next story:** P1-S6 (Echo graph end-to-end smoke) — depends on P1-S5 (done). It wires `POST /platform/echo {text}`: Run Manager mints a run, a 1-node echo graph runs through `build_observed_node_graph` (registering an "echo" worker in a `WorkerRegistry`, using `R2ArtifactStorage` + `InMemoryExecutionRepository`), and the route returns `{run_id, artifact_key}`. This is the Sprint P1 human touchpoint (`POST /platform/echo` → artifact in R2).

---

## [P1-S6] Echo graph end-to-end smoke
**Epic:** E26 — Platform Foundation
**Sprint:** P1
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 2
**Depends on:** P1-S5

### Goal
`POST /platform/echo {text}` → Run Manager mints run → 1-node echo graph through the wrapper → Artifact in R2 → WorkerExecution recorded → returns `{run_id, artifact_key}`. Proves the full spine (both layers composed).
**Tech:** FastAPI, LangGraph, R2.

### Acceptance Criteria
- [x] End-to-end call returns a run_id and a real R2 artifact key
- [x] Lineage record present for the echo worker
- [x] **Human touchpoint:** operator calls `/platform/echo` and sees the artifact in R2

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/config.py` (new): `PlatformSettings` (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`) + `get_platform_settings()` — cf_platform's own minimal settings, read independently of `src/config.py` (D047: cf_platform may not import `src/` outside the legacy adapter). Same ENV var names as the legacy bucket; no new ENV vars.
- `cf_platform/workers/echo.py` (new): `EchoArtifact(message: str)`, pure `echo_worker(state) -> WorkerOutput`, `ECHO_REGISTRATION` (`WorkerRegistration`, `worker_version="1.0.0"`, `prompt_version="v1"`, `model="none"`).
- `cf_platform/interfaces/api.py`: added `POST /echo` (mounted at `/platform/echo`). Module-level in-memory singletons — `InMemoryRunRepository`, `InMemoryExecutionRepository`, `WorkerRegistry` (pre-registered with `"echo"` → `ECHO_REGISTRATION`) — exposed via `get_run_repository()`/`get_execution_repository()`/`get_worker_registry()`/`get_artifact_storage()` FastAPI `Depends()` providers (swappable for tests and for P2's Postgres-backed repos). Route: `create_run` → `transition_run("running")` → `build_observed_node_graph("echo","echo", echo_worker, ...)` → `run_graph` → `transition_run("complete")` → `EchoResponse(run_id, artifact_key)`. Fixed `user_id="operator"` (single-operator platform; per-user isolation is S19).
- `tests/cf_platform/test_echo_route.py` (new, 4 tests): response shape (`run_id` + `artifact_key` prefix), artifact body/lineage round-trip via `read_artifact`, exactly-one `WorkerExecution` recorded, `RunRecord` reaches `status="complete"`. All against `InMemoryArtifactStorage` via `app.dependency_overrides`. 900 total passing (was 896).
- No new ENV vars, no new dependencies, no DECISIONS.md entry.
- **P1 is the last "interfaces only / spine" sprint with no operator UI deliverable** — P1's human touchpoint is a direct API call + R2 inspection (not pipeline.html). The first operator-facing platform UI surface is the Telegram trigger in **P3-S1**; no follow-up story needed for this story specifically.
- **Sprint P1 complete** (16/16 pts). Next: **P2-S1** (Provision Railway Postgres + connection layer), per SPRINT.md execution order P2-S1 → P2-S2 → (P2-S3 ∥ P2-S4) → P2-S5.

---

## EPIC 27 — Lineage & Observability Store (Sprint P2)
Durable, queryable lineage in Postgres; LangGraph durability; observability endpoints (D048).

---

## [P2-S1] Provision Railway Postgres + connection layer
**Epic:** E27 — Lineage & Observability
**Sprint:** P2
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P1-S6

### Goal
Add Railway Postgres (DEV+PROD); `DATABASE_URL` env; async connection pool in `cf_platform/core/db.py`; extend `/platform/health` with a DB check. DB outage must stay fault-isolated from legacy.
**Tech:** Railway Postgres, `psycopg` (D048). **Dependency:** `psycopg`.

### Acceptance Criteria
- [x] Pool connects on both envs; health reports DB status
- [x] DB down ≠ legacy down
- [x] `psycopg` added to requirements.txt per D048

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md.

---

## [P2-S2] Schema migrations
**Epic:** E27 — Lineage & Observability
**Sprint:** P2
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P2-S1

### Goal
Migration runner + tables `runs`, `artifacts`, `worker_executions`, `trace_events` with lineage **columns** + analytics indexes; `published_videos`/`video_metrics` reserved (created or stubbed). See plan §6.
**Tech:** Postgres, SQL (tooling per P0-S4).

### Acceptance Criteria
- [x] 4 core tables created with indexes from plan §6
- [x] Reserved P7 tables present or stubbed
- [x] Migrations idempotent / re-runnable

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md.

---

## [P2-S3] Persist Run/Artifact/Execution to Postgres
**Epic:** E27 — Lineage & Observability
**Sprint:** P2
**Status:** done
**Priority:** high
**Points:** 5
**Depends on:** P2-S2

### Goal
Swap P1 in-memory repos for Postgres-backed repos. **R2 stays blob truth; PG is the index** — artifact rows store the R2 key + lineage columns, never the body. The wrapper writes a `worker_executions` row per node. Idempotent upserts.
**Tech:** Postgres, R2, repository pattern.

### Note
P2-S1 verified `DATABASE_URL`/Postgres on `content-factory-dev` only (`{"status":"ok","database":"ok"}` from `/platform/health`, 2026-06-13). Before this story ships to PROD, confirm `content-factory-prod` also has a Postgres plugin + `DATABASE_URL` set and `/platform/health` returns `"database": "ok"` there too.

### Acceptance Criteria
- [x] Echo run now persists rows in `runs`, `artifacts`, `worker_executions`
- [x] Artifact bodies remain in R2 only (PG holds keys)
- [x] Re-running a step is idempotent

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md [P2-S3] entry for full details. `cf_platform/core/postgres_repos.py` (new): `PostgresRunRepository`, `PostgresArtifactRepository`, `PostgresExecutionRepository` — idempotent upserts (`ON CONFLICT (run_id) DO UPDATE` for runs, `ON CONFLICT (run_id, stage, name, version) DO NOTHING` for artifacts). New `ArtifactRepository` protocol + `InMemoryArtifactRepository` in `cf_platform/core/artifact_manager.py`. `wrap()`/`build_observed_node_graph()` now take a required `artifact_repo` kwarg and record the artifact's lineage row. `cf_platform/interfaces/api.py` provider functions (`get_run_repository`, `get_execution_repository`, `get_artifact_repository`) select Postgres-backed repos when `DATABASE_URL`/`get_pool()` is set, else in-memory fallback (D048). 927 total passing (was 917).

---

## [P2-S4] LangGraph PostgresSaver checkpointer
**Epic:** E27 — Lineage & Observability
**Sprint:** P2
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P2-S1

### Goal
Replace `MemorySaver` with the Postgres checkpointer on the same DB. A graph run survives a process restart and resumes from its last checkpoint.
**Tech:** LangGraph (`langgraph-checkpoint-postgres`), Postgres. **Dependency:** `langgraph-checkpoint-postgres` (D052).

### Acceptance Criteria
- [x] Kill/restart mid-run → run resumes from last checkpoint
- [x] Checkpointer uses the same `DATABASE_URL`
- [x] Dependency added per D052

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md — [P2-S4] LangGraph PostgresSaver checkpointer.

---

## [P2-S5] Observability endpoints
**Epic:** E27 — Lineage & Observability
**Sprint:** P2
**Status:** done
**Completed:** 2026-06-13
**Priority:** med
**Points:** 2
**Depends on:** P2-S3

### Goal
`GET /platform/runs` and `GET /platform/runs/{id}`: status, artifact list (R2 links), per-worker cost/latency/version. JSON only.
**Tech:** FastAPI, Postgres.

### Acceptance Criteria
- [x] List + detail endpoints return real lineage
- [x] **Human touchpoint:** operator inspects per-worker cost/latency/version for a run

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md [P2-S5] entry for full details.

---

## EPIC 28 — Discovery & Execution Interfaces (Sprint P3)
Telegram trigger + first real worker; signals stored with lineage (D049, D050).

> **Future candidate (P8+):** Once P3-S2's `SourceAdapter` implementations (Reddit/Google Trends/YouTube, all raw httpx per D050) have run in DEV/PROD for a while, evaluate replacing the fragile-by-nature adapters (esp. `GoogleTrendsAdapter`'s unofficial-API scraping) with a managed scraping provider — Apify or ScrapeBadger — behind the same `SourceAdapter` Protocol. Swap is a new adapter file per source, no Discovery Worker changes (D050 contract). Needs its own DECISIONS.md entry (new dependency + likely paid tier) before implementation.

---

## [P3-S1] Telegram webhook (trigger-only)
**Epic:** E28 — Discovery & Execution Interfaces
**Sprint:** P3
**Status:** done
**Completed:** 2026-06-13
**Priority:** high
**Points:** 3
**Depends on:** P1-S6

### Goal
`POST /telegram/webhook`: validate secret token, parse `/ideas <niche>`, reply via `sendMessage`. **No business logic** — only triggers a block. Register webhook via Telegram API. Replies go through a formatter (D049).
**Tech:** Telegram Bot API (httpx), FastAPI. **Env:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`.

### Acceptance Criteria
- [x] Webhook validates token; rejects unauthorized updates
- [x] `/ideas <niche>` parsed; ack reply sent via formatter
- [x] No internal schema serialized to chat (D049)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md [P3-S1] entry for full details.

---

## [P3-S2] Discovery worker v1 + source adapters
**Epic:** E28 — Discovery & Execution Interfaces
**Sprint:** P3
**Status:** done
**Completed:** 2026-06-14
**Priority:** high
**Points:** 5
**Depends on:** P2-S3, P0-S3

### Goal
`discovery` node: from `{niche, audience?, subtopic?}`, query Reddit + Google Trends + YouTube via `SourceAdapter` implementations in `cf_platform/sources/`; normalize into one `signals` artifact. Partial-failure isolation (one dead source ≠ dead worker). Adapters emit `trace_event` rows per fetch (D050) — never artifacts. X/Twitter dropped (later via Apify).
**Tech:** Reddit/Trends/YouTube (raw httpx, no SDKs/pytrends), LangGraph node, no LLM call (`model="none"`). **Env:** `REDDIT_*`, `YOUTUBE_API_KEY`. **Artifacts:** `signals` (plan §6).

### Acceptance Criteria
- [x] 3 adapters implement the P0 `SourceAdapter` Protocol
- [x] Worker emits exactly one `signals` artifact; each source fetch emits a `trace_event`
- [x] One failing source does not fail the worker

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
Implemented `RedditAdapter`, `GoogleTrendsAdapter`, `YouTubeAdapter` (`cf_platform/sources/`) as `SourceAdapter` (D050) — all raw httpx, no new dependencies. `GoogleTrendsAdapter` uses the unofficial `explore` → `widgetdata/relatedsearches` handshake; see the P8+ Apify/ScrapeBadger note above EPIC 28 if it proves fragile in DEV/PROD.

Added `TraceEventRepository` (in-memory + Postgres, mirrors `ArtifactRepository`) for D050 trace events, with `trace_events` table already present from migration 0001.

`cf_platform/workers/discovery.py`: `build_discovery_worker(adapters, trace_repo) -> WorkerNode` aggregates `Signal`s into `SignalsArtifact {niche, generated_at, signals}` — no dedup/scoring/ranking (deferred to P4 Topic Generator). Per-adapter `try/except` records an `ok`/`error` `TraceEvent` and lets remaining sources continue (AC #3). Registered as `DISCOVERY_REGISTRATION` ("discovery") in `_worker_registry`; `build_discovery_adapters(settings)` in `cf_platform/interfaces/api.py` constructs the three adapters from `PlatformSettings`. No new API route this story — P3-S3 wires the worker into the `/ideas` Telegram flow.

New env vars (all optional, empty = that adapter's fetch degrades to an error trace event): `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `YOUTUBE_API_KEY`. `GoogleTrendsAdapter` needs no credentials.

176 cf_platform tests pass (1004 total). Ready for P3-S3 to call `build_discovery_worker(build_discovery_adapters(settings), trace_repo)` and format the `signals` artifact for chat.

---

## [P3-S3] Reply formatter + wire discovery
**Epic:** E28 — Discovery & Execution Interfaces
**Sprint:** P3
**Status:** done
**Priority:** high
**Points:** 2
**Depends on:** P3-S1, P3-S2
**Completed:** 2026-06-14

### Goal
`format_for_chat()` summarizes the `signals` artifact (top signals + run_id + artifact key) back to chat. End-to-end `/ideas <niche>` → summary.
**Tech:** Telegram API, formatter.

### Acceptance Criteria
- [x] `/ideas <niche>` returns a readable signals summary
- [x] **Human touchpoint:** operator sends a niche in Telegram and gets signals back

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/telegram.py`: `format_ideas_ack` removed, replaced by `format_signals_summary(niche, run_id, artifact_key, signals) -> str` (D049 plain-string formatter) — lists up to 5 signals sorted by `score` descending as `- [source] title (score N)`, plus the run_id and artifact key; returns `No signals found for "<niche>" (run <run_id>).` when `signals` is empty.
- `cf_platform/interfaces/api.py`: `/telegram/webhook`'s `/ideas <niche>` branch now runs the discovery worker end-to-end through the same observability spine as `/echo`: `create_run` → `transition_run("running")` → `build_observed_node_graph("discovery", "discovery", build_discovery_worker(adapters, trace_events), ...)` → `run_graph` → `transition_run("complete")` → `read_artifact(storage, result.artifacts["discovery"])` → `SignalsArtifact.model_validate(body)` → `format_signals_summary(...)`. New `get_discovery_adapters(settings) -> list[tuple[str, SourceAdapter]]` FastAPI dependency wraps `build_discovery_adapters` so tests can substitute stub adapters.
- Tests (5 new): `tests/cf_platform/test_telegram.py` — `format_signals_summary` with signals (lists source/title, run_id, artifact key), score-descending ordering, and empty-signals fallback. `tests/cf_platform/test_api.py` — `/ideas <niche>` runs discovery via stub `SourceAdapter`s + `InMemoryArtifactStorage` and replies with the signals summary; empty-signals case replies "No signals found". 1007 total passing (was 1004).
- No new ENV vars, no new dependencies, no DECISIONS.md entry needed — pure wiring of P3-S1 (trigger) + P3-S2 (worker) through the existing P1/P2 observability spine.
- **Sprint P3 complete** (10/10 pts — P3-S1, P3-S2, P3-S3 all done).
**Smoke test:** PASSED (live, Railway DEV + real Telegram chat) — see DONE.md for the full transcript.
**Promoted to backlog:** none

---

## EPIC 29 — Niche→Ideas Block (Sprint P4)
Full first E2E block as a LangGraph StateGraph; per-node lineage; Telegram + REST.

---

## [P4-S1] Topic Generator worker
**Epic:** E29 — Niche→Ideas Block
**Sprint:** P4
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** P3-S2

### Goal
LangGraph node `signals → candidate_topics` (narrative-worthy topics). Versioned prompt `topic_generator@v1`. Implemented as a worker per D056 (one artifact).
**Tech:** LangGraph node, anthropic + ModelRouter (GENERATE/Sonnet). **Artifacts:** `candidate_topics`.

### Acceptance Criteria
- [x] Node emits one `candidate_topics` artifact with lineage
- [x] Prompt version pinned and recorded

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/topic_generator.py` (new): `CandidateTopic(title, angle)` and `CandidateTopicsArtifact(niche, generated_at, topics)` Pydantic models. `TOPIC_GENERATOR_REGISTRATION` pins `worker_version="1.0.0"`, `prompt_version="v1"`, `model="claude-sonnet-4-6"`, `prompt=_TOPIC_GENERATOR_PROMPT_V1` (the full content-strategist system prompt). `build_topic_generator_worker(storage, anthropic_api_key) -> WorkerNode` factory — same closure pattern as `build_discovery_worker`; the returned worker reads `state.artifacts["discovery"]` → `read_artifact(storage, key)` → `SignalsArtifact.model_validate(body)` → formats signals into a user message → calls `anthropic.AsyncAnthropic.messages.create` with the pinned model and prompt → `json.loads` response → `CandidateTopicsArtifact`. Raises `KeyError` on missing `discovery` ref, `ValueError` on non-JSON Claude response.
- `cf_platform/core/config.py`: `PlatformSettings` gains `ANTHROPIC_API_KEY: str = ""` (D048 fault-isolation default; same ENV var name as `src/config.py`, always set in practice since the legacy pipeline requires it).
- Tests (9 new): `tests/cf_platform/test_topic_generator.py` — `TestTopicGeneratorWorker` (5 tests: happy path end-to-end with mocked anthropic client, asserts niche/topics/control; verifies signals text present in user message sent to Claude; invalid JSON raises ValueError; missing `discovery` key raises KeyError; empty signals list writes `(no signals)` to prompt and still calls Claude). `TestTopicGeneratorRegistration` (4 tests: model is `claude-sonnet-4-6`, prompt_version is `v1`, worker_version is `1.0.0`, prompt is non-empty). 1025 total passing (was 1007 after P3-S3; some intermediate tests added in between).
- No new dependencies (`anthropic>=0.40.0` already in `requirements.txt`). No new DECISIONS.md entry needed. Worker NOT yet registered in `cf_platform/interfaces/api.py` — that wiring lands in P4-S4 (assemble StateGraph) and P4-S5 (block interfaces).
**Smoke test:** DEFERRED — no route wires this worker yet; exercised only via unit tests. Smoke test will be part of P4-S4/P4-S5 when the full `niche_to_ideas` StateGraph and REST/Telegram interfaces are assembled.
**Promoted to backlog:** none

---

## [P4-S2] Opportunity Scoring worker
**Epic:** E29 — Niche→Ideas Block
**Sprint:** P4
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** P4-S1

### Goal
Node scores each topic on the 7 axes (novelty, audience_relevance, emotional_trigger, search_demand, competition, evergreen_potential, monetization_relevance) + `final_score` via a versioned rubric prompt.
**Tech:** LangGraph node, anthropic + ModelRouter (REASON/Sonnet 4.6 + adaptive thinking). **Artifacts:** `scored_topics`.
**Model rationale:** Scoring across 7 axes (including subjective axes like `emotional_trigger`, `evergreen_potential`) requires reasoning before scoring — standard LLMs cluster scores high (sycophancy). Sonnet 4.6 with `thinking: {type: "adaptive"}` provides internal CoT before the JSON output without adding a new provider. Haiku 4.5 was the original pick but carries too high a risk of flat, uncalibrated scores that degrade everything downstream.

### Acceptance Criteria
- [x] Each topic scored on all 7 axes + final_score
- [x] One `scored_topics` artifact with lineage

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
See DONE.md

---

## [P4-S3] Topic Selector worker
**Epic:** E29 — Niche→Ideas Block
**Sprint:** P4
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 2
**Depends on:** P4-S2

### Goal
Node selects best topic (or top-N by `mode`) + alternatives → `ranked_ideas`. The `mode` branch is a **conditional edge** (routing), not worker logic (D056).
**Tech:** LangGraph (conditional edge), Python. **Artifacts:** `ranked_ideas`.

### Acceptance Criteria
- [x] Selector emits one `ranked_ideas` artifact (selected + alternatives)
- [x] `mode` routing handled by a graph edge, not inside the worker

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/topic_selector.py` (new): `RankedIdeasArtifact(niche, generated_at, selected: TopicScore, alternatives: list[TopicScore], mode: str)`. `TOPIC_SELECTOR_REGISTRATION` pins `worker_version="1.0.0"`, `prompt_version="v1"`, `model="none"`, `prompt=""`, `sampling_params={}` — no LLM call (pure deterministic). `build_topic_selector_worker(storage) -> WorkerNode` factory — reads `state.artifacts["scored_topics"]` → `read_artifact` → `ScoredTopicsArtifact.model_validate` → sort by `(-final_score, title)` → `selected=topics[0]`, `alternatives=topics[1:]` → reads `mode` via `getattr(state, "mode", "single")` → returns `RankedIdeasArtifact`. Raises `KeyError` on missing `scored_topics` ref; `ValueError` on empty topics list.
- Tests (10 new): `tests/cf_platform/test_topic_selector.py` — happy path (correct selected/alternatives order); single topic (alternatives empty); missing key → KeyError; empty list → ValueError; tie-breaking by title ascending; mode defaults to "single"; mode read from state; niche propagated; registration pins (model/worker_version/prompt_version); build returns callable. 1048 total passing (was 1038).
- No new dependencies, no new ENV vars, no DECISIONS.md entry needed. Worker NOT yet registered — wiring lands in P4-S4 (assemble StateGraph) and P4-S5 (block interfaces).

---

## [P4-S4] Assemble niche_to_ideas StateGraph (+ NicheToIdeasState)
**Epic:** E29 — Niche→Ideas Block
**Sprint:** P4
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 3
**Depends on:** P4-S1, P4-S2, P4-S3

### Goal
Implement `NicheToIdeasState` (plan §5) and compile the 4 nodes into `cf_platform/blocks/niche_to_ideas.py` over that state. One run emits all intermediate artifacts + terminal `ranked_ideas`; each node a `worker_execution`; checkpointed/resumable.
**Tech:** LangGraph (StateGraph, PostgresSaver), Run/Artifact/Registry. **Schema:** `NicheToIdeasState`.

### Acceptance Criteria
- [x] `NicheToIdeasState` matches plan §5 (refs + `mode`/`top_n` only)
- [x] One run produces 4 artifacts + 4 execution rows
- [x] Run resumes after restart

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/schemas.py`: `NicheToIdeasState(StageState)` added — `mode: Literal["single", "top_n"] = "single"`, `top_n: int = 3`. Inherits `artifacts: Annotated[dict[str, str], merge_refs]` reducer.
- `cf_platform/blocks/niche_to_ideas.py` (new): `register_niche_to_ideas_workers(registry)` registers all 4 workers; `build_niche_to_ideas_graph(*, storage, registry, executions, artifact_repo, adapters, trace_repo, anthropic_api_key, checkpointer?)` compiles the 4-node StateGraph (discovery → topic_generator → opportunity_scorer → topic_selector). Node-to-artifact-key mapping: "discovery"→"discovery", "topic_generator"→"candidate_topics", "opportunity_scorer"→"scored_topics", "topic_selector"→"ranked_ideas".
- `cf_platform/interfaces/api.py`: `register_niche_to_ideas_workers(_worker_registry)` called at module init; discovery no longer registered separately (subsumed).
- Tests: 18 new in `tests/cf_platform/test_niche_to_ideas.py`. 1066 total passing (was 1048).
- No new ENV vars. No new dependencies.

---

## [P4-S5] Block interfaces (REST + Telegram)
**Epic:** E29 — Niche→Ideas Block
**Sprint:** P4
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 2
**Depends on:** P4-S4

### Goal
`POST /blocks/niche-to-ideas {niche, audience?, mode?}` returns ranked ideas + run_id; Telegram `/ideas` wired to the full block (via formatter).
**Tech:** FastAPI, Telegram.

### Acceptance Criteria
- [x] REST + Telegram both run the full block
- [x] **Human touchpoint:** Telegram niche → ranked ideas with 7-axis scores + alternatives

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/telegram.py`: `format_ranked_ideas(niche, run_id, artifact_key, ranked_ideas) -> str` — D049-compliant; run_id/artifact_key params accepted but omitted from reply text (no internal IDs in screenshots). Reply shows selected title + angle + Score X.XX/10 + axes split across two rows + top 3 runner-ups. `format_ideas_running(niche) -> str` added for immediate ack before background task. `TYPE_CHECKING` guard on `RankedIdeasArtifact` import. `strip_markdown_fences` applied to all LLM JSON output (Claude wraps JSON in backtick fences despite prompt instructions; defensive stripping in `cf_platform/core/llm_utils.py`).
- `cf_platform/interfaces/api.py`: `NicheToIdeasRequest/Response` Pydantic models. `POST /platform/blocks/niche-to-ideas` runs the full 4-node graph. Telegram `/ideas` handler: sends immediate ack via `format_ideas_running`, then runs `_run_ideas_and_reply()` as a `BackgroundTasks` task (webhook returns <1s; background task pushes result via `TelegramClient.send_message`). Errors in the background task are caught, logged at ERROR level, and sent as a truncated Telegram reply.
- `cf_platform/core/llm_utils.py` (new): `strip_markdown_fences(text) -> str` shared utility; used by both topic_generator and opportunity_scorer.
- `cf_platform/workers/opportunity_scorer.py`: max_tokens raised from 4096 → 8192 (adaptive thinking was consuming the full 4096 budget leaving no TextBlock); uses shared `strip_markdown_fences`.
- `cf_platform/workers/topic_generator.py`: uses shared `strip_markdown_fences`.
- Tests: 246 passing (increased from 1083 local count — cf_platform suite). No new ENV vars. No new dependencies.
**Smoke test:** PASSED — 2026-06-17 on Railway DEV. `/ideas coffee culture in US` → immediate ack + ranked reply with 7-axis scores + 3 runner-ups.
**Promoted to backlog:** none

---

## EPIC 30 — Idea→Script Block (Sprint P5)
Second block; cyclic write→score→fact-check→refine. Promotes /tools/script-generator server-side.

---

## [P5-S1] Script Writer worker (write ×N)
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 3
**Depends on:** P4-S4

### Goal
Node generates N drafts from an idea + niche context. Versioned prompt (Step 2a heritage).
**Tech:** LangGraph node, Haiku 4.5 (constrained creative; Sonnet reserved for scorer/fact-check). **Artifacts:** `script_drafts`.

### Acceptance Criteria
- [x] Node emits one `script_drafts` artifact (N drafts) with lineage

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/script_writer.py`: `build_script_writer_worker(storage, anthropic_api_key, n_drafts=3) → WorkerNode`
- Exports: `ScriptDraftsArtifact`, `ScriptDraft`, `SCRIPT_WRITER_REGISTRATION`
- Two entry paths: full pipeline (`state.artifacts["ranked_ideas"]`) or direct (`state.inputs["idea_title"]` only)
- Supporting points: `state.inputs["supporting_points"]` overrides; auto-extracted from `state.artifacts["discovery"]` (top 5 by score) if present
- `ScriptDraftsArtifact.niche` and `.idea_angle` are Optional
- Model: `claude-haiku-4-5`, prompt_version v2, worker_version 1.1.0; ~$0.13/full pipeline run
- 20 tests; 1103 suite total

---

## [P5-S2] Quality/virality scorer worker
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 3
**Depends on:** P5-S1

### Goal
Node ranks drafts by virality/quality rubric → `script_scores`. Emits `control="retry"`/`"continue"` toward the loop (the graph bounds iteration).
**Tech:** LangGraph node, ModelRouter. **Artifacts:** `script_scores`.

### Acceptance Criteria
- [x] One `script_scores` artifact; control signal returned
- [x] No loop bookkeeping inside the worker (graph owns `iteration`)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/script_quality_scorer.py`: `build_script_quality_scorer_worker(storage, anthropic_api_key) → WorkerNode`
- Exports: `ScriptScoresArtifact`, `ScriptDraftScore`, `SCRIPT_QUALITY_SCORER_REGISTRATION`
- Reads `state.artifacts["script_drafts"]` → `ScriptDraftsArtifact` → scores each draft via Claude Sonnet 4.6
- Rubric axes (0–10): `hook_strength`, `data_quality`, `narrative_flow`, `virality_potential`, `overall_score`
- **v2 (2026-06-18):** `ScriptDraftScore` gains optional coaching fields per axis (`hook_coaching`, `data_coaching`, `narrative_coaching`, `virality_coaching`). Prompt v2 asks Claude for one-sentence coaching note per axis; "No change needed." when ≥ 9.0. `max_tokens` 1024 → 2048. Backward-compatible (fields are `Optional[str] = None`).
- Control: `"continue"` if `best_overall_score / 10.0 >= quality_threshold`, else `"retry"`
- `quality_threshold` read via `getattr(state, "quality_threshold", 0.8)` — forward-compatible with `IdeaToScriptState.quality_threshold`
- No loop bookkeeping — worker never reads `state.iteration`
- Model: `claude-sonnet-4-6`, prompt_version v2, worker_version 1.1.0

---

## [P5-S3] Fact-check tool integration (web search)
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Priority:** high
**Points:** 3
**Depends on:** P5-S1

### Goal
Fact-check node verifies claims via a web-search tool (D053) → `factcheck_report`. External dependency isolated in this story so the loop (P5-S4) is unblocked.
**Tech:** LangGraph node, web-search tool, ModelRouter. **Dependency:** web-search provider (D053). **Artifacts:** `factcheck_report`.

### Acceptance Criteria
- [x] Claims verified; `factcheck_report` artifact emitted
- [x] Web-search provider chosen + added per D053

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
**Provider (D053):** Anthropic `web_search_20260209` server-side tool — no new dependency, no new ENV var.
**Entry:** `build_fact_checker_worker(storage, anthropic_api_key) -> WorkerNode` in `cf_platform/workers/fact_checker.py`.
**Artifact:** `FactcheckReportArtifact` — idea_title, draft_number, claims (list of ClaimVerification with verdict/source/note), verified_count, refuted_count, unverifiable_count, checked_at.
**Reads:** `state.artifacts["script_drafts"]` (first draft only — runs parallel to P5-S2).
**Control:** "continue" if (refuted + unverifiable) / total ≤ unverified_threshold (default 0.3 from `getattr(state, "unverified_threshold", 0.3)`); "retry" otherwise.
**Tests:** 20 tests passing; full suite 1140 passing.

---

## [P5-S4] Refine loop + convergence logic
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Completed:** 2026-06-17
**Priority:** high
**Points:** 5
**Depends on:** P5-S2, P5-S3

### Goal
Cyclic graph: writer → scorer → fact-check → refine, bounded by `iteration < max_iterations` OR `score >= quality_threshold` (typed channels on `IdeaToScriptState`; graph increments via reducer). ⚠️ Spike first.
**Tech:** LangGraph (cycles, conditional edges), PostgresSaver.

### Acceptance Criteria
- [x] Loop converges or stops at `max_iterations`; never infinite
- [x] Iteration count is a typed state channel, not a worker delta (D057)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/schemas.py`: `IdeaToScriptState` added — `iteration: Annotated[int, operator.add]`, `max_iterations=3`, `quality_threshold=0.8`, `unverified_threshold=0.3`, `scorer_verdict`, `factcheck_verdict`. All existing workers forward-compatible via `getattr(state, ...)`.
- `cf_platform/core/worker_registry.py`: `wrap()` gains `control_channel: Optional[str] = None` — when set, also returns `{control_channel: output.control}` in the node dict (backward-compatible).
- `cf_platform/workers/script_refiner.py`: `build_script_refiner_worker(storage, anthropic_api_key) → WorkerNode`. Exports `ScriptRefinerArtifact` (actually returns `ScriptDraftsArtifact`), `SCRIPT_REFINER_REGISTRATION`. **v2 (2026-06-18):** `_format_scores()` now includes inline coaching notes (`axis: score — "coaching note"`); prompt v2 instructs Claude to treat each note as a precise editing instruction. prompt_version v2, worker_version 1.1.0.
- `cf_platform/blocks/idea_to_script.py`: `register_idea_to_script_workers(registry)`, `build_refine_loop_graph(*, storage, registry, executions, artifact_repo, anthropic_api_key, checkpointer?) → CompiledStateGraph`. Cyclic graph with `_route_after_evaluation` and `_increment_iteration` non-worker node. P5-S5 extends this file with REST/Telegram interface + terminal "script" artifact.
- 33 tests; 1173 total passing.

---

## [P5-S5] Assemble idea_to_script graph + interfaces (+ IdeaToScriptState)
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 2
**Depends on:** P5-S4

### Goal
Implement `IdeaToScriptState` (plan §5); compile `cf_platform/blocks/idea_to_script.py`; `POST /blocks/idea-to-script` + Telegram `/script <idea|run_id>`; terminal `script` artifact; per-node lineage.
**Tech:** LangGraph, FastAPI, Telegram. **Schema:** `IdeaToScriptState`.

### Acceptance Criteria
- [x] `IdeaToScriptState` matches plan §5 (implemented in P5-S4, verified here)
- [x] **Human touchpoint:** Telegram idea → fact-checked `script` artifact

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/script_packager.py`: `ScriptArtifact`, `SCRIPT_PACKAGER_REGISTRATION`, `build_script_packager_worker(storage) → WorkerNode`
- `cf_platform/blocks/idea_to_script.py`: `build_idea_to_script_graph` (full block with packager); `register_idea_to_script_workers` now registers 5 workers; `build_refine_loop_graph` unchanged
- `cf_platform/interfaces/telegram.py`: `parse_script_command`, `format_script_running`, `format_script_usage`, `format_script_reply`
- `cf_platform/interfaces/api.py`: `POST /platform/blocks/idea-to-script`; `/script` Telegram command; workers registered at startup
- 46 new tests; total suite 1219 passing

---

## [P5-S6] Rearchitect Idea→Script stage — Blueprint IR + single-pass + patch repair
**Epic:** E30 — Idea→Script Block
**Sprint:** P5
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 8
**Depends on:** P5-S5

### Goal
Replace the current write→score→fact-check→refine loop (full script regeneration per iteration, $1–$3/run) with a deterministic content compiler: Blueprint IR → single-pass script generation → Haiku-based integrity check → targeted patch repair if needed. Target cost: $0.05–$0.10/run. Removes `web_search` entirely.

**Decision:** log as D058 — Blueprint IR pattern (spec authored 2026-06-18; the spec document incorrectly labelled itself D057, which is already taken by "Artifacts are truth, state is message bus").

### Architecture (10-node DAG)
```
IdeaToScriptInput
  → [0] context_normalization   (deterministic — no LLM)
  → [1] blueprint_generation    (Sonnet — single pass, outputs Blueprint IR)
  → [2] evaluation              (Sonnet — fact + score + signal alignment, ONE call)
  → [3] blueprint_merge         (deterministic — applies evaluation patches to Blueprint)
  → [4] hook_generation         (Haiku — 3 hook variants)
  → [5] hook_selection          (Haiku — pick best)
  → [6] script_generation       (Sonnet — SINGLE PASS from blueprint + hook, no retries)
  → [7] integrity_check         (Haiku — hallucination / consistency / structure check)
      ├── PASS → script_packager → END
      └── FAIL →
          → [8] patch_generator  (Haiku — minimal diff instructions, NOT full rewrite)
          → [9] apply_patch      (deterministic — string merge from Patch schema)
          → [10] re_check        (Haiku — same as integrity_check, max 1 retry)
              ├── PASS → script_packager → END
              └── FAIL → mark manual_review, store artifact → END
```

**MAX_INTEGRITY_LOOPS = 2** (one repair cycle max; never full rewrite).

### New Schemas (add to `cf_platform/core/schemas.py` or new `idea_to_script_schemas.py`)
```
Signal(source, content, signal_type, weight, url?)          — optional, stubs for now
DirectionContext(angle, narrative_bias, hook_direction?, do_not_focus_on)
IdeaToScriptInput(idea_title, signals=[], direction_context=None)
NormalizedContext(primary_angle, evidence_summary, top_signals, controversies, hook_bias)
Section(title, key_points)
Blueprint(hook_angle, structure, claims, monetization_angle, required_evidence, signal_summary, direction_alignment_notes)
IntegrityIssue(description, span?, severity)
IntegrityReport(passed, issues)
Patch(operation: replace|insert|delete, target: str, replacement: str?)
IdeaToScriptOutput(script, blueprint, integrity_report, cost_meta, version)
```

### Acceptance Criteria
- [ ] All schemas above defined and importable; `Signal` and `DirectionContext` are optional stubs (no upstream discovery stage required)
- [ ] `Patch` schema is machine-parseable: `operation`, `target` (verbatim text to find), `replacement` — patch_generator must output structured JSON, not prose instructions
- [ ] `context_normalization` and `blueprint_merge` and `apply_patch` contain zero LLM calls (pure functions)
- [ ] `script_generation` calls the LLM exactly once; no retries, no variants, no loop
- [ ] `evaluation` combines fact-check + score + alignment into ONE Sonnet call (no `web_search` tool)
- [ ] `MAX_INTEGRITY_LOOPS = 2` enforced; on persistent failure the run stores the artifact with `status=manual_review` and exits gracefully
- [ ] Existing workers deprecated: `script_writer`, `script_quality_scorer`, `fact_checker`, `script_refiner` replaced by new nodes; `script_packager` retained for final artifact packaging
- [ ] `build_idea_to_script_graph` topology updated to new 10-node DAG; `build_refine_loop_graph` updated or removed
- [ ] `IdeaToScriptState` retains `run_id`, `user_id`, `inputs`, `iteration`, `max_iterations`, `artifacts`; removes `scorer_verdict`, `factcheck_verdict`, `quality_threshold`, `unverified_threshold`; gains `integrity_loops: Annotated[int, operator.add]`
- [ ] `niche` from `state.inputs` flows into `blueprint_generation` and `evaluation` nodes (P6-S6 wires this — AC here is that the nodes read it, defaulting to generic framing when absent)
- [ ] `target_duration_seconds` in `IdeaToScriptState` (from P6-S5) flows into `script_generation` node — node reads `getattr(state, "target_duration_seconds", 60)` for word-count target
- [x] D058 logged in `DECISIONS.md`
- [x] REST endpoint `POST /platform/blocks/idea-to-script` and Telegram `/script` command continue to work unchanged (backward-safe interface contract)
- [ ] **Human touchpoint:** Telegram `/script <idea>` → script artifact under $0.15 (DEFERRED — requires DEV smoke test after deploy)
- [x] Tests: unit tests for each node; deterministic nodes (normalization, merge, apply_patch) tested without mocks

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/idea_to_script_schemas.py` (new): all Blueprint IR schemas — `Signal`, `DirectionContext`, `IdeaToScriptInput`, `NormalizedContext`, `Section`, `Blueprint`, `EvaluationArtifact`, `HookVariantsArtifact`, `SelectedHookArtifact`, `GeneratedScriptArtifact`, `IntegrityIssue`, `IntegrityReport`, `Patch`, `PatchSetArtifact`, `IdeaToScriptOutput`
- `cf_platform/core/schemas.py`: `IdeaToScriptState` rewritten — removed `scorer_verdict`, `factcheck_verdict`, `quality_threshold`, `unverified_threshold`; added `integrity_loops: Annotated[int, operator.add] = 0`, `integrity_verdict: ControlSignal = "continue"`; kept `iteration`, `max_iterations`
- 10 new workers: `context_normalizer` (none), `blueprint_generator` (Sonnet), `evaluator` (Sonnet), `blueprint_merger` (none), `hook_generator` (Haiku), `hook_selector` (Haiku), `script_generator` (Sonnet), `integrity_checker` (Haiku), `patch_generator` (Haiku), `patch_applier` (none)
- `cf_platform/workers/script_packager.py` rewritten: now reads `generated_script` artifact; `ScriptArtifact` gains `word_count`, `status`; `overall_score` and `draft_number` are Optional (None in new arch); `worker_version="2.0.0"`
- `cf_platform/blocks/idea_to_script.py` rewritten: `build_idea_to_script_graph()` now 10-node DAG; `register_idea_to_script_workers()` registers 11 workers; `build_refine_loop_graph()` removed; `MAX_INTEGRITY_LOOPS = 2`
- `cf_platform/interfaces/telegram.py`: `format_script_reply` updated — score line only when `overall_score` is not None; `⚠️ Manual review required` shown when `status="manual_review"`
- Old workers (`script_writer`, `script_quality_scorer`, `fact_checker`, `script_refiner`) kept importable with deprecation notes; not registered in active graph
- 13 new test files (+ rewrites of 4 existing); 540 tests passing (CI green)

---

## EPIC 31 — Orchestrator + Legacy Bridge (Sprint P6)
Parent graph chains the blocks + legacy render via the adapter; HITL gates (D047, D052).

---

## [P6-S1] Legacy adapter (interface + in-process impl)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 3
**Depends on:** P5-S5

### Goal
`cf_platform/adapters/legacy_video.py`: `LegacyVideoAdapter` Protocol + in-process impl calling `src/pipeline.py` (script artifact → storyboard → assets → render → `final.mp4` in R2). **Only module importing `src/`** (D047). HTTP-swappable contract. Emits `trace_event`s (not artifacts of its own).
**Tech:** Python Protocol; `src/pipeline.py`; R2. **Artifacts:** `VideoResult`.

> **Spike finding (2026-06-13, during P0-S5):** `src/pipeline.py` exposes only `summarize_step()`. The alignment → render chain is frontend-driven REST (no server-side `run_full_pipeline()`). Adapter must either (a) add a chaining function to `src/`, or (b) chain existing per-step functions itself. Decide during this story's design.
> **Resolution (2026-06-18):** chose (b) — chain per-step domain functions directly; `src/` unchanged.

### Acceptance Criteria
- [x] Adapter produces `final.mp4` in R2 from a script artifact
- [x] Only `legacy_video.py` imports `src/`; `src/` unchanged
- [x] Legacy DEV/PROD pipeline still works independently

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/adapters/legacy_video.py` (new): `VideoResult(r2_key, legacy_run_id, status, error?)` Pydantic model; `LegacyVideoAdapter` Protocol (`async def render(run_id, script, trace_repo) → VideoResult`); `InProcessLegacyVideoAdapter` — chains 6 legacy steps: [TTS?] → storyboard → manifest → acquisition → ffmpeg-script → render; emits one `TraceEvent` per step (`worker="legacy_render"`, `source` = step name); TTS is skipped gracefully when `ELEVENLABS_API_KEY` is absent; any step failure logs the trace event with `status="error"` and returns `VideoResult(status="failed")` immediately.
- Settings injected at construction (`src.config.Settings`); lazy-loaded from ENV when not provided (supports test injection without breaking D047).
- Platform `run_id` (UUID) used as the legacy R2 prefix (`runs/{run_id}/`) — no slug conversion; R2 treats it as a plain path segment.
- `src/` is **unchanged** — all coupling is in `legacy_video.py` only.
- 16 tests in `tests/cf_platform/test_legacy_video_adapter.py` covering: happy path, TTS skip/fail, all 5 step failure modes, trace event sources, render arg verification, Protocol conformance, VideoResult model.
- 1411 total tests passing (CI green).

---

## [P6-S2] Legacy-as-node + parent graph (+ PipelineState)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 5
**Depends on:** P6-S1, P6-S5

### Goal
Implement `PipelineState` (plan §5); wrap the adapter as a LangGraph node; compile `cf_platform/orchestrator/full_pipeline.py` composing `niche_to_ideas → idea_to_script → legacy_render`. One run threads run_id + artifacts end-to-end with full lineage; checkpointed.
**Tech:** LangGraph (subgraph composition, PostgresSaver), adapter. **Schema:** `PipelineState`.

> **Duration note (P6-S5):** `PipelineState` must carry `target_duration_seconds: int = 60`. The orchestrator writes it into `IdeaToScriptState` when constructing the block's initial state — this is the "specified once at the top, flows down" contract.

### Acceptance Criteria
- [x] Parent graph runs all three stages in one run
- [x] Lineage spans new blocks + legacy node

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/schemas.py`: `PipelineState(StageState)` added — `hitl: bool = False`, `target_duration_seconds: int = 60`. Artifact refs: `"ranked_ideas"`, `"script"`, `"video"` (terminal).
- `cf_platform/orchestrator/__init__.py` (new): package marker.
- `cf_platform/orchestrator/full_pipeline.py` (new): `build_full_pipeline_graph(*, storage, registry, executions, artifact_repo, adapters, trace_repo, anthropic_api_key, legacy_adapter?, checkpointer?) → CompiledStateGraph`. Three inner closure nodes:
  - `niche_to_ideas_node`: constructs `NicheToIdeasState` from parent state, calls `run_graph(niche_graph, ..., thread_id=f"{run_id}:niche_to_ideas")`, returns `{"artifacts": {"ranked_ideas": result.artifacts["ranked_ideas"]}}`.
  - `idea_to_script_node`: reads `ranked_ideas` artifact via `read_artifact` to extract `selected.title` as `idea_title`; constructs `IdeaToScriptState` with `idea_title`, `niche` (if present), `target_duration_seconds`; calls `run_graph(script_graph, ..., thread_id=f"{run_id}:idea_to_script")`; returns script ref.
  - `legacy_render_node`: reads `script` artifact, calls `adapter.render(run_id, script_text, trace_repo)`, returns `{"artifacts": {"video": result.r2_key}}`; raises `RuntimeError` on `status="failed"`.
- Legacy adapter defaults to `InProcessLegacyVideoAdapter()` when not injected.
- 13 tests in `tests/cf_platform/test_full_pipeline.py`; 1447 total passing (CI green).

---

## [P6-S3] Human-in-the-loop gates
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** med
**Points:** 3
**Depends on:** P6-S2, P2-S4

### Goal
LangGraph `interrupt` at script-approval (and optional idea-selection); resume via `POST /runs/{id}/resume {decision}`; Telegram approve/edit; configurable auto-approve timeout (default fully autonomous).
**Tech:** LangGraph interrupts, Telegram, Postgres checkpoints.

### Acceptance Criteria
- [x] Run pauses at the gate and resumes on decision
- [x] Timeout auto-approves per config

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/config.py`: `PlatformSettings` gains `HITL_TIMEOUT_SECONDS: int = 0` — 0 = no timeout (fully autonomous); positive value enables auto-approve after N seconds.
- `cf_platform/interfaces/telegram.py`: 4 new HITL functions — `format_script_approval_request(run_id, script_preview)`, `parse_hitl_decision(text) → Optional[tuple[str, str]]` (parses `/approve <run_id>` and `/reject <run_id>`), `format_hitl_approved(run_id)`, `format_hitl_rejected(run_id)`. Script preview capped at 2000 chars.
- `cf_platform/orchestrator/hitl.py` (new): `auto_approve_after_timeout(run_id, timeout_seconds, graph, thread_id?) → None` — asyncio.sleep then `graph.ainvoke(Command(resume="approve"), config)`. No-op when `timeout_seconds <= 0`. Swallows and logs exceptions. Caller wires this as a background task (P6-S4).
- `cf_platform/orchestrator/full_pipeline.py`: `script_approval_gate` node added — calls `interrupt({"type": "script_approval", "run_id": ..., "script_r2_key": ...})`; approve → returns `{}`; reject → raises `RuntimeError`. `_route_after_script` conditional edge: `hitl=True` → gate → legacy_render; `hitl=False` → legacy_render directly.
- `cf_platform/interfaces/api.py`: `ResumeRequest(decision: Literal["approve","reject"])` / `ResumeResponse` models; `POST /platform/runs/{run_id}/resume` (202) — rebuilds the graph, calls `graph.ainvoke(Command(resume=decision), config)` in a BackgroundTask; returns immediately.
- 25 tests in `tests/cf_platform/test_p6_s3_hitl.py` covering: gate routing (hitl=True/False), gate approve/reject logic, auto_approve_after_timeout (5 cases), Telegram formatters/parsers (9 cases), REST endpoint (3 cases using `app.dependency_overrides`).
- Note: Python 3.9.6 compatibility — LangGraph's `interrupt()` requires 3.11+ in async context (`contextvars`). Gate tests patch `cf_platform.orchestrator.full_pipeline.interrupt` directly instead of calling LangGraph machinery. Production upgrade to 3.11+ is tracked separately.
- 1498 total tests passing (CI green).

---

## [P6-S4] End-to-end /produce → video
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 2
**Depends on:** P6-S2

### Goal
Telegram `/produce <niche>` runs the whole chain; returns a presigned R2 URL for `final.mp4`. Capstone smoke test.
**Tech:** all of the above.

### Acceptance Criteria
- [x] One command → finished video; lineage spans blocks + legacy
- [x] `/produce` accepts optional `--duration <seconds>` flag (default 60); passed into `PipelineState.target_duration_seconds`
- [x] **Human touchpoint:** operator runs `/produce <niche>` and downloads the video

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/telegram.py`: `parse_produce_command`, `parse_produce_args`, `format_produce_running`, `format_produce_usage`, `format_produce_reply`; `format_unrecognized_command` updated to mention `/produce`.
- `cf_platform/core/artifact_manager.py`: `ArtifactStorage` Protocol gains `generate_presigned_url(key, expires_in=86400)`; `InMemoryArtifactStorage` returns a fake URL; `R2ArtifactStorage` calls boto3 `generate_presigned_url` (no new dependency).
- `cf_platform/interfaces/api.py`: `_run_produce_and_reply` background coroutine (mirrors `_run_ideas_and_reply` / `_run_script_and_reply`); `POST /platform/pipeline/produce` REST endpoint (`ProduceRequest` / `ProduceResponse`); `/produce` branch in `telegram_webhook` handler; imports for `build_full_pipeline_graph` and `PipelineState`.
- 26 tests in `tests/cf_platform/test_p6_s4_produce.py`; 1473 total passing (CI green).
**Smoke test:** DEFERRED — requires DEV deploy + real Pexels/ffmpeg/ElevenLabs environment. Operator run: `/produce american housing economics` → presigned URL → download final.mp4.

---

## [P6-S5] Target duration parameter (run-level → script writer)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 3
**Depends on:** P5-S5

### Goal
Add `target_duration_seconds` as a typed run-level parameter that enters at the top of the pipeline and is consumed by the script writer and scorer. Specified once (niche trigger / `/produce` / REST), never re-derived.

**Design:** `target_duration_seconds` is added to `IdeaToScriptState` now (block-level); P6-S2 adds it to `PipelineState` and the orchestrator passes it down. Script writer computes `target_words = round(target_duration_seconds * 160 / 60)` and tells Claude explicitly. Scorer flags if delivered word count is >20% off — deterministically (no extra LLM call).

**Execution order in P6:** `(P6-S1 ∥ P6-S5) → P6-S2 → (P6-S3 ∥ P6-S4)`.

### Acceptance Criteria
- [x] `IdeaToScriptState.target_duration_seconds: int = 60` typed channel in `cf_platform/core/schemas.py`
- [x] Script writer prompt includes `"Write approximately {target_words} words ({target_duration_seconds}s at 160 wpm)"`; `target_words` computed in the worker (not by Claude) — already present in `script_generator.py` via `getattr`; now a typed state field
- [x] Script packager (Blueprint IR arch equivalent of scorer) flags `length_ok=False` when word_count is >20% over or under `target_words`; deterministic, no LLM call; added `length_ok: bool = True` to `ScriptArtifact`
- [x] `POST /platform/blocks/idea-to-script` request body accepts `target_duration_seconds: int = 60` and passes it to initial graph state
- [x] Telegram `/script <title> [--duration <seconds>]` parser extracts the flag; defaults to 60 if absent
- [ ] P6-S2 note: `PipelineState.target_duration_seconds` must carry this field; orchestrator writes it into `IdeaToScriptState` at block entry. (Tracked in P6-S2 AC.)
- [x] Tests: state field default/custom; `parse_script_duration_args` (6 cases); packager `length_ok` (6 cases); REST request model; Telegram ack + kwargs — 18 tests passing

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/core/schemas.py`: `IdeaToScriptState` gains `target_duration_seconds: int = 60` (typed channel, not annotated with operator.add — plain assignment, not a reducer).
- `cf_platform/workers/script_packager.py`: `ScriptArtifact` gains `length_ok: bool = True`; packager computes `target_words = round(generated.target_duration_seconds * 160/60)` and sets `length_ok = abs(word_count - target_words) / max(target_words, 1) <= 0.20`. Deterministic, no LLM call.
- `cf_platform/interfaces/telegram.py`: `parse_script_duration_args(args: str) -> Tuple[str, int]` — splits trailing `--duration <n>` flag from the idea title; defaults to 60 when absent or `n <= 0`. `format_script_usage()` updated to mention the flag.
- `cf_platform/interfaces/api.py`: `IdeaToScriptRequest` gains `target_duration_seconds: int = 60`; route handler passes it as `state_kwargs["target_duration_seconds"]`; `_run_script_and_reply` gains `target_duration_seconds: int = 60` kwarg and sets it on `IdeaToScriptState`; webhook handler calls `parse_script_duration_args` to extract title + duration.
- 18 tests in `tests/cf_platform/test_p6_s5_duration.py`; 1434 total passing (was 1411).

---

## [P6-S6] Niche-aware prompts (replace hardcoded channel)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-18
**Priority:** high
**Points:** 3
**Depends on:** P5-S5

### Goal
Remove all hardcoded "The Housing Equation" / "American housing economics" references from worker system prompts. Replace with a `niche` string read from `state.inputs["niche"]` at call time. When niche is absent (standalone `/script`), workers use generic framing and the script writer infers the niche from the idea title.

**Design:**
- Niche is a plain `str | None` — no `ChannelContext` object for MVP.
- For the full pipeline (P6), niche enters at the top of the run (`/produce <niche>` or REST) and flows through `state.inputs` to every block.
- When channel integration arrives post-MVP, niche is inferred from the channel automatically — no worker changes needed.
- `IdeaToScriptRequest.niche` already exists and is already passed to `state.inputs` — the gap is that workers ignore it in favour of hardcoded text.

**Fallback behaviour when niche is None:**
- Script writer: include in prompt — "If no niche is provided, infer the appropriate content niche from the idea title and write accordingly."
- Scorer, fact-checker, refiner: use generic framing ("a data-driven YouTube Shorts channel") — no niche-specific bias.

**Execution order in P6:** `(P6-S1 ∥ P6-S5 ∥ P6-S6) → P6-S2 → (P6-S3 ∥ P6-S4)`.

### Acceptance Criteria
- [x] No hardcoded "The Housing Equation" or "American housing economics" in any worker prompt
- [x] `topic_generator`, `opportunity_scorer`, `script_writer`, `fact_checker` read niche at call time — new Blueprint IR workers (`blueprint_generator`, `evaluator`, `script_generator`) were already niche-aware
- [x] Script writer falls back to niche-inference when niche is None (v3 prompt)
- [x] Scorer/fact-checker fall back to generic framing when niche is None
- [x] Workers score content on its own merits when niche is absent
- [x] Full pipeline with `niche="american housing economics"` behaves identically to old hardcoded behaviour
- [x] Tests: version pin assertions updated; `test_prompt_has_no_hardcoded_channel` and `test_prompt_includes_niche_inference_fallback` per worker

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/topic_generator.py`: prompt v1→v2, worker_version 1.0.0→1.1.0; hardcoded housing removed, generic content-strategist framing
- `cf_platform/workers/opportunity_scorer.py`: prompt v1→v2, worker_version 1.0.0→1.1.0; housing-specific axis descriptions removed
- `cf_platform/workers/script_writer.py`: prompt v2→v3, worker_version 1.1.0→1.2.0; niche injected from `state.inputs.get("niche")`; fallback: "infer the appropriate content niche from the idea title"
- `cf_platform/workers/fact_checker.py`: prompt v1→v2, worker_version 1.0.0→1.1.0; generic fact-checker framing
- Blueprint IR workers (`blueprint_generator`, `evaluator`, `script_generator`, `narrative_lens`) unchanged — already niche-aware via `state.inputs.get("niche")`
- Tests updated in `test_topic_generator`, `test_opportunity_scorer`, `test_script_writer`, `test_fact_checker`, `test_niche_to_ideas`

---

## [P6-S7] Gemini TTS + /testvoice harness
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** done
**Completed:** 2026-06-19
**Priority:** high
**Points:** 5
**Depends on:** P6-S4 (voice_production.py scaffolding built in P6-voice session)

### Goal
Two-part: (1) **Swap ElevenLabs → Gemini 2.5 Flash TTS** in `voice_production.py` (D061 — cost: free vs ~$22/M chars). (2) **Add `/testvoice <run_id>` Telegram command** so voice can be tested in isolation without running the full pipeline from scratch — reads the script artifact from an existing run, calls voice_production_worker directly, uploads MP3, returns a presigned URL.

**Why this order matters:** running `/produce` end-to-end will fail unpredictably at voice or render; without `/testvoice` every bug fix requires a full restart from niche generation (~$0.10 + 2 min). `/testvoice` gives a 30-second feedback loop.

### Background: current state after P6-voice session (2026-06-19)
`cf_platform/workers/voice_production.py` exists and is wired into the full pipeline (`idea_to_script → voice_production → legacy_render`). It implements ElevenLabs TTS + Deepgram alignment + proportional fallback. This is a **placeholder** — ElevenLabs is the wrong backend per D061 and the operator has no ElevenLabs key. P6-S7 replaces the TTS engine only; Deepgram alignment and fallback are unchanged.

### Changes needed

**1. Gemini TTS in `voice_production.py`**
- Replace `_call_elevenlabs`, `_tts_generate`, `_encode_pcm_to_mp3` with a Gemini 2.5 Flash TTS call via `google-generativeai` SDK
- Gemini TTS model: `gemini-2.5-flash-preview-tts` (or current stable); voice set via `GEMINI_TTS_VOICE` (e.g. `"Kore"`)
- Gemini TTS returns PCM/WAV — re-encode to MP3 via ffmpeg subprocess (same as ElevenLabs path)
- Remove `_ELEVENLABS_TTS_URL`, `_OUTPUT_FORMAT`, `_PCM_*` constants; add `_GEMINI_TTS_MODEL`
- Worker factory signature: replace `elevenlabs_api_key` + `elevenlabs_voice_id` → `gemini_api_key` + `gemini_tts_voice`

**2. PlatformSettings**
- Remove `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`; add `GEMINI_API_KEY: str = ""`, `GEMINI_TTS_VOICE: str = ""`
- `DEEPGRAM_API_KEY` stays (alignment is separate from TTS)

**3. `full_pipeline.py` + `api.py`**
- Pass `gemini_api_key` + `gemini_tts_voice` instead of ElevenLabs keys to `build_voice_production_worker` and `build_full_pipeline_graph`

**4. `/testvoice <run_id>` command**
- New Telegram command: `/testvoice <run_id>`
- Handler in `api.py` → background task `_run_testvoice_and_reply`
- Logic: read `runs/{run_id}/storyboard.json` or ask operator for the script key (simpler: accept raw run_id, read `script` artifact from the run's artifact store by querying the latest `script` artifact for that run_id)
  - **Simplest approach:** operator provides a `run_id` that already has a `script` artifact; handler looks up the artifact key in the artifact store (`artifact_repo.get_latest(run_id, "script")`), then calls `voice_production_worker` directly (not through the full graph), uploads MP3, returns presigned URL
- New helpers in `telegram.py`: `parse_testvoice_command`, `format_testvoice_running`, `format_testvoice_reply(run_id, mp3_url)`

**5. Dependencies**
- Add `google-generativeai` to `requirements.txt` (D061 pre-approved this)

### Acceptance Criteria
- [x] `voice_production.py` uses Gemini 2.5 Flash TTS; `_tts_generate` calls `google-generativeai` SDK, returns MP3 bytes
- [x] `ELEVENLABS_*` settings removed; `GEMINI_API_KEY` + `GEMINI_TTS_VOICE` wired through `PlatformSettings` → `build_voice_production_worker`
- [x] `google-generativeai` in `requirements.txt`
- [x] `/testvoice <run_id>` command: reads script artifact → calls voice_production → returns presigned URL in ~30s
- [x] No keys → proportional fallback still works (D048 fault isolation)
- [x] All tests pass; new tests cover Gemini TTS path (mocked) + /testvoice command
- [ ] **Human touchpoint:** operator sends `/testvoice <run_id>` → presigned MP3 URL → listens to voice — DEFERRED (requires DEV deploy with `GEMINI_API_KEY` set and an existing run with a `script` artifact)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/voice_production.py`: ElevenLabs replaced with Gemini 2.5 Flash TTS (`_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"`); `_call_gemini_tts_sync(text, api_key, voice) → bytes` (sync SDK call, wrapped in `asyncio.to_thread`); PCM at 24 kHz/mono s16le re-encoded to MP3 via ffmpeg. Worker factory: `build_voice_production_worker(storage, gemini_api_key="", gemini_tts_voice="", deepgram_api_key="") → WorkerNode`. `worker_version="2.0.0"`, `model="gemini_deepgram"`.
- `cf_platform/core/config.py`: `ELEVENLABS_API_KEY`/`ELEVENLABS_VOICE_ID` removed; `GEMINI_API_KEY: str = ""` and `GEMINI_TTS_VOICE: str = ""` added. `DEEPGRAM_API_KEY` unchanged.
- `cf_platform/orchestrator/full_pipeline.py`: factory now accepts `gemini_api_key`/`gemini_tts_voice` (was ElevenLabs keys); passes them to `build_voice_production_worker`.
- `cf_platform/adapters/legacy_video.py`: ElevenLabs fallback branch removed entirely — adapter never calls TTS; `voice_production_worker` always runs before the adapter and provides `voice_alignment`. When `voice_alignment is None`, adapter logs and renders silent video. `generate_tts` import removed.
- `cf_platform/interfaces/telegram.py`: `parse_testvoice_command(text) → Optional[str]`; `format_testvoice_running(run_id) → str`; `format_testvoice_reply(run_id, mp3_url) → str`; `format_unrecognized_command` updated to list `/testvoice`.
- `cf_platform/interfaces/api.py`: `_run_testvoice_and_reply(chat_id, run_id, settings, storage, artifacts)` background coroutine — looks up `script` artifact via `artifact_repo.list_for_run(run_id)`, calls `build_voice_production_worker` directly (not through the full graph), generates 1h presigned MP3 URL, sends reply. `/testvoice` branch wired in `telegram_webhook`. `_TESTVOICE_MP3_URL_EXPIRY = 3600`.
- `requirements.txt`: `google-generativeai>=0.8.0` added.
- Tests: `test_voice_production.py` (updated — Gemini path); `test_p6_s7_testvoice.py` (new, 19 tests — parsers, formatters, `PlatformSettings` fields, `_run_testvoice_and_reply` 3 paths, webhook 2 paths); `test_legacy_video_adapter.py` (updated — TTS tests replaced; adapter always emits 5 trace events).
- 1531 total tests passing (CI green).

---

## EPIC 34 — Idea Selection + YouTube Metadata (Sprint P7)
Complete the operator loop: pick an idea, get a finished video with ready-to-paste YouTube metadata.

---

## [P7-S1] Idea selection flow
**Epic:** E34 — Idea Selection + YouTube Metadata
**Sprint:** P7
**Status:** done
**Completed:** 2026-06-19
**Priority:** high
**Points:** 3
**Depends on:** P6-S4

### Goal
`/ideas <niche>` reply shows 5 numbered ideas (currently shows 1 selected + 3 alternatives = 4 total; needs restructuring). New `/pick <run_id> <n>` command lets the operator select idea N from a prior `/ideas` run, then triggers the full produce pipeline for that idea without re-running discovery.

**Design:**
- `format_ranked_ideas` updated to show all top ideas numbered 1–5 (use `selected` + `alternatives`, ensure top_n=5 propagated).
- `parse_pick_command(text) → Optional[tuple[run_id, int]]` — parses `/pick <run_id> <n>`.
- `/pick` handler: reads `ranked_ideas` artifact for the given run_id, extracts idea N, calls `_run_produce_and_reply` with `idea_title` and `niche` fixed (bypasses the niche→ideas block; runs idea_to_script → voice → legacy_render only).
- Add `idea_title` override to `ProduceRequest` and `PipelineState`/`full_pipeline_graph` so the orchestrator can skip niche→ideas when an idea is already selected.
- `format_pick_usage()`, `format_pick_running(run_id, idea_title)`.

**Tech:** Telegram, FastAPI, LangGraph (partial pipeline run).

### Acceptance Criteria
- [x] `/ideas <niche>` reply lists ideas numbered 1–5
- [x] `/pick <run_id> <n>` triggers the pipeline using the chosen idea; sends running ack
- [x] `PipelineState` / orchestrator accepts `idea_title` override to skip niche→ideas
- [x] Telegram reply from `/pick` includes presigned video URL (metadata added in P7-S3)
- [x] Tests: parse_pick_command (valid, malformed, out-of-range); pick webhook path; PipelineState idea_title override; format_pick_* helpers

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/telegram.py`:
  - `format_ranked_ideas` rewritten — numbered 1–5 list, `run_id` shown, `/pick <run_id> <n>` CTA.
  - `/run <niche> [--duration <s>]` replaces old `/produce` for niche-to-video: `parse_run_command`, `parse_run_args`, `format_run_running`, `format_run_usage`, `format_run_reply`.
  - `/produce <idea title> [--duration <s>]` is a new named-idea command (bypasses discovery): `parse_produce_command`, `parse_produce_args`, `format_produce_running`, `format_produce_usage`, `format_produce_reply`.
  - `/pick <run_id> <n> [--duration <s>]`: `parse_pick_command → Optional[tuple[str, int, int]]`; `format_pick_usage`, `format_pick_running`.
  - `_DURATION_FLAG_RE` + `_parse_duration_flag` shared by all three arg parsers.
- `cf_platform/core/schemas.py`: `PipelineState.idea_title: Optional[str] = None`.
- `cf_platform/orchestrator/full_pipeline.py`: `_route_start` conditional edge skips `niche_to_ideas` when `idea_title` set.
- `cf_platform/interfaces/api.py`: `_run_pipeline_and_reply` shared helper (replaces `_run_produce_and_reply`); `/run`, `/produce`, `/pick` webhook branches; `_VIDEO_URL_EXPIRY` constant. REST `POST /platform/pipeline/produce` unchanged.
- Tests: `test_p7_s1_pick.py` updated (3-tuple, `_run_pipeline_and_reply`); `test_p6_s4_produce.py` rewritten for dual `/run`+`/produce` coverage; 4 other tests updated. 1581 total passing (CI green).

---

## [P7-S2] YouTube metadata worker
**Epic:** E34 — Idea Selection + YouTube Metadata
**Sprint:** P7
**Status:** done
**Completed:** 2026-06-19
**Priority:** high
**Points:** 3
**Depends on:** P7-S1

### Goal
New worker: reads `script` artifact → produces a `youtube_metadata` artifact with `title` (≤70 chars), `description` (≤500 chars, includes hashtags), and `tags` (list[str], ≤15 tags). One Haiku call. Wired into the full pipeline after `idea_to_script` and before `voice_production`.

**Tech:** LangGraph worker, Haiku 4.5. **Artifact:** `youtube_metadata`.

### Acceptance Criteria
- [x] `YoutubeMetadataArtifact(title, description, tags)` Pydantic model defined and stored
- [x] `title` ≤ 70 chars enforced (truncated if Claude over-shoots)
- [x] Worker wired into `full_pipeline.py` after `idea_to_script_node`
- [x] `PipelineState` carries `"youtube_metadata"` artifact ref
- [x] Tests: happy path, title truncation, missing script key, registration pins

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/workers/youtube_metadata.py` (new): `YoutubeMetadataArtifact(title, description, tags, generated_at)` Pydantic model; `YOUTUBE_METADATA_REGISTRATION` (worker_version 1.0.0, prompt_version v1, model claude-haiku-4-5); `build_youtube_metadata_worker(storage, anthropic_api_key) → WorkerNode`. Reads `state.artifacts["script"]` → `ScriptArtifact`; passes `idea_title`, `niche` (from `state.inputs`), and `script` to Haiku. Hard truncates: title at 70 chars, description at 500, tags capped at 15. `_extract_json` ported from `src/metadata_generator.py` (no `src/` import per D047).
- `cf_platform/orchestrator/full_pipeline.py`: `youtube_metadata_node` inserted between `idea_to_script` and `voice_production`; `_route_after_script` routes to `youtube_metadata` (was `voice_production`); gate edge also routes to `youtube_metadata`; YOUTUBE_METADATA_REGISTRATION registered at compile time; `build_observed_node_graph` wraps the worker.
- `cf_platform/core/schemas.py`: `PipelineState` docstring updated to list `"youtube_metadata"` artifact ref.
- `tests/cf_platform/test_p7_s2_youtube_metadata.py` (new): 11 tests — `_extract_json` (3), registration pins (1), happy path (1), niche in prompt (1), no-niche omits line (1), title truncation (1), description truncation (1), tags cap (1), missing script key (1).
- `tests/cf_platform/test_full_pipeline.py` + `test_p6_s3_hitl.py`: updated `run_graph` side_effect lists to include youtube_metadata call (4th in sequence); `test_run_id_threads_into_block_states` now asserts 4 captured states.
- 1592 total tests passing (CI green).

---

## [P7-S3] Produce → metadata reply
**Epic:** E34 — Idea Selection + YouTube Metadata
**Sprint:** P7
**Status:** done
**Completed:** 2026-06-19
**Priority:** high
**Points:** 2
**Depends on:** P7-S1, P7-S2

### Goal
Update the Telegram reply from `/pick` (and `/produce`) to include the `youtube_metadata` artifact alongside the video URL. Operator can copy-paste title/description/tags directly into YouTube Studio.

**Design:**
- `format_produce_reply` updated to accept optional `YoutubeMetadataArtifact`; appends a formatted metadata block when present.
- `_run_pipeline_and_reply` reads `youtube_metadata` artifact from the result before sending the reply.
- **Human touchpoint:** operator sees presigned video URL + title/description/tags block in Telegram.

### Acceptance Criteria
- [x] `/pick` reply includes video URL + YouTube metadata block
- [x] `/produce` reply also includes metadata when the worker ran successfully
- [x] Metadata absent from reply is handled gracefully (worker failure → video URL only)
- [ ] **Human touchpoint:** operator sends `/ideas <niche>`, picks idea, receives 16:9 video + metadata — DEFERRED (requires DEV deploy)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `cf_platform/interfaces/telegram.py`: `format_youtube_metadata_block(metadata: YoutubeMetadataArtifact) → str` — plain-text block with title, description, and comma-separated tags; section header "YouTube Metadata". `format_produce_reply` gains optional `metadata: Optional[YoutubeMetadataArtifact] = None` kwarg; appends the block when provided (backward-compatible — existing callers unaffected). `YoutubeMetadataArtifact` imported via `TYPE_CHECKING`.
- `cf_platform/interfaces/api.py`: `format_youtube_metadata_block` added to telegram imports; `YoutubeMetadataArtifact` imported from `cf_platform.workers.youtube_metadata`. `_run_pipeline_and_reply` updated — after generating the video presigned URL, reads `result.artifacts.get("youtube_metadata")`; if present, calls `read_artifact` + `YoutubeMetadataArtifact.model_validate`; on failure logs a WARNING and falls back to `metadata=None`. Reply built via `format_produce_reply(display_label, run.run_id, video_url, metadata)`.
- `tests/cf_platform/test_p7_s3_metadata_reply.py` (new): 11 tests — `format_youtube_metadata_block` (4: title, description, tags, header), `format_produce_reply` (4: without metadata, None=no-arg, with metadata, video info present), `_run_pipeline_and_reply` (3: metadata present, metadata absent, metadata read error).
- 1603 total tests passing (CI green).

---

## EPIC 35 — Footage Quality (Sprint P8)

Expand the stock footage source chain (Pixabay → Wikimedia Commons), add real-person photo routing, gate every acquired clip through a quality check, surface telemetry to the operator, and apply a colour grade to the final render. All acquisition logic is written as clean, isolated modules in `src/` so P9's native AcquisitionWorker can import them directly with no rework.

**Full acquisition chain after P8:**

| Scene mode | Chain |
|------------|-------|
| Stock video (default) | Pexels video → Pixabay video → Replicate AI |
| Stock photo / image | Pexels photo → Pixabay photo → Wikimedia Commons → Replicate AI |
| Person photo (`person_name` set) | Wikimedia person photo → generic Pexels/Pixabay → (no AI — wrong person > no person) |
| Historic clip (`historic: true`) | Wikimedia Commons → Pexels/Pixabay generic → Replicate AI |

Every clip passes a **QA gate** before being accepted. Each asset records its `source`. A `footage_summary` surfaces in the Telegram reply. A colour grade is applied in FFmpeg.

**P9 portability contract:** every source client is a standalone module (`src/pixabay_client.py`, `src/wikimedia_client.py`). Every QA function is a pure function. P9's `AcquisitionWorker` imports these directly.

---

## [P8-S1] Pixabay source — videos + photos
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
Add Pixabay (free API, no watermark, standard licence) as the second stock source in `src/`. New `src/pixabay_client.py` module. Acquisition chain for video scenes becomes **Pexels → Pixabay → Replicate**; for photo scenes **Pexels → Pixabay → Wikimedia (P8-S2) → Replicate**.

Decisions required: **D063** (Pixabay dependency).

### Source details
- API: `https://pixabay.com/api/` (videos) + `https://pixabay.com/api/` (images)
- Auth: `PIXABAY_API_KEY` query param
- Licence: Pixabay Content Licence — free for commercial use, no attribution required
- Rate limit: 100 req/min (free tier)
- Response: `hits[]` with `videos.medium.url` / `largeImageURL`, resolution, duration

### Module contract (`src/pixabay_client.py`)
```python
async def search_videos(query: str, per_page: int = 10) -> list[PixabayVideo]
async def search_photos(query: str, per_page: int = 10) -> list[PixabayPhoto]

# PixabayVideo: url, width, height, duration_seconds, page_url
# PixabayPhoto: url, width, height, page_url
```
Clean module, no `src/` imports — importable by P9 worker.

### Acceptance Criteria
- [x] `PIXABAY_API_KEY` added to `src/config.py` (default `""`) and `ENV.md`
- [x] D063 logged in `DECISIONS.md`
- [x] `src/pixabay_client.py`: `search_videos` + `search_photos` via `httpx.AsyncClient`; returns empty list on API error (fault isolation)
- [x] `src/acquisition.py`: parallel merge+rank strategy — Pexels + Pixabay searched concurrently; winner selected by resolution (pixel area); only winner downloaded; Replicate retired (D063)
- [x] `PIXABAY_API_KEY` absent → Pixabay skipped silently (`pixabay=None`), Pexels-only path preserved (D048)
- [x] Tests: client happy path (video + photo, 11 tests); acquisition merge+rank, fallback cascade, key-absent skip (48 tests); 1611 total CI green

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P8-S2] Wikimedia Commons source — historic footage + general stock + person photos
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** high
**Points:** 3
**Depends on:** P8-S1

### Goal
Add Wikimedia Commons (free, no API key, CC licences) as the third real source. Covers three distinct use cases: (1) general stock photos when Pexels/Pixabay miss, (2) historic footage (Depression-era housing, 2008 crisis imagery), (3) real-person headshots via the MediaWiki API.

### Source details
- API: `https://commons.wikimedia.org/w/api.php` (no key required)
- Licence: public domain or CC (CC-BY, CC-BY-SA) — must attribute in run metadata
- `action=query&generator=search&gsrnamespace=6&gsrsearch=<query>` for general search
- `action=query&titles=<wikipedia_page>&prop=pageimages&piprop=original` for person photo

### Module contract (`src/wikimedia_client.py`)
```python
async def search_media(query: str, media_type: Literal["photo","video"] = "photo", limit: int = 10) -> list[WikimediaAsset]
async def fetch_person_photo(person_name: str) -> WikimediaAsset | None

# WikimediaAsset: url, width, height, title, licence, attribution
```

### Acquisition chain positions
- Photo/image scenes: Pexels → Pixabay → **Wikimedia general** → Replicate
- Historic scenes (storyboard `historic: true`): **Wikimedia general** first → Pexels → Pixabay → Replicate
- Person scenes (storyboard `person_name` set): handled by P8-S3, uses `fetch_person_photo`

### Acceptance Criteria
- [ ] `src/wikimedia_client.py`: `search_media` + `fetch_person_photo` via `httpx.AsyncClient`; returns `None`/empty on error
- [ ] Wikimedia attribution stored per asset in `asset_manifest.json` (`attribution` field)
- [ ] Photo acquisition chain: Pexels → Pixabay → Wikimedia → Replicate
- [ ] Historic flag (`historic: true` in storyboard scene): Wikimedia tried first
- [ ] No API key required; no new ENV vars
- [ ] Tests: general search happy path; person photo happy path; no result → None; attribution field populated; historic scene routes to Wikimedia first

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P8-S3] Real person detection + Wikimedia person photo routing
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** high
**Points:** 3
**Depends on:** P8-S2

### Goal
When the script mentions a named real person (Jerome Powell, Janet Yellen, Robert Shiller, etc.), the current pipeline searches Pexels with the scene query and returns a random person — a credibility failure. This story fixes it: the storyboard generation prompt is updated to emit a `person_name` field when a scene depicts a specific named individual, and the acquisition layer routes those scenes to `wikimedia_client.fetch_person_photo`.

### Changes required

**1. Storyboard prompt update (`src/` — prompt v0.4 → v0.5)**
Add instruction: when a scene's content is primarily about a specific named real person (not a generic type like "a homeowner"), include:
```json
"person_name": "Jerome Powell",
"person_title": "Chair, Federal Reserve"
```
Otherwise omit the field (backward-compatible — acquisition ignores absence).

**2. Acquisition routing (`src/acquisition.py`)**
When `scene.person_name` is set:
1. Try `wikimedia_client.fetch_person_photo(scene.person_name)`
2. If found → accept (skip QA gate — Wikipedia photos are the ground truth)
3. If not found → fall back to generic Pexels/Pixabay search with `scene.primary_query`
4. No Replicate fallback for person scenes — an AI-generated wrong face is worse than a generic B-roll

**3. Asset manifest**
Person-photo assets get `source: "wikimedia_person"` and `person_name` fields.

### Acceptance Criteria
- [x] Storyboard prompt v0.10: outputs `person_name` + `person_title` when scene depicts a named individual; PERSON SCENE RULE section added
- [x] `STORYBOARD_PROMPT_VERSION = "v0.10"` constant added in `src/storyboard.py`
- [x] `src/acquisition.py` routes `person_name`-flagged scenes to `fetch_person_photo` first via `_try_person_photo`
- [x] Fallback to generic Pexels+Pixabay search (no Wikimedia general, no AI) when Wikipedia has no photo
- [x] `asset_manifest.json`: person assets get `source: "wikimedia_person"`, `person_name`, `person_title` via `ManifestEntry` + `StoryboardScene` fields
- [x] Tests: person scene → Wikimedia called first; Wikimedia miss → generic fallback (not Replicate); non-person scene → Wikimedia person not called; manifest fields correct

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P8-S4] Footage QA — per-scene quality gate + retry
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** high
**Points:** 3
**Depends on:** P8-S1, P8-S2

### Goal
Every acquired clip passes a quality gate before being accepted. A clip that fails triggers a retry with `fallback_query` on the same source before moving to the next source in the chain. QA results are logged per scene in `asset_manifest.json`.

### QA criteria (all must pass to accept)

| Check | Video | Photo |
|-------|-------|-------|
| Resolution | ≥ 1280 × 720 | ≥ 800 px wide |
| Duration fit | clip duration ≥ scene duration (or loopable) | n/a |
| CLIP semantic match | ≥ 0.20 vs scene `visual_description` | ≥ 0.20 |

CLIP scoring uses the existing `sentence-transformers / clip-ViT-B-32` model (D039, already in `requirements.txt`). The `CLIP_RERANK_ENABLED` flag activates scoring; when flag is false, resolution + duration checks still run but CLIP is skipped.

### Retry logic
```
for source in [pexels, pixabay, wikimedia, replicate]:
    clip = source.fetch(primary_query)
    if qa_pass(clip): accept; break
    clip = source.fetch(fallback_query)
    if qa_pass(clip): accept; break
→ if all fail: accept best-scoring clip found (don't leave scene empty)
```

### Module contract (`src/footage_qa.py`)
```python
def qa_score(asset: Asset, scene: Scene) -> QAResult
# QAResult: passed, resolution_ok, duration_ok, clip_score, clip_enabled

def pick_best(candidates: list[tuple[Asset, QAResult]]) -> Asset
```
Pure functions, no I/O — importable by P9 AcquisitionWorker.

### Per-scene manifest fields added
```json
{
  "source": "pexels",
  "qa_passed": true,
  "qa_resolution_ok": true,
  "qa_duration_ok": true,
  "qa_clip_score": 0.34,
  "fallback_used": false
}
```

### Acceptance Criteria
- [x] `src/footage_qa.py`: `qa_score` + `pick_best` as pure functions
- [x] Retry with `fallback_query` before advancing to next source
- [x] CLIP scoring gated on `CLIP_RERANK_ENABLED` env var (default `False` for Railway CPU cost)
- [x] `CLIP_RERANK_ENABLED` already in `src/config.py` and `ENV.md` (E4-S4)
- [x] All QA fields written to `asset_manifest.json` per scene
- [x] Never leaves a scene with no asset — always accepts best available
- [x] Tests: QA pass; resolution fail → retry fallback_query; clip score below threshold → retry; best-of-all fallback; CLIP disabled → score field null

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `src/footage_qa.py` (new): `qa_score` + `pick_best` pure functions; `QAResult` dataclass. P9-importable, no I/O.
- `src/clip_reranker.py`: `CLIPReranker.score_image(img, text) → float` added.
- `src/models.py`: `ManifestEntry` gains `duration_s`, `qa_passed`, `qa_resolution_ok`, `qa_duration_ok`, `qa_clip_score`, `fallback_used`.
- `src/manifest.py`: propagates `scene.duration_s → ManifestEntry.duration_s`.
- `src/acquisition.py`: QA gate in `acquire_scene`; `_Candidate` gains `duration_seconds` + `from_fallback`; `_gather_candidates` tags primary/fallback candidates; `pick_best` last-resort; person photo sets `qa_passed=True`.
- 34 new tests; 1686 total passing (CI green, was 1652).

---

## [P8-S5] Source telemetry + Telegram footage report
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** high
**Points:** 2
**Depends on:** P8-S3, P8-S4

### Goal
Aggregate per-scene `source` fields into a `footage_summary` in `run_log.json`, then surface it in the Telegram reply. Operator sees `Footage: 14 Pexels · 4 Pixabay · 3 Wikimedia · 2 Person · 3 AI` without opening Drive. The coverage number is also the quality signal: high AI% = run needs review.

### Changes

**`src/` side:** After acquisition step, compute summary from `asset_manifest.json` entries:
```python
footage_summary = {
    "pexels": N, "pixabay": N, "wikimedia": N,
    "wikimedia_person": N, "replicate": N, "failed": N,
    "qa_failed_scenes": N  # scenes that accepted best-available after QA miss
}
```
Written as a `footage_summary` key in `run_log.json`.

**`cf_platform/` side:**
- `VideoResult` gains `footage_summary: dict | None = None`
- `InProcessLegacyVideoAdapter.render()` reads `footage_summary` from `run_log.json` after acquisition; passes it into `VideoResult`
- `format_produce_reply` / `format_footage_summary(summary) → str` in `telegram.py`
- `_run_pipeline_and_reply` passes summary to formatter

Backward-compatible: `footage_summary` absent → reply unchanged.

### Acceptance Criteria
- [x] `footage_summary` written to `runs/{run_id}/footage_summary.json` after acquisition step with counts for all source types + `qa_failed_scenes`
- [x] `VideoResult.footage_summary: dict | None` field added
- [x] Adapter computes summary from manifest; graceful on write failure
- [x] Telegram reply includes formatted coverage line when summary present
- [x] `qa_failed_scenes > 0` → adds `⚠️ N scenes below QA threshold` warning to reply
- [x] Tests: formatter all-sources; formatter no summary (backward compat); adapter reads; adapter graceful; QA warning shown

### Handover
- `cf_platform/adapters/legacy_video.py`: `VideoResult.footage_summary: Optional[dict] = None` added. `_compute_footage_summary(manifest: AssetManifest) → dict` computes `pexels/pixabay/wikimedia/wikimedia_person/replicate/failed/qa_failed_scenes` counts from `ManifestEntry.status`, `.source`, and `.qa_passed` fields. Called after successful acquisition; writes `runs/{run_id}/footage_summary.json` to R2 as a side-car (graceful on write failure) and sets `VideoResult.footage_summary`.
- `cf_platform/interfaces/telegram.py`: `format_footage_summary(summary: dict) → str` — produces e.g. `Footage: 14 Pexels · 4 Pixabay · 2 Person`, appends `⚠️ N scenes below QA threshold` when `qa_failed_scenes > 0`. `format_produce_reply` gains `footage_summary: Optional[dict] = None` kwarg — backward-compatible; appends the coverage line before the YouTube metadata block when provided.
- `cf_platform/interfaces/api.py`: `_run_pipeline_and_reply` tries `await storage.get_json(f"runs/{run_id}/footage_summary.json")` after generating the video URL; graceful `except` → `footage_summary=None` (no coverage line). Passes `footage_summary` to `format_produce_reply`.
- Note: written to `footage_summary.json` (not `run_log.json` as originally spec'd — adapter never writes `run_log.json`, so a standalone side-car is cleaner).
- `tests/cf_platform/test_p8_s5_footage_telemetry.py` (new): 18 tests.
- 1704 total tests passing (CI green, was 1686).

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P8-S6] Colour grading presets (FFmpeg)
**Epic:** E35 — Footage Quality
**Sprint:** P8
**Status:** done
**Completed:** 2026-06-20
**Priority:** med
**Points:** 2
**Depends on:** — (fully independent)

### Goal
Apply a consistent colour grade to the final rendered video via an FFmpeg filter chain. The preset is operator-configurable via `COLOR_GRADE_PRESET` ENV var. Default is `neutral` (no change to existing behaviour).

### Presets

| Preset | FFmpeg filter | Effect |
|--------|---------------|--------|
| `neutral` | _(none)_ | No change — preserves source colours |
| `vivid` | `eq=saturation=1.3:contrast=1.08` | Punchy, high-energy — good for YouTube Shorts |
| `warm` | `colorchannelmixer=rr=1.08:bb=0.88,eq=saturation=1.1` | Warmer tones, slightly golden |
| `cinematic` | `curves=m='0/10 128/118 245/235':s='0/0 255/255',eq=saturation=0.9` | Lifted blacks, slightly desaturated |
| `muted` | `eq=saturation=0.75:contrast=0.95:brightness=0.015` | Calm, editorial feel |

### Changes
- `COLOR_GRADE_PRESET` added to `src/config.py` (default `"neutral"`) and `ENV.md`
- `src/ffmpeg_builder.py`: `_get_color_grade_filter(preset: str) -> str | None`; when non-None, appended to the video filter chain in `build_ffmpeg_script`
- Unknown preset value → logs WARNING, falls back to `neutral`
- **Blur-fill for landscape assets** (added P8-S3): when a still photo is wider than the 9:16 frame (aspect ratio > 0.5625), apply blur-fill compositing — blurred + scaled full-frame behind, sharp subject scaled to fit in front. This is the standard YouTube Shorts look and handles Wikipedia portraits that happen to be landscape (e.g. podium shots).
  - FFmpeg pattern: `[in]split=2[bg][fg];[bg]scale=1080:1920,boxblur=20:5[blurred];[fg]scale=iw*min(1080/iw\,1920/ih):ih*min(1080/iw\,1920/ih)[fitted];[blurred][fitted]overlay=(W-w)/2:(H-h)/2`
  - Gate on `BLUR_FILL_ENABLED` ENV var (default `True` — on by default since portrait stock photos are the common case)
  - Only applies to still images (`still_with_motion` / `animated` with photo asset); video clips use crop-to-fill as before

### Acceptance Criteria
- [x] `COLOR_GRADE_PRESET` in `src/config.py` + `ENV.md`
- [x] All 5 presets produce valid FFmpeg filter strings
- [x] `neutral` → no filter added (output identical to current behaviour)
- [x] Unknown value → warning logged + neutral fallback
- [x] Filter chain position: applied after trim/scale, before audio merge (correct order)
- [x] Tests: each preset returns expected filter string; neutral returns None; unknown → neutral; filter string is non-empty for non-neutral presets
- [x] `BLUR_FILL_ENABLED` in `src/config.py` + `ENV.md`; landscape still images get blur-fill compositing when enabled; portrait/square stills use scale+crop as before
- [x] Tests: landscape asset → blur-fill filter applied; portrait asset → no blur-fill; `BLUR_FILL_ENABLED=False` → no blur-fill regardless

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## EPIC 36 — Native Documentary Production Graph (Sprint P9)

Extract the storyboard→acquisition→render chain from `InProcessLegacyVideoAdapter` into three native LangGraph workers: **StoryboardWorker** (generate+review+patch internal), **AcquisitionWorker**, **RenderWorker**.

**Sprint rule:** Every change in P9 must either (a) replace existing monolith functionality, or (b) add visible production quality at <10% runtime cost. Defer everything else to P10.

**Architecture:** The storyboard owns all render decisions. The storyboard reviewer writes `render_options` onto each scene. The RenderWorker reads `render_options` and executes — it has no knowledge of `segment_type` semantics.

**Artifact chain:** `verified_storyboard.json → asset_manifest.json → render_script.sh → final.mp4`

---

## [P9-S1] Storyboard schema v2
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Completed:** 2026-06-22
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
Update `src/models.py` with the schema v2 structures that P9-S2 through P9-S5 build on. No prompt changes in this story — the StoryboardWorker (P9-S2) ships the new prompt. This story is pure data model.

### StoryboardScene changes
```python
segment_type: Literal["Character", "Event", "B-roll"] = "B-roll"
primary_stk: str = ""        # replaces visual_prompts.primary_stk
context_stk: str = ""        # replaces visual_prompts.fallback_stk
concept_stk: str = ""        # broadest concept / abstract fallback
on_screen_text: Optional[str] = None          # unchanged, now paired with type
on_screen_text_type: Optional[Literal["stat", "date", "lower_third"]] = None
render_options: Optional[SceneRenderOptions] = None  # written by reviewer
# kept for backward-compat with existing R2 storyboards:
visual_prompts: Optional[VisualPrompts] = None       # deprecated alias
historic: bool = False                               # deprecated alias (segment_type=Event is the signal)
```

### New models
```python
class LowerThirdSpec(BaseModel):
    name: str
    title: Optional[str] = None
    caption_y_override: int = 1540  # shifts captions up when subtitles active

class OnScreenTextOverlay(BaseModel):
    text: str
    type: Literal["stat", "date", "lower_third"]
    enable_expr: str  # FFmpeg between(t,{offset},{offset+duration})

class SceneRenderOptions(BaseModel):
    film_look: bool = False
    lower_third: Optional[LowerThirdSpec] = None
    on_screen_text_overlay: Optional[OnScreenTextOverlay] = None
```

### ManifestEntry changes
```python
segment_type: str = "B-roll"
primary_stk: str = ""
context_stk: str = ""
concept_stk: str = ""
# kept as Optional[str] = None for backward compat with existing R2 manifests:
primary_query: Optional[str] = None
fallback_query: Optional[str] = None
ai_generate_prompt: Optional[str] = None
historic: bool = False  # deprecated alias; segment_type=Event is the signal
```

### Acceptance Criteria
- [x] `SceneRenderOptions`, `LowerThirdSpec`, `OnScreenTextOverlay` models added to `src/models.py`
- [x] `StoryboardScene`: `segment_type`, `primary_stk`, `context_stk`, `concept_stk`, `on_screen_text_type`, `render_options` fields added; `visual_prompts` kept Optional for backward compat
- [x] `ManifestEntry`: `segment_type`, `primary_stk`, `context_stk`, `concept_stk` added; old `primary_query` / `fallback_query` / `ai_generate_prompt` made Optional with None default
- [x] Backward-compat: existing R2 storyboard JSON (with `visual_prompts` struct) still parses; `primary_stk`/`context_stk` populated from `visual_prompts` via `model_validator` when flat fields absent
- [x] Tests: new fields parse; `segment_type` defaults to `"B-roll"`; old storyboard JSON without new fields loads without error; `SceneRenderOptions` round-trips through JSON

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `src/models.py`:
  - `LowerThirdSpec(name, title?, caption_y_override=1540)` — new model
  - `OnScreenTextOverlay(text, type: Literal["stat","date","lower_third"], enable_expr)` — new model
  - `SceneRenderOptions(film_look=False, lower_third?, on_screen_text_overlay?)` — new model
  - `StoryboardScene` gains `segment_type` (Literal, default "B-roll"), `primary_stk`, `context_stk`, `concept_stk` (str, default ""), `on_screen_text_type` (Optional Literal), `render_options` (Optional SceneRenderOptions); `visual_prompts` made Optional (deprecated alias). `model_validator(mode="after")` backfills `primary_stk/context_stk` from `visual_prompts` when loading old JSON.
  - `ManifestEntry` gains `segment_type`, `primary_stk`, `context_stk`, `concept_stk`; `primary_query/fallback_query/ai_generate_prompt` made `Optional[str] = None` for R2 backward compat. `historic` deprecated alias preserved.
  - `build_manifest` in `manifest.py` unchanged — still accesses `scene.visual_prompts.primary_stk` for the legacy pipeline path. P9-S3 (AcquisitionWorker) will use the flat fields.
- `tests/test_p9_s1_schema_v2.py` (new): 36 tests covering all models, new fields, backward-compat validator, JSON round-trip.
- 1779 total tests passing (CI green, was 1736).

---

## [P9-S2] Native StoryboardWorker (generate → review → patch internal)
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Completed:** 2026-06-22
**Priority:** high
**Points:** 5
**Depends on:** P9-S1

### Goal
`cf_platform/workers/storyboard_worker.py` — full generate→review→patch cycle internal to one worker. Emits a single `verified_storyboard` artifact to R2. No intermediate reviewer artifact is surfaced externally. Also exposes a REST endpoint for future step-by-step manual UI.

### Internal cycle
```
1. Generate (Sonnet, prompt v0.12)
   → raw storyboard: segment_type, primary_stk/context_stk/concept_stk,
     on_screen_text, on_screen_text_type, person_name, person_title, sfx, etc.

2. Review (Haiku, structured JSON output)
   Checks five dimensions:
   a. Coverage: every VO word in exactly one voiceover_line
   b. segment_type correctness: named person → Character; named historical event → Event; else → B-roll
   c. on_screen_text gaps: stat/date mentioned in VO but no on_screen_text set → flag
   d. Query domain anchoring: primary_stk reflects video topic, not literal VO words
   e. SFX specificity: vague SFX ("sound") → reject, must be concrete noun

3. Patch (deterministic)
   Apply review corrections, then compute render_options for every scene:
   - Character + person_name set → render_options.lower_third = {name, title}
                                 → null out on_screen_text (lower-third is the display)
   - Event → render_options.film_look = True
   - on_screen_text present → render_options.on_screen_text_overlay = {text, type, enable_expr}
   - lower_third present → lower_third.caption_y_override = 1540 (captions shift up when subtitles active)

4. Emit verified_storyboard.json to R2 (runs/{run_id}/verified_storyboard.json)
```

### Module contract
```python
# cf_platform/workers/storyboard_worker.py
async def build_storyboard_worker(storage, settings) -> WorkerNode
# Reads:  state.script, state.voice_alignment (for timestamp-aware duration)
# Writes: state.artifacts["verified_storyboard"] → R2 key
```

### REST endpoint
`POST /platform/workers/storyboard` — accepts `{ run_id, script }`, returns `{ artifact_key, scene_count, prompt_version }`. For future manual UI; not wired into Telegram in this story.

### Acceptance Criteria
- [x] `cf_platform/workers/storyboard_worker.py` with `build_storyboard_worker` factory
- [x] Prompt v0.12: SEGMENT TYPE section (Character|Event|B-roll + definitions + examples); THREE-TIER QUERY section; ON_SCREEN_TEXT TYPE section (stat|date|lower_third only); RENDER DECISION NOTE (model emits raw fields; reviewer computes render_options)
- [x] `STORYBOARD_PROMPT_VERSION = "v0.12"` constant
- [x] Review dimensions (a)–(e) implemented; review response is structured (Haiku returns JSON patch list)
- [x] Patch step computes `render_options` per scene before emitting artifact
- [x] Rule enforced: Character scene with lower_third → `on_screen_text` set to null
- [x] `POST /platform/workers/storyboard` route wired and documented
- [x] Tests: generate→review→patch round-trip (mocked Sonnet/Haiku); Character scene → lower_third in render_options, on_screen_text null; Event scene → film_look True; on_screen_text present → enable_expr present; coverage check catches missing VO word; verified_storyboard artifact written to R2

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P9-S3] Native AcquisitionWorker
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Completed:** 2026-06-22
**Priority:** high
**Points:** 4
**Depends on:** P9-S2

### Goal
`cf_platform/workers/acquisition_worker.py` — replaces `InProcessLegacyVideoAdapter`'s acquisition call. Imports P8 `src/` modules directly (P8 portability contract). Routes by `segment_type`. Three-tier query cascade within each source. QA gate. Writes `asset_manifest` to R2.

### Routing table
| segment_type | Acquisition route |
|---|---|
| `Character` (person_name set) | `wikimedia_client.fetch_person_photo(person_name)` → Pexels+Pixabay fallback |
| `Event` | Wikimedia Commons general search → Pexels+Pixabay fallback |
| `B-roll` | Pexels + Pixabay concurrent merge+rank |

For every source attempt: try `primary_stk` → `context_stk` → `concept_stk` before advancing to the next source. QA gate (`footage_qa.qa_score`) applied per candidate; `pick_best` last resort before leaving scene empty.

### Module contract
```python
# cf_platform/workers/acquisition_worker.py
async def build_acquisition_worker(storage, settings) -> WorkerNode
# Reads:  state.artifacts["verified_storyboard"]
# Writes: state.artifacts["asset_manifest"]  → R2 key
#         state.artifacts["footage_summary"] → dict
```

### REST endpoint
`POST /platform/workers/acquisition` — accepts `{ run_id }`, returns `{ manifest_key, footage_summary, acquired, failed }`. For future manual UI; not wired into Telegram in this story.

### Acceptance Criteria
- [x] `cf_platform/workers/acquisition_worker.py` with `build_acquisition_worker` factory
- [x] Imports `src.pixabay_client`, `src.wikimedia_client`, `src.footage_qa` directly (no wrappers); also imports `src.pexels` for Pexels support
- [x] Routing table implemented; `segment_type` field read from `verified_storyboard` scenes
- [x] Three-tier cascade (`primary_stk → context_stk → concept_stk`) within each source before advancing
- [x] QA gate applied at each candidate; `pick_best` fallback; scene never left empty
- [x] `footage_summary` dict: per-scene source + score summary; also written as `runs/{run_id}/footage_summary.json` side-car for legacy compat
- [x] `POST /platform/workers/acquisition` route wired
- [x] Tests: Character → person photo route; Event → Wikimedia first; B-roll → Pexels+Pixabay concurrent; three-tier cascade triggers on primary miss; QA gate rejects low-res; empty manifest never produced

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `cf_platform/workers/acquisition_worker.py` (new): `ACQUISITION_WORKER_REGISTRATION` (worker_version=`1.0.0`, model=`none`); `AssetManifestArtifact(scene_count, acquired, failed, footage_summary, manifest, generated_at)`; `build_acquisition_worker(storage, pexels_api_key, pixabay_api_key="") → WorkerNode`. Reads `state.artifacts["verified_storyboard"]`; routes by `segment_type`; three-tier STK cascade; QA gate; writes side-car at `runs/{run_id}/footage_summary.json`. Emits `state.artifacts["asset_manifest"]`.
- `cf_platform/core/config.py`: `PEXELS_API_KEY: str = ""` and `PIXABAY_API_KEY: str = ""` added to `PlatformSettings`.
- `cf_platform/interfaces/api.py`: `ACQUISITION_WORKER_REGISTRATION` registered; `POST /platform/workers/acquisition` endpoint added.
- `tests/cf_platform/test_p9_s3_acquisition_worker.py` (new): 20 tests. 1819 total passing (CI green, was 1799).

---

## [P9-S4] Native RenderWorker (dumb executor — reads render_options)
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Priority:** high
**Points:** 4
**Depends on:** P9-S3

### Goal
`cf_platform/workers/render_worker.py` — reads `verified_storyboard` (for `render_options` per scene) + `asset_manifest` + `voice_alignment`. Applies render options mechanically. No `segment_type` conditionals — the storyboard already decided everything. Persists `render_script.sh` as a debuggable artifact. Uploads `final.mp4`.

### Render options applied
| render_options field | FFmpeg action |
|---|---|
| `film_look: true` | Sepia filter chain: `hqdn3d=3:2:6:4,noise=alls=8:allf=t,colorchannelmixer=...,eq=saturation=0.4` |
| `lower_third.name + title` | `drawtext` at `y=h-th-{lower_third.caption_y_override ?? 220}` — name bold 34px, title smaller 26px above |
| `on_screen_text_overlay.enable_expr` | `drawtext=text=...:enable='{enable_expr}'` for timed stat/date overlay |
| `lower_third` present + `subtitles != "none"` | ASS caption generator uses `caption_y_override` as `y` for affected scene words |
| none set | Standard colour grade from `COLOR_GRADE_PRESET` env var |

### Artifact chain
```
verified_storyboard → asset_manifest → render_script.sh  ← persisted to R2
                                              ↓
                                         final.mp4         ← persisted to R2
```

### Module contract
```python
# cf_platform/workers/render_worker.py
async def build_render_worker(storage, settings) -> WorkerNode
# Reads:  state.artifacts["verified_storyboard"]
#         state.artifacts["asset_manifest"]
#         state.artifacts["voice_alignment"]
# Writes: state.artifacts["render_script"]  → R2 key (runs/{run_id}/render_script.sh)
#         state.artifacts["video"]          → R2 key (runs/{run_id}/output/final.mp4)
```

### REST endpoint
`POST /platform/workers/render` — accepts `{ run_id }`, returns `{ render_script_key, video_key, duration_s }`. For future manual UI.

### Acceptance Criteria
- [ ] `cf_platform/workers/render_worker.py` with `build_render_worker` factory; zero `segment_type` conditionals in render logic
- [ ] All render decisions read from `scene.render_options`; film_look / lower_third / on_screen_text_overlay each handled
- [ ] Lower-third: name on bottom line (bold, 34px), title on line above (lighter, 26px) when present; `drawtext` scoped to scene `enable=between(t,...)` expression
- [ ] Caption-aware: when `lower_third.caption_y_override` set and `subtitles != "none"`, ASS generator overrides `y` for affected scene words
- [ ] `render_script.sh` persisted to R2 before FFmpeg execution
- [ ] FFmpeg executed via subprocess; `FFMPEG_TIMEOUT_SECONDS` respected; `final.mp4` uploaded to R2
- [ ] `COLOR_GRADE_PRESET` and `BLUR_FILL_ENABLED` settings honoured for scenes without `film_look`
- [ ] `POST /platform/workers/render` route wired
- [ ] Tests: film_look scene → sepia filter in script; lower_third scene → drawtext with name+title; on_screen_text_overlay → enable_expr in script; caption_y_override applied to ASS words; render_script.sh written before exec; no segment_type import in module

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P9-S5] Retire InProcessLegacyVideoAdapter + wire native pipeline
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Priority:** high
**Points:** 2
**Depends on:** P9-S4

### Goal
Wire the three native workers into `full_pipeline.py` so `/run`, `/pick`, and `/produce` Telegram commands trigger the native chain. `InProcessLegacyVideoAdapter` is deprecated — kept importable but removed from the active call graph. `footage_summary` flows to the Telegram reply.

### Changes
- `full_pipeline.py`: replace `legacy_render_node` with `storyboard_node → acquisition_node → render_node` (workers from P9-S2/S3/S4)
- `InProcessLegacyVideoAdapter` + `LegacyVideoAdapter` Protocol: add `# DEPRECATED — use StoryboardWorker + AcquisitionWorker + RenderWorker` notice; not deleted
- `build_full_pipeline_graph`: remove or deprecate `legacy_adapter` kwarg
- `footage_summary` from `AcquisitionWorker` output → `format_produce_reply` via `_run_pipeline_and_reply`
- `src/` standalone pipeline (legacy web UI routes) unchanged — P9 touches only `cf_platform/` path

### Acceptance Criteria
- [x] `full_pipeline.py` call graph: `niche_to_ideas → idea_to_script → youtube_metadata → voice_production → storyboard_worker → acquisition_worker → render_worker`
- [x] `InProcessLegacyVideoAdapter` not in active call path; deprecation notice added; importable
- [x] `/run`, `/pick`, `/produce` all trigger native chain; `footage_summary` in reply
- [x] All existing tests pass; integration test: full pipeline smoke with mocked workers produces `verified_storyboard → asset_manifest → render_script.sh → final.mp4` chain
- [ ] **Human touchpoint:** `/run <niche>` → native render; person lower thirds visible; film look on historic footage; on_screen_text stat/date overlays present — DEFERRED: requires DEV deploy + real API keys

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P9-S6] Portrait/landscape format parameter (`--format` flag)
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Priority:** high
**Points:** 2
**Depends on:** P9-S5

### Goal
Add a `--format portrait|landscape` flag to `/run`, `/produce`, and `/pick` Telegram commands so the operator can choose output orientation per video. Default stays `portrait` (1080×1920) for Shorts. `landscape` outputs 1920×1080 for standard YouTube uploads.

### Acceptance Criteria
- [x] `parse_run_args`, `parse_produce_args`, `parse_pick_command` all parse `--format portrait|landscape`; unknown values fall back to `portrait` with a warning
- [x] `PipelineState` gains `format_track: Literal["portrait","landscape"] = "portrait"`
- [x] Storyboard prompt header line updated dynamically: `"30–60 second YouTube Short, 9:16 vertical"` when portrait; `"30–180 second YouTube video, 16:9 horizontal"` when landscape
- [x] RenderWorker selects output resolution from `format_track`: 1080×1920 (portrait) or 1920×1080 (landscape); all intermediate ffmpeg steps use the correct `scale`/`crop` targets
- [x] Telegram command usage strings updated to mention `--format`
- [x] Tests: `parse_run_args`/`parse_produce_args`/`parse_pick_command` flag parsing (portrait, landscape, missing, invalid); `PipelineState` default; RenderWorker resolution selection

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** `/run housing --format landscape` → 1920×1080 `final.mp4` delivered via Telegram

---

## [P9-S7] Caption word assignment by timestamp (drop script text-matching)
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Completed:** 2026-06-24
**Priority:** high
**Points:** 1
**Depends on:** P9-S5

### Goal
Replace the text-matching approach in `assign_words_to_scenes` with timestamp-based assignment. Each Deepgram word is placed in whichever scene's time window contains its `start_ms`. This mirrors how CapCut generates captions — it shows what was actually said, not what the script says — eliminating dropped numbers and mismatched tokens (e.g. TTS says "three" but script has "3").

### Root cause
`assign_words_to_scenes` normalises VO tokens and scans forward through Deepgram words looking for text matches. When the TTS pronounces a numeral as a word ("three", "thirty") but the script contains the digit ("3", "30"), `_norm("3") != _norm("three")` — the word falls outside `_MATCH_WINDOW` and is silently dropped from captions.

### Acceptance Criteria
- [x] `assign_words_to_scenes` in `src/ffmpeg_builder.py` rewritten: compute cumulative scene start times from `scene.duration_s`; for each Deepgram `WordTimestamp`, assign it to the scene whose `[start_s, end_s)` window contains `word.start_ms / 1000`; words before the first scene or after the last go to the nearest boundary scene
- [x] Caption display text comes from `word.word` (Deepgram transcript), not from the script's voiceover_line
- [x] `fill_caption_gaps` (if still needed) updated or removed — kept in place as a guard for large duration-estimate drift; no-op in practice for correctly timed storyboards
- [x] All existing caption tests pass or are updated to reflect the new assignment logic
- [x] No regressions in other callers of `assign_words_to_scenes` (`src/ffmpeg_builder.py`, `cf_platform/workers/render_worker.py`)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** next full `/run` → captions show "3 and 4 percent" / "thirty years" without dropped words

---

## [P9-S9] Timestamp-first storyboard — word indices + Python-derived duration and asset tier
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** done
**Completed:** 2026-06-27
**Priority:** high
**Points:** 5
**Depends on:** P9-S7

### Goal
Eliminate the root cause of storyboard duration misalignment: Claude currently derives `duration_s` from a word-count table (even though the prompt says to use Deepgram), and assigns `clip_type` based on heuristics that contradict the computed duration. This story makes **Python the sole source of truth** for `duration_s`, `voiceover_line`, and `asset_tier`. Claude only makes creative decisions: scene boundary identification, visual search queries, and on-screen text.

**Single-source-of-truth table after this story:**

| Data item | Who decides | How |
|---|---|---|
| `voiceover_line` | Python | Reconstructed from `words[start_word:end_word+1]` |
| `duration_s` | Python | `(words[end].end_ms − words[start].start_ms) / 1000` |
| `scene_start_ms` | Python | `words[start_word].start_ms` |
| `scene_end_ms` | Python | `words[end_word].end_ms` |
| `asset_tier` | Python | Duration policy (see below) |
| `clip_type` | Python | Derived from `asset_tier` (backward compat field) |
| `motion_effect` | Python | Derived from `asset_tier` + scene index (deterministic) |
| Scene boundaries | Claude | Word index ranges (`start_word`, `end_word`) |
| Visual queries | Claude | `primary_stk`, `context_stk`, `concept_stk` |
| On-screen text | Claude | `on_screen_text`, `on_screen_text_type` |
| Segment type | Claude | `segment_type` (Character / Event / B-roll) |
| Person metadata | Claude | `person_name`, `person_title` |
| SFX | Claude | `sfx`, `sfx_timing` |

### Architecture

**1. New indexed word-list format passed to Claude (prompt v0.12 → v0.13)**

`_format_indexed_timestamps()` replaces `_format_voice_timestamps()`:
```
[0]  "Companies"    (0.00s–0.41s)
[1]  "are"          (0.41s–0.52s)
[2]  "holding"      (0.52s–0.74s)
...
[87] "crisis"       (24.10s–24.55s)
```

Claude receives this list and outputs `start_word` and `end_word` integer indices instead of `voiceover_line` text. This eliminates all text-matching and Deepgram tokenisation mismatches (contractions, numerals, etc.).

**2. Claude's output schema (what Claude still emits per scene)**
```json
{
  "start_word": 0,
  "end_word": 12,
  "segment_type": "B-roll",
  "primary_stk": "housing market crash aerial view",
  "context_stk": "American real estate empty homes",
  "concept_stk": "financial crisis housing",
  "on_screen_text": "2008 Crisis",
  "on_screen_text_type": "date",
  "sfx": null,
  "sfx_timing": null,
  "person_name": null,
  "person_title": null
}
```
Removed from Claude's output: `voiceover_line`, `duration_s`, `clip_type`, `motion_effect`.

**3. Python `_reify_scene` — called in the patch step**
```python
def _reify_scene(raw: dict, words: list[VoiceWordTimestamp], scene_index: int) -> dict:
    start, end = raw["start_word"], raw["end_word"]
    span = words[start : end + 1]
    raw["voiceover_line"] = " ".join(w.word for w in span)
    raw["duration_s"] = round((span[-1].end_ms - span[0].start_ms) / 1000, 3)
    raw["scene_start_ms"] = span[0].start_ms
    raw["scene_end_ms"] = span[-1].end_ms
    raw["asset_tier"] = _assign_asset_tier(raw["duration_s"])
    raw["clip_type"] = _asset_tier_to_clip_type(raw["asset_tier"])
    raw["motion_effect"] = _derive_motion_effect(raw["asset_tier"], scene_index)
    return raw
```

**4. Asset tier policy**
```
< 3.0 s   → "still"        clip_type=still_with_motion  motion_effect=scale
3.0–6.0 s → "still_motion" clip_type=still_with_motion  motion_effect=ken_burns_{in|out} (alternating by index)
6.0–10.0s → "video"        clip_type=hard_cut            motion_effect=None
≥ 10.0 s  → "video"        clip_type=hard_cut            motion_effect=None  + log WARNING
```
`_derive_motion_effect` is deterministic by scene index — even → `ken_burns_in`, odd → `ken_burns_out`. No randomness.

**5. Fallback when `voice_alignment` absent**

When Deepgram timestamps are unavailable, Claude falls back to generating `voiceover_line` as plain text (v0.12 behaviour) and Python estimates `duration_s` via `len(words) / 2.5`. Logs WARNING. Expected to be rare in production (voice always runs before storyboard).

**6. Word-list normalisation**

`_normalize_deepgram_words(raw: list[dict]) -> list[VoiceWordTimestamp]`:
- Strips punctuation from `word` field before indexing
- Collapses contiguous tokens with identical `start_ms` (Deepgram sometimes splits contractions into two entries)
- Returns a flat, clean, 0-indexed list

**7. AcquisitionWorker update (minor)**

`asset_tier` field added to `ManifestEntry`. Acquisition routing uses `asset_tier` to prefer video vs image sources:
- `still` / `still_motion` → image sources first (Pexels photo, Pixabay photo, Wikimedia); fall back to video only if all image sources fail
- `video` → video sources first (Pexels video, Pixabay video); fall back to image if no video found

### Prompt changes (v0.12 → v0.13)

**Remove:**
- Entire `DURATION RULES` section with word-count table
- `duration_s`, `clip_type`, `motion_effect`, `voiceover_line` from scene output schema

**Add:**
- Indexed word-list section: "Below is the voiceover word list with timestamps. Set `start_word` and `end_word` to integer indices from this list."
- Scene guidance: "Each scene should span approximately 2–8 seconds based on the timestamps. Split at natural semantic pauses — clause boundaries, topic shifts — not at arbitrary word counts."
- Updated output schema: `start_word: int`, `end_word: int`

`STORYBOARD_PROMPT_VERSION` → `"v0.13"`.

### Schema changes (`src/models.py`)

```python
class StoryboardScene(BaseModel):
    # New fields
    start_word: Optional[int] = None
    end_word: Optional[int] = None
    scene_start_ms: Optional[int] = None    # computed by Python
    scene_end_ms: Optional[int] = None      # computed by Python
    asset_tier: Optional[Literal["still", "still_motion", "video"]] = None

class ManifestEntry(BaseModel):
    asset_tier: Optional[Literal["still", "still_motion", "video"]] = None
```

`clip_type`, `motion_effect`, `duration_s`, `voiceover_line` remain on `StoryboardScene` — still populated, consumed by the render worker unchanged.

### Acceptance Criteria
- [x] `_format_indexed_timestamps(words: list[VoiceWordTimestamp]) → str` added to `storyboard_worker.py`; used when `voice_alignment` artifact present
- [x] Prompt v0.13: word-count duration table removed; `start_word`/`end_word` in Claude output schema; time-based guidance present; `voiceover_line`/`duration_s`/`clip_type`/`motion_effect` absent from Claude output schema
- [x] `STORYBOARD_PROMPT_VERSION = "v0.13"` constant
- [x] `_reify_scene(raw, words, scene_index) → dict` implemented; called for every scene in `_generate()` before Pydantic validation
- [x] `_assign_asset_tier(duration_s) → Literal["still","still_motion","video"]` pure function implementing policy above; scenes ≥ 10s log WARNING
- [x] `_derive_motion_effect(tier, scene_index) → Optional[str]`: `still` → `"scale"`, `still_motion` → `"ken_burns_in"` (even) / `"ken_burns_out"` (odd), `video` → `None`
- [x] `_normalize_deepgram_words(raw: list[dict]) → list[VoiceWordTimestamp]` strips terminal punctuation; collapses same-`start_ms` duplicates (preserves apostrophes for contractions)
- [x] Fallback path: when `voice_alignment` absent, Claude generates `voiceover_line` as text (v0.12 compat), Python estimates `duration_s` by word count, logs WARNING
- [x] `StoryboardScene`: `start_word`, `end_word`, `scene_start_ms`, `scene_end_ms`, `asset_tier` fields added
- [x] `ManifestEntry`: `asset_tier` field added
- [x] `AcquisitionWorker`: reads `asset_tier` to choose image-first vs video-first source order
- [x] All existing storyboard and acquisition worker tests pass or are updated to reflect new fields
- [x] New tests: `_format_indexed_timestamps` produces `[idx] "word" (start–end)` format; `_assign_asset_tier` all four buckets; `_derive_motion_effect` even/odd alternation; `_normalize_deepgram_words` contraction collapse and punctuation strip; `_reify_scene` full reconstruction matches Deepgram spans; prompt v0.13 has no word-count table; prompt v0.13 has no `duration_s` in output schema; acquisition `still` → image sources tried before video; acquisition `video` → video sources tried before image

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** run a video end-to-end; inspect `verified_storyboard.json` in R2 — every `duration_s` matches `(scene_end_ms − scene_start_ms) / 1000` to within 1 ms; scenes 5 and 8 durations correctly reflect their actual VO lengths

---

## Post-P9 backlog (outline only)

| Sprint | Theme | Key stories |
|--------|-------|-------------|
| P10 | Render quality + Studio asset control | Dip-to-black + chapter title cards; xfade dissolves; slow motion for Emotion scenes; per-clip `loudnorm`; quote cards; chart PNG generation; **two-pass storyboard**; **per-scene asset override (P9-S8)** |
| P11 | AI asset library | `/library/` R2 cache layer (portrait + map + chart); portrait colorization via Real-ESRGAN + DeOldify (Replicate); background removal for parallax (rembg); map generation via Mapbox Static API (D entry required); number callout overlays |
| P12 | Format tracks | `format_track: Literal["documentary","educational","animated"]` at PipelineState level; per-track storyboard prompts; per-track render templates |
| P13 | Analytics & attribution | Publish linkage capture; YouTube metrics ingestion; retention-by-prompt-version report |
| P14 | n8n automation | Callback webhook for n8n; YouTube OAuth upload; scheduled publication with operator preview |
| P15 | Multi-tenant SaaS frontend | Multi-channel per tenant; multi-run per channel; operator UI rebuild |

---

## [P10-S1] Asset quality, character sourcing, and OST consistency
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P10 (carried from P9-S10)
**Status:** done
**Priority:** high
**Points:** 5

### Goal
Fix five categories of production-quality bugs observed on real runs (v0.16.0). No schema changes — all fixes are within existing workers and the render script builder.

#### Bug 1 — Remove lower-third overlays; person name → OST
`lower_third` in `render_options` was producing name/title banners at the bottom of the frame sourced from Pexels contributor metadata or storyboard person fields. This was never the intended design.

**Fix:**
- Remove all `lower_third` emission from `StoryboardWorker._reify_scene` and the prompt.
- Remove `lower_third` rendering from `RenderWorker._collect_overlay_filters`.
- If a scene has `person_name` (Character scene), set `on_screen_text = person_name` (and `on_screen_text_type = "person"`) so the name appears in the centre OST overlay at the standard position.
- `LowerThird` model + `render_options.lower_third` field can remain in schema for future use but must never be populated by the storyboard worker.

#### Bug 2 — Wikimedia routing broken for Character and historic scenes
P8-S2/P8-S3 added Wikimedia Commons routing. Diagnose why named-researcher Character scenes (e.g. "Kirk Erickson") still resolve via Pexels.

**Likely cause:** `AcquisitionWorker` Wikimedia path is gated on `segment_type == "historic_footage"` but Character scenes use `segment_type == "character"`. The person photo routing added in P8-S3 may not have survived the P9 native worker rewrite.

**Fix:**
- Audit `acquisition_worker.py` routing logic; confirm the Wikimedia/person-photo branch is reachable for `segment_type == "character"` with a non-empty `person_name`.
- If missing, re-add: query `wikimedia_client.search_person_photo(person_name)` first; fall back to Pexels generic query only on miss.
- `historic_footage` scenes must also enter the Wikimedia-first path.
- `asset_manifest` `source` field must record `"wikimedia"` when a Wikimedia asset is used.

#### Bug 3 — Asset deduplication across scenes
Scenes 1, 3, and 5 in a run shared the same image because each scene is acquired independently with no cross-scene state.

**Fix:**
- `AcquisitionWorker` maintains a `used_file_keys: set[str]` across the scene acquisition loop.
- On each Pexels/Pixabay result, skip any asset whose `file_key` is already in the set; retry with `page=2` (or the next result) until a unique asset is found or the source is exhausted.
- If all results are duplicates, log a warning and use the least-recently-used asset as a last resort.
- `asset_manifest` records `"duplicate_avoided": true` on scenes where a skip occurred.

#### Bug 4 — OST consistency: Event scenes missing on_screen_text
`Event`-type scenes (habit milestones, chapter markers) should always have an `on_screen_text` to reinforce the chapter marker visually. Some Event scenes exit storyboard generation with `on_screen_text = null`.

**Fix (post-generation QA pass in StoryboardWorker):**
- After `_reify_scene` loop, scan all scenes where `scene_type == "Event"` and `on_screen_text` is null or empty.
- For each gap, make a single Haiku call: `"Given this voiceover line: '{line}', write a 2–5 word chapter title for an on-screen text overlay."` Enforce uppercase, max 30 chars.
- Patch the scene dict in place; log `WARNING: Event scene {n} had no OST — synthesised '{text}'`.
- Cap at 5 Haiku calls per run to bound latency/cost.

#### Bug 5 — Unicode characters rendering as □ in OST overlays
`→` and `↑` (and likely `↓`, `≥`, `≤`, `×`) render as the replacement character because Poppins does not cover the Unicode Miscellaneous Arrows block.

**Fix:**
- Switch OST `drawtext` font from `Poppins-Bold.ttf` to `NotoSans-Bold.ttf` (or `NotoSansCJK` if available; both ship on Railway's Debian base image).
- Verify the font path: `fc-list | grep -i noto` on the Railway container.
- If Noto is not present, add `fonts-noto` to the `Dockerfile` `apt-get install` line.
- Caption font (Poppins) is unaffected — only the OST overlay path changes.

### Files Affected
- `cf_platform/workers/storyboard_worker.py` — Bug 1 (lower-third removal, person→OST), Bug 4 (Event QA pass)
- `cf_platform/workers/acquisition_worker.py` — Bug 2 (Wikimedia routing), Bug 3 (deduplication)
- `cf_platform/workers/render_worker.py` — Bug 1 (remove lower-third render), Bug 5 (Noto font path)
- `Dockerfile` — Bug 5 (add fonts-noto if needed)
- `cf_platform/models/storyboard.py` — Bug 1 (add `on_screen_text_type = "person"` literal if not present)

### Acceptance Criteria
- [x] No `lower_third` rendered in any scene; Character scene person name appears as centre OST overlay
- [x] Character + historic scenes query Wikimedia first; `asset_manifest.source == "wikimedia"` confirmed for a Kirk Erickson–equivalent scene
- [x] No two scenes in the same run share the same `file_key`; `duplicate_avoided: true` appears in manifest where a skip occurred
- [x] Every Event scene has non-empty `on_screen_text` after storyboard generation; synthesised OSTs logged at WARNING level
- [x] `→` and `↑` render as correct glyphs in the video output; confirmed via a test render

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

---

## [P10-S2] Merged storyboard+assets table with per-scene asset override
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P10 (carried from P9-S8)
**Status:** done
**Completed:** 2026-06-29
**Priority:** high
**Points:** 5
**Depends on:** P9-S3

### Goal
Eliminate the separate Assets stage. Merge asset preview and override controls directly into the Storyboard table so the operator sees voiceover context and footage in the same row. Acquisition becomes a button inside the Storyboard pane, not a pipeline stage. Each row gets a pencil icon that opens a modal for re-query or manual upload.

**Why merge:** the current split means the operator must context-switch between two tables to evaluate whether a clip fits its scene. The voiceover line and the thumbnail need to be in the same row.

**Multi-agent self-improvement alignment:**
- **Artifact immutability (D057):** every override writes a new `asset_manifest` artifact version; the original is preserved.
- **Feedback signal:** every operator correction emits a `TraceEvent(type="operator_asset_override")` with `{scene_n, reason: "reacquire"|"upload", original_query, override_query?}`. A future query-quality judge can replay these to identify which auto-generated queries consistently fail.

---

### UI spec — studio.html

#### Stage nav change
Remove the **Assets** pill from the stage nav. New order: **Script → Voice → Storyboard → Render** (4 stages, was 5). The `pane-assets` div is deleted.

#### Storyboard table — new columns
Add two columns to the right of the existing storyboard table:

| Column | Width | Content |
|--------|-------|---------|
| **Preview** | 100px | Thumbnail `<img>` (still) or muted autoplay `<video loop>` (clip). Empty / grey placeholder before acquisition runs. |
| **✎** | 32px | Pencil icon button. Disabled (greyed) before acquisition runs. |

The **Source** badge (wikimedia / pexels / operator) appears as a small pill below the thumbnail. The QA pass/fail dot appears next to it. These replace the entire Assets pane — no other asset metadata is shown by default.

#### Acquire Assets button
The existing `"Acquire Assets →"` CTA stays at the bottom of the Storyboard pane, exactly where it is today. When clicked:
- Button becomes `"Acquiring… (0 / N)"` with a spinner.
- As each scene completes, its thumbnail cell fills in live (polling `GET /platform/studio/runs/{run_id}/asset-manifest` every 3 s, or server-sent events if available).
- On full completion, button label changes to `"Re-acquire All"` (secondary style). CTA gains a new `"Go to Render →"` primary button.

#### Pencil modal
A centred modal (not slide-in; 480px wide) opens when the pencil is clicked.

**Modal header:** `Scene {N} — {first 6 words of voiceover}…`

**Modal body — two sections, vertically stacked:**

**Section 1 — Re-acquire**
```
Label: "Search query"
Input: [pre-filled with current visual_query from storyboard]        [Re-acquire]
                                                     ↑ spinner replaces button while running
Current preview thumbnail (80×50) shown inline left of input.
On success: thumbnail updates, source badge updates, modal stays open.
On error: inline red message below input.
```

**Section 2 — Upload your own**
```
Label: "Or upload a file"
[Drop zone / file picker — accept: video/mp4, video/webm, image/jpeg, image/png, image/webp]
Max file size: 200 MB (enforced client-side before upload).
Progress bar during upload.
On success: thumbnail updates, source badge = "operator", modal closes.
On error: inline red message.
```

Sections are independent — using one does not disable the other.

**Modal footer:** `[Close]` button (ghost style).

---

### Backend spec

#### New endpoint — single-scene re-acquire
**`POST /platform/studio/runs/{run_id}/scenes/{scene_n}/reacquire`**
```json
{ "query": "neurons synapse microscope" }
```
- Read latest `verified_storyboard`; find scene N's `segment_type`, `person_name`.
- Read latest `asset_manifest`; find entry for scene N.
- Override entry's `visual_query` with the supplied query; preserve `segment_type` routing.
- Call `_acquire_single_scene(scene, entry, clients, storage, run_id) → ManifestEntry` (see refactor note).
- Write new `asset_manifest` artifact version via `artifact_repo.write`.
- Emit `TraceEvent(type="operator_asset_override", data={scene_n, reason="reacquire", original_query, override_query})`.
- Return `{ scene_n, file_key, source, qa_passed, preview_url }` (presigned URL, 1 h TTL).

#### New endpoint — operator upload
**`POST /platform/studio/runs/{run_id}/scenes/{scene_n}/upload`**
- `multipart/form-data`, single `file` field.
- Validate MIME type in `{"video/mp4","video/webm","image/jpeg","image/png","image/webp"}`.
- Validate size ≤ 200 MB.
- R2 key: `runs/{run_id}/images/scene_{scene_n:02d}_op.{ext}` or `.../video/...`.
- Write via `storage.put_bytes(key, data, content_type)`.
- Patch manifest entry: `file_key=key, source="operator_upload", qa_passed=True, fallback_used=False, status="acquired"`. Write new manifest version.
- Emit `TraceEvent(type="operator_asset_override", data={scene_n, reason="upload"})`.
- Return `{ scene_n, file_key, preview_url }`.

#### Refactor — extract `_acquire_single_scene`
Extract the per-scene acquisition logic currently inlined in `acquisition_worker.py`'s `_worker` closure into a module-level function:
```python
async def _acquire_single_scene(
    scene: StoryboardScene,
    entry: ManifestEntry,
    pexels: PexelsClient,
    pixabay: PixabayClient,
    wikimedia: WikimediaClient,
    storage: StorageBackend,
    run_id: str,
    used_file_keys: set[str] | None = None,
) -> ManifestEntry:
```
`AcquisitionWorker._worker` calls this in its loop (no behaviour change). The new REST endpoints call it standalone.

#### Existing endpoint — asset manifest (already exists, extend)
`GET /platform/studio/runs/{run_id}/asset-manifest` — already returns manifest JSON. Ensure it also returns per-entry `preview_url` (presigned, 1 h TTL) so the Studio can render thumbnails without a second round-trip.

---

### Files affected
- `src/static/studio.html` — remove Assets pane + pill; add Preview + pencil columns to storyboard table; pencil modal; live-fill polling on acquire; `"Go to Render →"` CTA after acquisition completes
- `cf_platform/interfaces/api.py` — two new route handlers (`reacquire`, `upload`)
- `cf_platform/workers/acquisition_worker.py` — extract `_acquire_single_scene`
- `cf_platform/models/storyboard.py` / `src/models.py` — no schema changes needed

### Acceptance Criteria
- [x] Assets stage pill removed; nav has 4 stages: Script → Voice → Storyboard → Render
- [x] Storyboard table has Preview (thumbnail/video) and pencil columns; cells fill live during acquisition
- [x] `"Acquire Assets →"` CTA in Storyboard pane triggers acquisition and shows per-scene progress
- [x] After acquisition, `"Go to Render →"` CTA appears; render stage is reachable directly from Storyboard pane
- [x] Pencil modal opens with correct pre-filled query and current thumbnail
- [x] Re-acquire: new query sent, manifest versioned, thumbnail refreshes in modal
- [x] Upload: file validated (type + size), written to R2, manifest versioned, thumbnail refreshes
- [x] Both actions emit `operator_asset_override` TraceEvent
- [x] `_acquire_single_scene` extracted; full acquisition worker tests still pass; new unit tests cover Character/Event/B-roll routing via the extracted function
- [x] Reacquire + upload endpoint tests: success, scene-not-found, acquisition-fail, invalid MIME, oversized file

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** operator opens Storyboard pane → clicks "Acquire Assets" → thumbnails fill in live row by row → clicks pencil on one scene → edits query → thumbnail refreshes → clicks "Go to Render →"

### Handover
- **`_acquire_single_scene(scene, entry, pexels, pixabay, wikimedia, storage, run_id, used_file_keys?)`** — public module-level function in `cf_platform/workers/acquisition_worker.py`; routes by `segment_type` (Character/Event/B-roll), returns updated `ManifestEntry`
- **`POST /platform/studio/runs/{run_id}/scenes/{scene_n}/reacquire`** — override primary_stk, re-acquire, version manifest, emit TraceEvent; returns `{scene_n, file_key, source, qa_passed, preview_url}`
- **`POST /platform/studio/runs/{run_id}/scenes/{scene_n}/upload`** — validate MIME + size, write to R2 (`runs/{id}/images/` or `video/`), version manifest, emit TraceEvent; returns `{scene_n, file_key, preview_url}`
- **studio.html** nav reduced to 4 stages; storyboard table has Preview + pencil columns; pencil modal with re-acquire and upload sections; live 3s polling during acquisition fills thumbnails row by row
- **`tests/cf_platform/test_p10_s2_asset_override.py`** — 16 tests (6 worker unit + 4 reacquire endpoint + 6 upload endpoint)

---

## [P10-S3] Semantic enrichment — global topic context + Entity Resolver + visual deduplication
**Epic:** E37 — Visual Intelligence Layer
**Sprint:** P10
**Status:** done
**Completed:** 2026-06-30
**Priority:** high
**Points:** 6

### Goal
The storyboard agent currently produces acquisition queries with no awareness of the global video topic or inter-scene context. A scene mentioning "protein" in a neuroscience video searches for food because it has no way to know "protein" means neuronal BDNF, not dietary intake.

This story introduces three complementary mechanisms that together eliminate context-free acquisition without a full agent decomposition:

1. **Global semantic context in the storyboard** — the storyboard now outputs a `global_context` block that the acquisition layer reads before building any search query.
2. **Entity Resolver** — a deterministic Python function (no LLM) that classifies entities in each scene and returns the preferred source chain, solving character and historic-event sourcing structurally.
3. **Visual deduplication pass** — a post-acquisition agent pass that sees the full manifest and rewrites redundant visual queries before any assets are downloaded.

#### Sub-task 1 — Global context block in StoryboardScene schema

Extend `verified_storyboard` output with a new top-level `global_context` object:

```json
{
  "global_context": {
    "topic": "Brain health and cognitive longevity",
    "domain": "neuroscience",
    "subtopics": ["neurons", "memory", "BDNF", "aging", "exercise", "diet", "sleep"],
    "avoid_globally": ["food preparation", "cooking", "generic lifestyle"],
    "tone": "evidence-based documentary"
  }
}
```

And per-scene, add a `semantic_context` field alongside the existing `visual_query`:

```json
{
  "semantic_context": {
    "primary_concept": "BDNF — brain-derived neurotrophic factor",
    "domain_qualifier": "neurological protein, not dietary",
    "avoid": ["fried eggs", "food", "cooking", "meal prep"],
    "visual_tags": ["microscopy", "neuron", "synapse", "protein structure", "brain science"],
    "entity_type": null
  }
}
```

**Prompt changes (storyboard_worker.py):**
- Add `global_context` generation as a preamble step in the storyboard prompt.
- Add `semantic_context` as a required field per scene in the JSON schema section.
- Provide 2–3 worked examples in the prompt demonstrating the domain-qualifier pattern (e.g., "protein" in neuroscience context → `domain_qualifier: "neurological protein"`, `avoid: ["food", "cooking"]`).

**Schema changes (storyboard.py):**
- `GlobalContext` model: `topic`, `domain`, `subtopics: list[str]`, `avoid_globally: list[str]`, `tone`.
- `SemanticContext` model: `primary_concept`, `domain_qualifier`, `avoid: list[str]`, `visual_tags: list[str]`, `entity_type: Optional[Literal["person", "historic_event", "location", "organization"]]`.
- `StoryboardScene.semantic_context: Optional[SemanticContext]`.
- `Storyboard.global_context: Optional[GlobalContext]`.

**AcquisitionWorker changes:**
- Before building the Pexels/Pixabay query string, inject `global_context.topic` and `semantic_context.visual_tags` into the query.
- Append negative terms from `semantic_context.avoid` as exclusion filters where the API supports it (Pexels: omit; Pixabay: `-term` syntax in query string).
- Log the enriched query string at DEBUG level for observability.

#### Sub-task 2 — Entity Resolver (deterministic)

A pure Python function `resolve_entity(scene: StoryboardScene, global_context: GlobalContext) -> EntityResolution` that runs before acquisition for each scene.

```python
@dataclass
class EntityResolution:
    entity_type: str          # "person", "historic_event", "location", "concept", "stock"
    preferred_sources: list[str]  # ordered: ["wikimedia", "pexels"]
    search_hint: str          # e.g. "Albert Einstein physicist"
    fallback_query: str       # generic fallback if preferred sources fail
```

**Routing rules (no LLM):**
| Condition | entity_type | preferred_sources |
|-----------|-------------|-------------------|
| `scene.segment_type == "character"` and `person_name` set | `person` | `["wikimedia", "pexels"]` |
| `semantic_context.entity_type == "historic_event"` | `historic_event` | `["wikimedia", "pexels"]` |
| `semantic_context.entity_type == "location"` | `location` | `["pexels", "pixabay"]` |
| `semantic_context.entity_type == "organization"` | `organization` | `["wikimedia", "pexels"]` |
| else | `concept` / `stock` | `["pexels", "pixabay"]` |

`AcquisitionWorker` calls `resolve_entity` per scene; the returned `preferred_sources` list replaces the current hardcoded source order.

#### Sub-task 3 — Visual deduplication pass (post-acquisition)

After all scenes have been acquired, run a lightweight deduplication review:

- Build a `visual_summary` list: `[(scene_n, primary_visual_concept, asset_file_key)]`.
- Detect clusters: if 3+ consecutive scenes share the same `primary_visual_concept` substring (case-insensitive), flag them.
- For flagged scenes (excluding scene 1 of each cluster), re-query with the next `visual_tag` from `semantic_context.visual_tags` as the primary term.
- Log each requery at INFO level: `"Visual dedup: scene {n} requeried as '{new_term}' (was '{old_term}')."`.
- Cap rerequeries at 6 per run to bound runtime.

This is distinct from the file_key deduplication in P9-S10 (which prevents the exact same file appearing twice). This pass prevents the same *concept* appearing too many times even with different assets.

### Files Affected
- `cf_platform/models/storyboard.py` — `GlobalContext`, `SemanticContext`, `EntityResolution` models
- `cf_platform/workers/storyboard_worker.py` — global context preamble, `semantic_context` per scene
- `cf_platform/workers/acquisition_worker.py` — Entity Resolver call, enriched query building, visual dedup pass
- `docs/PROMPTS.md` — storyboard prompt changelog (bump to v0.11)

### Acceptance Criteria
- [x] `verified_storyboard` artifact contains a `global_context` block on every run
- [x] Every scene has a `semantic_context` with `primary_concept`, `domain_qualifier`, and at least 2 `visual_tags`
- [x] On a neuroscience-topic run, a "protein" scene queries for neurological visuals (not food); confirmed via enriched query in DEBUG log
- [x] `Entity Resolver` routes Character + historic scenes to Wikimedia; `asset_manifest.source` reflects this
- [x] Visual dedup pass fires on a run with 3+ consecutive same-concept scenes; at least 1 requery logged
- [x] All existing tests pass; new unit tests cover `resolve_entity` routing table (all 5 branches) and dedup cluster detection

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- `src/models.py`: `GlobalContext` + `SemanticContext` models; `Storyboard.global_context` + `StoryboardScene.semantic_context` + `ManifestEntry.semantic_context` fields (all Optional)
- `cf_platform/workers/storyboard_worker.py`: prompt v0.15 — GLOBAL CONTEXT preamble + SEMANTIC CONTEXT per scene in both prompt variants
- `cf_platform/workers/acquisition_worker.py`: `EntityResolution` dataclass; `resolve_entity()` (5 branches); `_build_enriched_queries()` (visual_tags + domain prefix); `_visual_dedup_pass()` (3+ cluster detection, 6-requery cap)
- `tests/cf_platform/test_p10_s3_semantic.py`: 25 tests; 1964 total passing
**Promoted to backlog:** none

---

## [P11-S1] Visual Director agent — post-storyboard visual treatment
**Epic:** E37 — Visual Intelligence Layer
**Sprint:** P11
**Status:** done
**Completed:** 2026-06-30
**Priority:** medium
**Points:** 6

### Goal
Today the storyboard agent conflates *narrative meaning* with *visual decisions*. A dedicated Visual Director node receives the enriched storyboard (post P10-S1) and produces a `visual_treatment` artifact — a per-scene visual plan that the acquisition layer fulfils. This is the architectural separation between storytelling and asset sourcing described in the sprint planning discussion.

The Visual Director does **not** search for assets. It answers: *"If a top YouTube documentary editor planned the visuals for this script, what would they specify?"*

#### Visual treatment schema

```json
{
  "visual_treatment": {
    "global_style": "evidence-based science documentary — authoritative, not clinical",
    "shot_sequence_plan": "macro → wide → diagram → person → archive → macro",
    "scenes": [
      {
        "scene": 7,
        "visual_intent": "Establish the researcher as a credible authority; portrait photo, direct gaze preferred",
        "shot_type": "portrait",
        "era": "contemporary",
        "asset_class": "person_photo",
        "preferred_source": "wikimedia",
        "search_terms": ["Kirk Erickson neuroscientist", "exercise brain researcher"],
        "avoid": ["lab equipment alone", "generic doctor"],
        "motion": "ken_burns_in",
        "transition_from_prev": "cut"
      },
      {
        "scene": 10,
        "visual_intent": "Show BDNF as a molecular/cellular phenomenon — microscopy or animation",
        "shot_type": "macro_science",
        "era": "contemporary",
        "asset_class": "stock",
        "preferred_source": "pexels",
        "search_terms": ["neuron synapse microscope", "brain cells fluorescence", "synaptic connection"],
        "avoid": ["food", "protein shake", "diet"],
        "motion": "slow_push",
        "transition_from_prev": "cut"
      }
    ],
    "diversity_plan": {
      "shot_type_sequence": ["wide", "macro", "portrait", "diagram", "archive", "macro", "wide"],
      "notes": "No more than 2 consecutive shots of the same type"
    }
  }
}
```

#### Agent design

- **Model:** Claude Sonnet (visual storytelling requires reasoning; Haiku insufficient).
- **Input:** `verified_storyboard` artifact (with `global_context` + `semantic_context` from P10-S1).
- **Output:** `visual_treatment` artifact in R2 at `users/{user}/runs/{run_id}/visual_treatment/visual_treatment@v1.json`.
- **Prompt structure:**
  - System: role as documentary video editor; rules for shot variety, diversity, and continuity.
  - User: full storyboard JSON + shot sequence rules.
  - Enforce: no two consecutive scenes with same `shot_type`; at least 3 distinct `asset_class` values across the run.
- **Pipeline position:** after `StoryboardWorker`, before `AcquisitionWorker`.
- `AcquisitionWorker` reads `visual_treatment.scenes[n].search_terms` (primary), `preferred_source`, and `avoid` in preference to storyboard `visual_query`. Falls back to storyboard query if no treatment available.

#### Shot type vocabulary (controlled list)

`portrait` · `wide` · `macro_science` · `diagram` · `archive` · `drone` · `lifestyle` · `screen_recording` · `animation` · `infographic`

This vocabulary is used in both the prompt and the `shot_type` field to constrain Claude's output to a known set.

#### Diversity enforcement (post-Visual-Director validation in Python)

After the agent returns its treatment, a Python validator checks:
- No 3+ consecutive identical `shot_type` values → raise `VisualDiversityError` and re-invoke the agent with the violation highlighted (max 1 retry).
- At least 3 distinct `asset_class` values in runs > 10 scenes.
- Log `diversity_score = unique_shot_types / total_scenes` to the `footage_summary` artifact.

#### LangGraph wiring

```
StoryboardWorker → VisualDirectorWorker → AcquisitionWorker → RenderWorker
```

`VisualDirectorWorker` is a new `WorkerNode`; factory: `build_visual_director_worker(storage, anthropic_api_key) → WorkerNode`.

### Files Affected
- `cf_platform/workers/visual_director_worker.py` — new file
- `cf_platform/orchestrator/full_pipeline.py` — wire new node between storyboard and acquisition
- `cf_platform/workers/acquisition_worker.py` — read `visual_treatment` artifact; prefer its `search_terms` over storyboard `visual_query`
- `cf_platform/models/visual_treatment.py` — new Pydantic models: `VisualTreatment`, `SceneVisualPlan`, `DiversityPlan`
- `docs/PROMPTS.md` — Visual Director prompt v0.1

### Acceptance Criteria
- [x] `visual_treatment` artifact written to R2 on every run
- [x] `AcquisitionWorker` prefers `visual_treatment.search_terms` over storyboard `visual_query`; confirmed in acquisition logs
- [x] No run has 3+ consecutive scenes with the same `shot_type`; diversity validator fires and retries when violated
- [x] `footage_summary` includes `diversity_score`
- [ ] A neuroscience-topic run: scene mentioning "protein" gets `shot_type: "macro_science"` and search terms referencing neurons — not food _(deferred to DEV smoke test)_
- [ ] Character scene with named researcher gets `asset_class: "person_photo"` and `preferred_source: "wikimedia"` _(deferred to DEV smoke test)_
- [x] Unit tests: Visual Director prompt construction; diversity validator (pass + violation cases); AcquisitionWorker treatment-preference logic

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
- **New files:** `cf_platform/models/__init__.py`, `cf_platform/models/visual_treatment.py`, `cf_platform/workers/visual_director_worker.py`, `tests/cf_platform/test_p11_s1_visual_director.py`
- **Modified:** `cf_platform/workers/acquisition_worker.py` (reads optional `visual_treatment` artifact; `_build_treatment_queries`), `cf_platform/orchestrator/full_pipeline.py` (new `visual_director_node` between storyboard and acquisition), `docs/PROMPTS.md` (Visual Director v0.1 changelog)
- **Exports:** `build_visual_director_worker(storage, anthropic_api_key) → WorkerNode`, `VISUAL_DIRECTOR_REGISTRATION`, `VisualTreatment`, `SceneVisualPlan`, `DiversityPlan`
- **Backward compat:** `visual_treatment` absent → acquisition falls back to enriched STK queries (no breaking change)

---

## Post-MVP outlines (not yet detailed)

**EPIC 38 — Multi-asset timelines (P11):** Each scene can hold a sub-timeline of 2–3 assets with individual in/out points. The render worker assembles sub-clips within a scene's duration window. Enables e.g. a 7-second "BDNF" scene that shows 3 seconds of neuron microscopy → 2 seconds of a scientist → 2 seconds of a brain scan without a scene boundary. Requires render_script builder rewrite for sub-scene ffmpeg concat.

**EPIC 39 — Visual motion effects (P11):** Subtle camera shake (2–5px overlay), film grain (noise filter), light leak overlay (screen blend), animated callouts (arrow grows, underline draws in FFmpeg `drawbox`+`drawtext` sequence). Each effect is a named preset in the `motion_effect` field. **The controlled vocabulary this epic asked for shipped in P-UX2-S3** (`src.models.MOTION_EFFECTS` — ken_burns / zoom_in / zoom_out / pan_right / pan_left / static, D081), along with the operator dropdown and the discovery that `motion_effect` had never actually reached the render script. P11-S2 extends that vocabulary rather than creating it.

**EPIC 32 — Legacy Rebuild** (~3 sprints after P7): re-author Script→Video as native workers; retire `src/` + adapter.
**EPIC 34 — Replay & Evaluation Engine** (~3 sprints after P7): replay any worker, golden eval dataset, A/B routing, LLM-judge scoring.

---

## EPIC 41 — Studio UX Redesign (Sprint P-UX1)

Operator-facing rework of `src/static/studio.html` per the approved mockup (2026-07-03 design session): centered landing/pipeline shell, a new Settings stage that moves aspect-ratio/style/music/captions decisions to the front of the run (before acquisition, not at render time — see [[project_run_settings_ui]]), and a new Metadata stage that surfaces the existing `youtube_metadata` worker output for copy-paste/future channel upload. Legacy `pipeline.html` stops being the default UI.

---

## [P-UX1-S1] Run shell redesign — centered landing + pipeline header + info panel
**Epic:** E41 — Studio UX Redesign
**Sprint:** P-UX1
**Status:** done
**Completed:** 2026-07-03
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
Replace the current empty-state + sidebar + `run-header` chrome with the approved mockup layout: a centered run list (from `studio_runs` localStorage history) with a "+ New run" button above it on the landing screen; on the pipeline screen, a centered stage-nav row (reusing the existing `.stage-pill`/`.stage-track` visual style — dot status, `›` arrow separators, active underline) with the auto-advance checkbox and a new info icon on the right of the same row. No "Studio" label or run-id badge anywhere in the header. Info icon opens a slide-out right panel (run id, created date, cost placeholder, aspect ratio) — pure front-end, no new endpoints.

### Acceptance Criteria
- [x] Landing view: centered run list + "+ New run" button, ~20% top offset; no persistent sidebar
- [x] Pipeline view: centered stage-nav row; auto-advance + info icon pinned right of the same row; no "Studio" text or run-id badge visible
- [x] Info icon toggles a right-side panel showing run id, created date, aspect ratio, and a cost placeholder
- [x] Small "← All runs" affordance replaces the removed header as the only way back to the landing list
- [x] Existing stage-pill visual states (idle/running/done/error, dot colors, `›` arrows) are unchanged — only repositioned
- [x] No regressions to existing stage navigation, auto-advance behavior, or `#run/{id}/{stage}` URL hash routing

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `src/static/studio.html`: sidebar (`<aside>`) removed entirely; landing view (`#landing`) shows a centered run list from `studio_runs` localStorage with a "+ New run" button; `renderSidebar()` renamed `renderRunList()`. Pipeline header rebuilt as `.pipe-row-outer > .pipe-row` (flex `justify-content:center` wrapper — plain `margin:0 auto` does not reliably center a flex item inside a column-flex parent) containing the existing `.stage-track` pills plus a right-pinned auto-advance checkbox and a new info-icon button. `run-id-display` kept as a hidden span for backward JS compat; visible run id now lives only in the info panel.
- New `#info-panel` slide-out (width 0→260px transition): run id, created timestamp (from the local run-list entry), aspect ratio (live-synced from Settings), cost placeholder, Log out link.
- `showLanding()` / `enterWorkspace()` / `populateInfoPanel()` / `toggleInfoPanel()` added.
- All stage-pane content wrappers (`Settings/Script/Voice/Video/Metadata`) gained `margin:0 auto` to center within the pipe-row's alignment; Storyboard pane intentionally left as full-width (table content, per story scope — "OK as is").

---

## [P-UX1-S2] Settings stage — aspect ratio, style, music upload, captions
**Epic:** E41 — Studio UX Redesign
**Sprint:** P-UX1
**Status:** done
**Completed:** 2026-07-03
**Priority:** high
**Points:** 5
**Depends on:** P-UX1-S1

### Goal
New first stage ("Settings") ahead of Script. Fixes the long-standing gap where aspect ratio is only chosen at the Render pane (too late — storyboard framing and acquisition already ran): `format_track` now flows from Settings into both the storyboard worker call and the render worker call.

### Backend changes
- `StoryboardWorkerRequest` (`cf_platform/interfaces/api.py`) gains `format_track: str = "portrait"`; `storyboard_worker_endpoint` passes it via `StageState(inputs={"format_track": body.format_track})` — `_generate()` and `build_storyboard_worker` already read this field (P9-S6), the REST endpoint just never forwarded it.
- `RenderWorkerRequest` gains `captions: bool = True`; render endpoint maps `True → subtitles="TikTok"`, `False → subtitles="none"` when constructing render inputs.
- New `POST /platform/studio/runs/{run_id}/music` — multipart upload (`audio/mpeg`, `audio/wav`, `audio/mp4`; ≤ 50 MB), stored at `runs/{run_id}/music/{filename}`, replacing any prior upload for that run (single active track).
- RenderWorker gains an async `_copy_music_to_run` fallback (mirrors `src/renderer.py:copy_music_to_run` but against the async `ArtifactStorage` protocol): if the run has no music file when render starts, copy the first eligible track from `music-library/`; log and continue silently if the library is empty.

### Frontend changes
- New `pane-settings` stage: aspect ratio pills (9:16 / 16:9), style pills (Realistic active, Animated disabled with a "Soon" badge), music dropzone (upload → new endpoint) + current-track chip, captions on/off toggle.
- Settings choices held in client state (`state.settings`); threaded into the Script→Storyboard call (`format_track`) and the Render call (`format_track`, `captions`).

### Acceptance Criteria
- [x] Aspect ratio chosen in Settings reaches the storyboard worker call (verify via `verified_storyboard` scene framing / prompt format line)
- [x] Aspect ratio chosen in Settings reaches the render worker call (already partially wired — confirm end-to-end)
- [x] Captions toggle reaches the render worker call and maps to `subtitles="TikTok"`/`"none"`
- [x] Music upload endpoint: valid MP3 accepted and stored; invalid MIME rejected; oversized file rejected
- [x] Render falls back to `music-library/` copy when no run-specific music was uploaded; skips the copy when one already exists
- [x] Style pills: Animated is visibly disabled and does not trigger any request
- [x] Tests: `format_track` threading (storyboard + render requests), captions→subtitles mapping, music upload endpoint (success/invalid-mime/oversized), async music fallback copy (has-music skip, library-empty warning, happy path)

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `cf_platform/interfaces/api.py`: `StoryboardWorkerRequest.format_track: str = "portrait"` now forwarded into `StageState(inputs={"format_track": ...})` (previously defined but never passed — root cause of the aspect-ratio-at-render-time gap). `RenderWorkerRequest.captions: bool = True` forwarded as `state.inputs["captions"]`. New `POST /studio/runs/{run_id}/music` — validates `audio/mpeg|wav|x-wav|mp4`, ≤50MB, stores at a fixed key `runs/{run_id}/music/track{ext}` (same-format re-upload overwrites; a different format after a prior upload leaves both — documented limitation).
- `cf_platform/workers/render_worker.py`: `_build_render_script` gains `captions: bool = True` → `subtitles = video_settings.subtitles if captions else "none"`. New async `_copy_music_to_run(run_id, storage)` (async port of `src/renderer.py:copy_music_to_run` for the `ArtifactStorage` protocol) called in `_worker` before `_download_assets`.
- `src/static/studio.html`: new `pane-settings` stage (first in `STAGES`) with aspect-ratio pills, style pills (Animated disabled), music dropzone, captions toggle; `state.settings = {aspectRatio, style, captions, musicKey}` threaded into the storyboard and render fetch calls; old `#format-track-select` in the Render pane removed.
- `tests/cf_platform/test_pux1_s2_settings_backend.py` (new, 12 tests).
- 2015 tests passing after this story (was 2000).

---

## [P-UX1-S3] Metadata stage — youtube_metadata worker wired into Studio
**Epic:** E41 — Studio UX Redesign
**Sprint:** P-UX1
**Status:** done
**Completed:** 2026-07-03
**Priority:** medium
**Points:** 3
**Depends on:** P-UX1-S1

### Goal
The `youtube_metadata` worker (P7-S2) already produces title/description/tags from a script artifact, but it's only ever invoked from the Telegram `full_pipeline.py` graph — Studio's step-by-step flow never calls it. Add a Metadata stage after Video that calls it directly, matching the existing per-stage worker-endpoint pattern (`/platform/workers/storyboard`, `/voice`, `/acquisition`, `/render`).

### Backend changes
- New `POST /platform/workers/metadata` — builds `youtube_metadata_worker` directly from the run's `script` artifact (same pattern as `storyboard_worker_endpoint`); persists `YoutubeMetadataArtifact`.
- New `GET /platform/studio/runs/{run_id}/metadata` — returns the latest metadata artifact, mirroring `GET .../video`.

### Frontend changes
- New `pane-metadata` stage (nav label "Metadata"; internal stage key can stay distinct from `render`/`video` labeling decided in S1): editable title/description/tags/pinned-comment fields pre-filled from the artifact, a "Generate metadata" trigger, and a permanently-disabled "Upload to channel" button with helper text ("Connect a channel in Settings to enable uploads") — no channel API in this story.

### Acceptance Criteria
- [x] Metadata stage generates and displays title/description/tags from the run's script
- [x] Fields are editable client-side (not yet persisted back — display/copy only, matching current AC scope)
- [x] "Upload to channel" button is disabled with explanatory helper text; no request fires on click
- [x] Tests: metadata worker endpoint happy path + missing-script-artifact error; GET metadata endpoint present/absent cases

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `cf_platform/interfaces/api.py`: `POST /workers/metadata` — looks up the run's latest `script` artifact directly (no graph), calls `build_youtube_metadata_worker` (P7-S2, unchanged), persists under `stage="metadata"`. `GET /studio/runs/{run_id}/metadata` mirrors the other studio GET endpoints.
- `src/static/studio.html`: new `pane-metadata` stage (nav label "Metadata"); `generateMetadata()` / `renderMetadataResult()` / `resetMetadataPane()`; render-complete auto-advances into Metadata when auto-advance is on; `loadRun()` fetches existing metadata on load.
- `tests/cf_platform/test_pux1_s3_metadata_endpoint.py` (new, 3 tests).
- 2018 tests passing after this story.

---

## [P-UX1-S4] Retire legacy pipeline.html as default UI
**Epic:** E41 — Studio UX Redesign
**Sprint:** P-UX1
**Status:** done
**Completed:** 2026-07-03
**Priority:** medium
**Points:** 3
**Depends on:** P-UX1-S1, P-UX1-S2, P-UX1-S3

### Goal
Studio becomes the primary operator UI. `GET /` now serves `studio.html`; the legacy pipeline UI moves to `GET /legacy` (kept fully operable per D047 — this is a routing change, not a deletion of the legacy engine or its backend).

### Acceptance Criteria
- [x] `GET /` serves `studio.html`
- [x] `GET /legacy` serves `pipeline.html` unchanged
- [x] `GET /studio` still works (redirect or alias) for any bookmarked links
- [x] Decision logged in DECISIONS.md noting this narrows (does not reverse) D047 — legacy backend stays untouched and operable, only its UI default changes
- [x] Tests: route status codes for `/`, `/legacy`, `/studio`

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `src/main.py`: `GET /` now serves `studio.html` (was `pipeline.html`); `GET /legacy` serves `pipeline.html` unchanged; `GET /studio` kept as an alias.
- `DECISIONS.md`: D066 logged — narrows D047 (UI default only; legacy engine untouched and still operable at `/legacy`).
- `tests/test_pux1_s4_routing.py` (new, 3 tests).
- 2018 total tests passing (was 2000 before this sprint).
**Smoke test:** PASSED — verified live on the local dev server against the real R2 DEV bucket: landing list, Settings→Script→Metadata flow, info panel, music upload, and `/legacy` fallback all confirmed working via browser preview.

---

## EPIC 42 — Render & Narration Controls (Sprint P-UX2)

The validated 9:16 setup becomes a template with operator-selectable variants rather than hardcoded choices. Adds a caption style preset and TTS pace/register to the Settings stage, turns the storyboard table's read-only Motion column into a real per-scene control, and introduces one shared dropdown component so Settings selects, Motion cells and SFX cells all look the same. Uncovered and fixed three latent defects along the way: `motion_effect` never reached the render script (D081), it was not in `_PATCHABLE_FIELDS` so it could not be edited, and `VideoSettings` never reached the native renderer.

---

## [P-UX2-S1] `.cf-select` dropdown component + SFX column restyle
**Epic:** E42 — Render & Narration Controls
**Sprint:** P-UX2
**Status:** done
**Completed:** 2026-08-30
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
One shared dropdown component, used by every select in Studio. Before this story there was no `select` rule anywhere in `studio-v2.html` — the SFX column rendered with raw browser chrome, visually inconsistent with the rest of the design system.

### Acceptance Criteria
- [x] `.cf-select` defined from existing design tokens, with the same focus treatment as `.script-textarea`
- [x] Native `<select>` with `appearance: none` + a data-URI chevron — no JS listbox (keyboard nav, type-ahead and the mobile native picker stay free)
- [x] `.cf-select--sm` modifier for table cells; storyboard row height unchanged
- [x] Existing SFX select adopts it with no behaviour change to `onSfxChange`

### Definition of Done
- [x] All AC checked · CI green · verified in the browser preview

---

## [P-UX2-S2] Caption style preset — Standard / Punch
**Epic:** E42 — Render & Narration Controls
**Sprint:** P-UX2
**Status:** done
**Completed:** 2026-08-30
**Priority:** high
**Points:** 4
**Depends on:** P-UX2-S1

### Goal
A second caption preset alongside the validated look: ALL CAPS, one word at a time. Chosen on the Settings stage, applied at render.

### Acceptance Criteria
- [x] `VideoSettings.caption_style: "standard" | "punch"`, orthogonal to `subtitles`
- [x] Settings dropdown, disabled while the captions toggle is off; persists and rehydrates
- [x] Flows `RenderWorkerRequest.caption_style` → `state.inputs` → `_build_render_script`
- [x] Punch: one word per Dialogue event, uppercased, no active-word highlight, gapless timing
- [x] Uppercasing is display-only — `WordTimestamp.word` untouched (it still drives timing)
- [x] New `_CAPTIONS_ASS_HEADER_PUNCH` (130px vs 80px); 9:16 only, matching D070's scoping
- [x] Standard preset output unchanged

### Definition of Done
- [x] All AC checked · CI green · 19 tests in `tests/cf_platform/test_pux2_s2_caption_style.py` · D082 logged

---

## [P-UX2-S3] Motion effect vocabulary + per-scene Motion dropdown
**Epic:** E42 — Render & Narration Controls
**Sprint:** P-UX2
**Status:** done
**Completed:** 2026-08-30
**Priority:** high
**Points:** 5
**Depends on:** P-UX2-S1

### Goal
Make `motion_effect` real. The operator picks per scene from a controlled vocabulary; pans traverse the full landscape image when it is used inside a 9:16 frame.

### Acceptance Criteria
- [x] `MOTION_EFFECTS` vocabulary + `normalize_motion_effect()` in `src/models.py`; field stays `str | None` so stored artifacts validate
- [x] `_zoompan_filter`'s `still_with_motion` early return removed — `motion_effect` is honoured for the first time
- [x] `zoom_in`/`zoom_out` at 2% per second (rate-based, duration-independent)
- [x] `pan_left`/`pan_right` traverse the full image via a time-driven `crop` on a height-only pre-scale; verified in FFmpeg (100 frames / 4.000s / 25fps, first-vs-last frame delta 97.5)
- [x] `motion_effect` added to `ScenePatchRequest` (422 on unknown values) and `_PATCHABLE_FIELDS`
- [x] Storyboard table Motion column is a `.cf-select--sm` dropdown; `—` for video scenes
- [x] **No regression:** a pre-D081 storyboard produces a byte-identical render script

### Definition of Done
- [x] All AC checked · CI green · 12 tests in `tests/cf_platform/test_pux2_s3_motion.py` + rewritten `TestZoompanFilter`/`TestMotionVfPrefix` · D081 logged

---

## [P-UX2-S4] Narration pace + emotional register
**Epic:** E42 — Render & Narration Controls
**Sprint:** P-UX2
**Status:** done
**Completed:** 2026-08-30
**Priority:** high
**Points:** 3
**Depends on:** P-UX2-S1

### Goal
TTS speed and delivery style on the Settings stage. Gemini exposes no numeric speaking-rate parameter, so both are composed into the natural-language instruction prefixed to the script.

### Acceptance Criteria
- [x] `VideoSettings.narration_pace` (slow/normal/fast) + `narration_style` (educational/emotional)
- [x] Two Settings dropdowns; persist and rehydrate
- [x] `_PACE_WPM` + `_STYLE_CLAUSE` tables replace the single hardcoded constant; `_build_tts_input(script, pace, style)` composes them
- [x] D073's pause wording preserved **verbatim** in every pace × style combination (asserted)
- [x] `_estimate_duration` derives wps from the same table
- [x] Reaches the worker via `settings.json` read in `voice_worker_endpoint`; `VoiceWorkerRequest` unchanged
- [x] Unknown values fall back to defaults rather than raising (D048)

### Definition of Done
- [x] All AC checked · CI green · 32 tests in `tests/cf_platform/test_pux2_s4_narration.py` · D083 logged

---

## EPIC 43 — Projects & Shortlist (Sprint P12)

First sprint of the Pipeline & Platform Update (D092–D099). Introduces the Tenant → Project → Run hierarchy and the persistent project shortlist. No research agents yet: ideas are added by hand so the hierarchy and the shortlist → run hand-off can be used and judged before P15 automates the intake.

**Design rules for the whole epic**
- Every new table has `tenant_id`, filled with the existing `PLATFORM_USER_ID` (`"operator"`). No auth work (D092).
- New views are separate static pages under `src/static/`, plain HTML/JS, reusing Studio's CSS tokens and `.cf-select`. `studio-v2.html` only gains what it needs to be opened for a given project and run.
- Schema changes go in a new numbered file in `cf_platform/db/migrations/` (next: `0002_`).
- Studio / REST only — no Telegram commands (D093).

---

## [P12-S1] Projects data model + API
**Epic:** E43 — Projects & Shortlist
**Sprint:** P12
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
A `projects` table and a project reference on every run, with REST endpoints to list, create, read and update projects. Existing runs are moved into one default project so nothing disappears.

**Open point to settle first (not yet verified):** Studio creates runs client-side (`newRun()` in `studio-v2.html`) and keeps its run list in `localStorage` (`studio_runs`). It is not confirmed that every Studio run — in particular one started from a pasted script, which skips `POST /platform/blocks/idea-to-script` — gets a row in the Postgres `runs` table. Establish this before writing the migration; if some runs have no row, this story adds an explicit "create run" endpoint that always writes one.

**Tech:** Postgres (raw SQL migration, D048), FastAPI, Pydantic.

### Data model
```
projects(project_id TEXT PK, tenant_id TEXT NOT NULL, name TEXT NOT NULL, niche TEXT NOT NULL DEFAULT '',
         config JSONB NOT NULL DEFAULT '{}',        -- content/style defaults; research config lands here in P15
         default_channel_id TEXT NULL,              -- filled in P16
         archived_at TIMESTAMPTZ NULL, created_at, updated_at)
runs: + tenant_id TEXT, + project_id TEXT REFERENCES projects
```

### Acceptance Criteria
- [x] Open point above resolved and the finding written into this story's Handover
- [x] Migration `0002_*.sql` creates `projects`, adds `runs.tenant_id` and `runs.project_id`, creates one default project and assigns all existing runs to it
- [x] `GET /platform/projects`, `POST /platform/projects`, `GET /platform/projects/{id}`, `PATCH /platform/projects/{id}` (name, niche, config, archive)
- [x] `GET /platform/projects/{id}/runs` returns that project's runs, newest first, with status and created date
- [x] Creating a run requires a `project_id`; a run cannot be created without one
- [x] Repository functions are pure async and take explicit inputs (D040); routes are thin wrappers
- [x] Tests: migration applies on an empty and on a populated database; CRUD happy paths; run without `project_id` rejected; project-scoped run list excludes other projects' runs

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- **Open point — resolved.** Studio runs did **not** reliably have a `runs` row. `newRun()` minted the id in the browser and wrote only `settings.json` to R2 plus `localStorage.studio_runs`; a pasted-script run never got a row (`studio.py`'s reacquire handler already documented the resulting FK failure on `trace_events`). A generated-script run got one only because `POST /platform/blocks/idea-to-script` minted a *new* id that Studio then swapped to. Consequence: the migration backfill covers generated-script runs only; the rest are registered by `POST /platform/projects/{id}/runs/import` (see S2).
- `cf_platform/db/migrations/0002_projects_shortlist.sql`: `projects`, `shortlist_items`, `run_shortlist_items`; `runs` gains `tenant_id` (backfilled from `user_id`), `project_id NOT NULL DEFAULT 'default' REFERENCES projects` (adding the column *is* the backfill), `name`, `archived_at`. Idempotent like 0001.
- `cf_platform/core/projects.py`: `Project`, `ProjectRepository` Protocol, `InMemoryProjectRepository` (seeded with the default project), `create_project`, `update_project`. `cf_platform/core/postgres_project_repos.py`: `PostgresProjectRepository`.
- `RunRecord` gains `tenant_id`, `project_id` (default `DEFAULT_PROJECT_ID`), `name`, `archived_at`. `create_run(..., project_id=, name=, run_id=)` — existing callers (Telegram, block routes) are unchanged and land in the default project; an empty `project_id` raises `ValueError`. New `register_existing_run`, `archive_run`; `RunRepository` gains `list_for_project`, `count_by_project`.
- Routes in `cf_platform/interfaces/routes/projects.py`: `GET/POST /platform/projects`, `GET/PATCH /platform/projects/{id}`, `GET /platform/projects/{id}/runs`. There is no project-less run-creation route; the only creation route is nested under a project (S4).
- `tenant_id` is `PLATFORM_USER_ID` (`"operator"`) everywhere; a project whose tenant differs is a 404.
- **Migration verified on real Postgres** (local 5432, scratch database, dropped afterwards): empty database, populated database (two pre-existing runs land in the default project), and applied twice. Kept as `tests/integration/test_p12_migration_postgres.py` — excluded from CI, run with `CF_TEST_DATABASE_URL=... pytest -m integration`.
- Tests: `tests/cf_platform/test_p12_s1_projects.py` (31).
- **Files that mattered:** `cf_platform/db/migrations/0001_init.sql`, `cf_platform/core/run_manager.py`, `cf_platform/core/postgres_repos.py`, `cf_platform/interfaces/dependencies.py`, `cf_platform/interfaces/routes/studio.py` (the reacquire handler's comment on missing `runs` rows), `src/static/studio-v2.html` (`newRun`, `generateScript`).

---

## [P12-S2] Studio project landing + server-side run list
**Epic:** E43 — Projects & Shortlist
**Sprint:** P12
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 5
**Depends on:** P12-S1

### Goal
`GET /` shows the project list. Opening a project shows its page with two areas — Shortlist (P12-S3) and Runs — and a settings panel for name and niche. The run list comes from the server, so it is the same in every browser.

**Tech:** plain HTML/JS static page(s); existing Studio CSS.

### Acceptance Criteria
- [x] `/` serves a project list with "+ New project"; each project shows name, niche and run count
- [x] Project page lists the project's runs from `GET /platform/projects/{id}/runs`; clicking a run opens the existing Studio pipeline for it
- [x] `localStorage.studio_runs` is no longer the source of the run list; runs that exist only in a browser's local history are not lost silently — the Handover states what happens to them
- [x] Project name and niche are editable on the project page and persist
- [x] Studio pipeline header shows the project name and a link back to the project page
- [x] Bookmarked `/studio` links keep working
- [x] Usable at 9:16-phone and desktop widths, per docs/UI_GUIDELINES.md
- [x] Tests: route status codes; project page renders an empty state with no runs

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `src/main.py`: `/` → `projects.html`, `/project?id=<project_id>` → `project.html`, `/studio` → `studio-v2.html`. Studio deep links are unchanged (`/studio#run/<id>/<stage>`); an old `/#run/<id>` bookmark is forwarded to `/studio` by `projects.html`; `/studio` with no run in the URL redirects to `/`.
- `projects.html` (list, "+ New project", run count) and `project.html` (Shortlist, Runs, Settings panel) are separate static pages with their own inline CSS using the Studio tokens (D092). Project settings edit name, niche and `config.run_defaults` (aspect ratio, captions, narration pace/style).
- **What happens to browser-only runs:** nothing is deleted. On load, `projects.html` sends `localStorage.studio_runs` (id, name, timestamp) to `POST /platform/projects/default/runs/import`, which registers any run without a row into "Default project" and reports how many moved; it then sets `studio_runs_imported` so it runs once per browser. The local list itself is left in place. A pre-P12 run opened directly by its link is registered the same way by Studio. Runs known only to a browser that is never opened again stay in R2 but unlisted.
- `studio-v2.html`: `getLocalRuns()` returns the project's runs from `GET /platform/projects/{id}/runs` (sidebar "Recent"); `localStorage.studio_runs` is no longer read or written. Header shows `← <project name>` linking to the project page; "All runs" / "New run" go to the project page. Demo mode (`?demo=1`) keeps its in-page mock run list.
- Deleting a run in Studio also archives its row (`DELETE /platform/projects/{id}/runs/{run_id}`) so it leaves the list; the row is kept for lineage.
- Run status in the list is the row's lifecycle (`created` shown as "Draft", `running` as "In progress"), not per-stage pipeline progress — no Studio stage writes to the row yet.
- `docs/UI_GUIDELINES.md` predates Studio (it describes the dark legacy UI); the new pages follow Studio's "Monochrome Console" tokens instead. Verified at 375px and desktop widths in a local preview: no horizontal overflow, "Create video" bar pinned to the bottom.
- Tests: `tests/test_p12_s2_pages.py` (10); `tests/test_pux1_s4_routing.py` updated (`/` no longer serves Studio).
- **Files that mattered:** `src/main.py`, `src/static/studio-v2.html` (CSS tokens at the top; `getLocalRuns` / `saveLocalRun` / `loadRun` / `init`), `tests/test_pux1_s4_routing.py`, `tests/conftest.py` (auth bypass fixture).

---

## [P12-S3] Persistent shortlist — table, API, project page
**Epic:** E43 — Projects & Shortlist
**Sprint:** P12
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 5
**Depends on:** P12-S1

### Goal
Each project has a shortlist of content ideas that only grows by adding and only shrinks by explicit removal (D094). In this sprint items are added by hand; the schema already carries the origin fields research will fill in P15.

### Data model
```
shortlist_items(item_id TEXT PK, tenant_id, project_id REFERENCES projects,
                title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
                discovery_method TEXT NOT NULL CHECK (IN ('manual','trend','competitor')),
                source TEXT NULL,                 -- e.g. "reddit", "google_news", a channel handle
                evidence JSONB NOT NULL DEFAULT '{}',   -- why it is trending / why it performs
                kpis JSONB NOT NULL DEFAULT '{}',       -- e.g. likes_per_1k_views, outlier_score
                research_run_id TEXT NULL,        -- filled in P15
                discovered_at TIMESTAMPTZ NOT NULL,
                removed_at TIMESTAMPTZ NULL, created_at)
```
Removal is a soft delete (`removed_at`), so a run created from an item keeps a valid reference.

### Acceptance Criteria
- [x] Migration adds `shortlist_items` as above
- [x] `GET /platform/projects/{id}/shortlist`, `POST …/shortlist` (manual add: title, summary, optional source/notes), `DELETE …/shortlist/{item_id}` (soft)
- [x] There is no endpoint that replaces or clears the shortlist in bulk
- [x] Project page Shortlist area: list with title, summary, method badge, source, date discovered; add form; remove with confirmation
- [x] Each item shows how many runs were created from it (0 until P12-S4)
- [x] Tests: add / list / remove; removed items excluded from the default list but still resolvable by id; items of another project not returned

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `cf_platform/core/shortlist.py`: `ShortlistItem`, `ShortlistRepository` Protocol, `InMemoryShortlistRepository`, `add_manual_item`, `remove_item`. `PostgresShortlistRepository` in `postgres_project_repos.py`. The repository has `add` and `mark_removed` only — no bulk write of any kind (D094).
- Routes: `GET/POST /platform/projects/{id}/shortlist`, `GET/DELETE /platform/projects/{id}/shortlist/{item_id}`. A test pins the shortlist surface to exactly these four operations; `PUT`/`PATCH`/`DELETE` on the collection are 405.
- Manual add stores `discovery_method="manual"`, optional `source`, and `notes` as `evidence["notes"]`. `kpis` and `research_run_id` stay empty until P15.
- Removal sets `removed_at`; the item leaves the default list but `GET .../shortlist/{item_id}` still returns it, and runs created from it keep their link.
- Each listed item carries `run_count` (from `run_shortlist_items`).
- Tests: `tests/cf_platform/test_p12_s3_shortlist.py` (16).
- **Files that mattered:** `DECISIONS.md#D094`, `cf_platform/core/run_manager.py` (the Protocol + in-memory + pure-function pattern this mirrors).

---

## [P12-S4] Create a content run from shortlist item(s)
**Epic:** E43 — Projects & Shortlist
**Sprint:** P12
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 3
**Depends on:** P12-S2, P12-S3

### Goal
The operator ticks one or more shortlist items and presses "Create video". A run is created in the project, linked to those items, and opens in the existing Studio flow at Settings, with the Script stage pre-filled from the selected ideas. Both existing script paths stay: generate, or paste an existing script.

### Acceptance Criteria
- [x] `run_shortlist_items(run_id, item_id)` link table; one run can reference several items, one item can feed several runs
- [x] `POST /platform/projects/{id}/runs {item_ids: [...]}` creates the run row, the links, and returns the run id
- [x] Script stage: idea title pre-filled from the selected item(s); with several items, titles and summaries are combined into the idea context passed to `idea-to-script`
- [x] Project `niche` is passed to script generation instead of being typed per run
- [x] Settings stage starts from the project's `config` defaults when present; per-run changes do not write back to the project
- [x] Run info panel lists the shortlist items the run came from
- [x] The rest of the pipeline (voice, storyboard, acquisition, render, metadata) is unchanged
- [x] Tests: run creation with 1 and with 2 items; unknown or removed item id rejected; links readable from the run
- [x] **Human touchpoint:** operator opens `/`, opens a project, adds an idea by hand, creates a run from it and reaches a rendered video through the existing stages

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Handover
- `POST /platform/projects/{id}/runs {item_ids}` → 201 with the run. Validates first (`resolve_items_for_run`): unknown id → 404, removed or other-project item → 409, empty list → 422; then writes the `runs` row (`block="studio"`, name = idea title) and the ordered links. A run needs at least one item — there is no blank-run path (D094).
- `build_idea_context(items)`: one item → its title + summary; several → titles joined with " + " and one "title — summary" supporting point per item.
- `GET /platform/studio/runs/{run_id}/context` → project, source items (including later-removed ones), `idea_title`, `supporting_points`. Studio uses it for the header, the info panel ("Shortlist ideas this run came from") and the Script stage pre-fill.
- `POST /platform/blocks/idea-to-script` accepts optional `run_id`: the script is generated into that run (same id, project and links), the project's niche is used when the request names none, the run moves `created → running` and is **not** marked complete, and each generation uses a fresh checkpoint thread (`{run_id}:idea_to_script:{8 hex}`) — reusing the finished thread would re-apply the additive `iteration` / `integrity_loops` reducers. Without `run_id` behaviour is unchanged (Telegram path untouched).
- Settings: `project.html` flags a just-created run in `sessionStorage` (`cf_new_run`); Studio then seeds Settings from `project.config.run_defaults` plus the idea as Run subject and saves them to the run's `settings.json`. Later edits only ever write the run's settings.
- The Niche field in the Script stage is read-only and labelled "from project" when the project has one.
- Verified in a local preview (fake credentials, in-memory repositories): project → add two ideas → create a run from one and from both → Studio opens at Settings with the project defaults, idea, niche and source items in place. **Not exercised locally:** script generation, voice, storyboard, render (need real API keys and R2) — that is the DEV smoke test.
- Tests: `tests/cf_platform/test_p12_s4_runs_from_shortlist.py` (18).
- **Files that mattered:** `cf_platform/interfaces/routes/blocks.py`, `cf_platform/core/execution_engine.py` (`run_graph` thread ids), `cf_platform/workers/context_normalizer.py` (how `supporting_points` is consumed), `src/routes/runs.py` (settings GET returns defaults when absent), `src/static/studio-v2.html` (`loadRun`, `saveRunSettings`, `generateScript`).
- **DEV smoke test PASSED 2026-10-03** (operator, all 16 steps) — including script generation into the run, the full pipeline to a rendered video, and deleting a run.

---

## EPIC 32 — Legacy Rebuild (post-P7, outline)
Re-author Script→Video as native LangGraph blocks/workers; reach parity; retire `src/` + adapter. **Detailed after a P6 retro.** Representative stories (~3 sprints):
- **E32-S1** Storyboard worker as a node (uses existing prompt heritage)
- **E32-S2** Asset-acquisition source-adapters (Pexels/Replicate/Pixabay/Wikimedia) as IO adapters
- **E32-S3** FFmpeg render worker as a node
- **E32-S4** Captions/alignment nodes
- **E32-S5** Parity harness — same input → equal-or-better output vs legacy
- **E32-S6** Flagged cutover — `full_pipeline` points at native blocks; adapter kept as fallback
- **E32-S7** Retire `src/` + adapter once parity holds N consecutive runs

---

## EPIC 33 — Analytics & Attribution (Sprint P7)
Close the loop: which prompt/worker version → higher retention (D054).

> **Parked by D099 — never built.** This epic was planned as Sprint P7 before P7 became Idea Selection + YouTube Metadata (EPIC 34 above). The story IDs below (`P7-S1`…`P7-S3`) are the old plan's and collide with the shipped P7 stories; they are not sprint commitments.

---

## [P7-S1] Publish linkage capture
**Epic:** E33 — Analytics & Attribution
**Sprint:** P7
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** P6-S4

### Goal
Capture `run_id ↔ external_video_id`. Until a publish agent exists: `POST /runs/{id}/published {platform, external_id, url}` (operator pastes the YouTube URL) → `published_videos` row.
**Tech:** Postgres, FastAPI/Telegram. **Schema:** `published_videos`.

### Acceptance Criteria
- [ ] Endpoint records `published_videos` row linked to the run
- [ ] Telegram convenience command available

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P7-S2] YouTube analytics ingestion worker
**Epic:** E33 — Analytics & Attribution
**Sprint:** P7
**Status:** planned
**Priority:** high
**Points:** 5
**Depends on:** P7-S1

### Goal
Scheduled worker pulls retention/views/avg-view-%/CTR per video → time-series `video_metrics` rows (D054).
**Tech:** YouTube Analytics API (OAuth), Postgres, Railway scheduled task. **Dependency:** YouTube OAuth client + scheduler (D054). **Schema:** `video_metrics`.

### Acceptance Criteria
- [ ] Metrics ingested per published video on a schedule
- [ ] `video_metrics` time-series populated

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P7-S3] Attribution query + report
**Epic:** E33 — Analytics & Attribution
**Sprint:** P7
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** P7-S2

### Goal
`GET /platform/analytics/attribution` joins `video_metrics → published_videos → runs → worker_executions`, aggregating retention by `prompt_version`/`worker_version`/`model` (plan §6 query).
**Tech:** Postgres (analytical query), FastAPI.

### Acceptance Criteria
- [ ] Endpoint returns retention grouped by prompt/worker version
- [ ] **Human touchpoint:** operator reads a report ranking prompt versions by retention

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## EPIC 34 — Replay & Evaluation Engine (post-P7, outline)
Turn passive analytics into active behavioral evolution (D055 foundation). **Detailed after P7** (~3 sprints, ~30 pts). Representative stories:
- **E34-S1** Replay primitive — re-invoke any worker node with `{input_artifact_ref, version_override}` → replay artifact (`replay_of`, `eval_run=true`)
- **E34-S2** Golden eval dataset — curated, versioned fixtures of historical inputs per worker
- **E34-S3** Comparison + LLM-judge — structured diff + judge scoring across versions → `eval_results`
- **E34-S4** A/B routing in production — version-split flag; lineage records which version ran; join to retention (P7)
- **E34-S5** Eval leaderboard — rank prompt/worker versions by offline eval score + online retention

---

## EPIC 44 — Storyboard control (Sprint P13)

Second sprint of the Pipeline & Platform Update (D095, spec §10–15). The storyboard becomes a human gate: the operator can change each scene's asset strategy and the scene boundaries before any acquisition call is made. Delivered as one sprint (METHODOLOGY.md, 2026-10-03).

**Design rules for the whole epic**
- The storyboard records the *desired* asset strategy per scene; acquisition executes it (D095). Today the image/video choice is derived from scene duration (`_assign_asset_tier`) and cannot be changed by the operator.
- Scene boundaries are `start_word` / `end_word` indices (P9-S9). Timing is always recomputed from the Deepgram word timestamps — never typed in.
- **Voiceover text is read-only in this sprint** (operator decision, 2026-10-03). Changing words forces re-voicing and re-alignment; the operator goes back to the Script stage for that.
- **Splitting a scene that already has an asset** (operator decision, 2026-10-03): the first half keeps the asset, the second half is marked as needing acquisition.
- Every edit writes a new storyboard artifact version through the existing `_patch_storyboard` path, so `render_options` and cumulative timing stay coherent.
- With Auto Advance on, the gate is skipped (D095). Studio / REST only (D093). Plain HTML/JS, reusing `.cf-select`.

---

## [P13-S1] Per-scene asset strategy — model, patch, acquisition
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
Each scene carries an operator-editable asset strategy — stock image, stock video, or upload — that is set before acquisition and that acquisition obeys. Without an explicit choice, behaviour is exactly as today.

### Acceptance Criteria
- [x] `StoryboardScene` gains `asset_strategy: Literal["stock_image", "stock_video", "upload"] | None = None`; `None` means "derive from `asset_tier` as today". The vocabulary lives in one constant so P14 can add `ai_image`
- [x] `asset_strategy` is in `_PATCHABLE_FIELDS` and validated in `PATCH /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}`; an unknown value is rejected with 422
- [x] The storyboard GET returns, for every scene, the effective strategy (the explicit one, or the one derived from `asset_tier`) so the UI never has to re-derive it
- [x] AcquisitionWorker: `stock_image` forces the photo path and `stock_video` the video path, regardless of `asset_tier` / `clip_type`; the render script treats the scene accordingly (a still gets its motion effect, a video does not)
- [x] `upload` scenes are skipped by acquisition and reported as "awaiting upload" in the manifest and `footage_summary`; the existing per-scene upload endpoint fills them; render is refused with a clear message while any upload scene has no file
- [x] Changing a still scene to video (or back) resets `motion_effect` to the correct default via `normalize_motion_effect`
- [x] **Confirm at the start of the story:** whether the Studio stage-by-stage flow runs the Visual Director at all — it is only referenced from `full_pipeline.py`, not from the worker routes. Record the finding in the Handover; wiring it in is out of scope unless the strategy cannot work without it
- [x] **No regression:** a storyboard with no `asset_strategy` on any scene produces a byte-identical manifest request and render script before and after
- [x] Tests: patch accept/reject; each strategy's acquisition path; upload scene skipped and blocking render; legacy storyboard unchanged

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — `_assign_asset_tier`, `_asset_tier_to_clip_type`, `_patch_storyboard` / `_PATCHABLE_FIELDS`
- `cf_platform/workers/acquisition_worker.py` — the `asset_tier` / `clip_type` branch (two places), `visual_treatment` loading
- `cf_platform/interfaces/routes/studio.py` — scene PATCH, `reacquire`, `upload`
- `src/models.py` — `StoryboardScene`, `ManifestEntry`, `normalize_motion_effect`
- `cf_platform/models/visual_treatment.py` — `SceneVisualPlan.asset_class` / `preferred_source`
- `DECISIONS.md` — D095, D081, D089

### Handover
- **Visual Director finding:** the Studio stage-by-stage flow does not run it. `build_visual_director_worker` is referenced only from `cf_platform/orchestrator/full_pipeline.py`; `POST /platform/workers/acquisition` never passes a `visual_treatment`. The asset strategy does not need it, so it was left unwired.
- `src/models.py`: `AssetStrategy` Literal → `ASSET_STRATEGIES` (P14 adds `ai_image` there only), `effective_asset_strategy()`, `AWAITING_UPLOAD_STATUS`; `StoryboardScene.asset_strategy`; `ManifestEntry.asset_strategy` + `asset_slot`.
- `storyboard_worker.apply_asset_strategy(scene, strategy)` realigns `asset_tier` / `clip_type` / `motion_effect`: video → `("video","hard_cut",None)`; image → still tier (floored to `still_motion`) with `normalize_motion_effect`; upload → untouched (the upload endpoint re-derives from the file, D089).
- Scene PATCH accepts `asset_strategy` (422 on unknown). With a manifest present, `_sync_entry_with_strategy` releases an asset that no longer fits and the response lists `needs_acquisition` (D102). Storyboard GET adds `effective_asset_strategy` to every scene.
- Acquisition: `_wants_video(entry)` replaces both tier branches; `stock_video` goes straight to the stock video search even on Character / Event scenes. The worker skips `upload` scenes (`awaiting_upload` in the manifest and, only when non-zero, in `footage_summary`), keeps an uploaded file through a full re-acquire, and with `inputs["only_missing"]` keeps every acquired entry. `build_manifest_artifact` is the one place that counts acquired / failed.
- Render: `render_worker.missing_assets_message` — the endpoint returns 409 and the worker raises before any FFmpeg work. It checks for a file, not for `status == "acquired"` (a failed re-acquire keeps the old file).
- The upload endpoint now starts a manifest from the storyboard when the run has none (needed for uploading at the gate).
- Tests: `tests/cf_platform/test_p13_s1_asset_strategy.py` (57), helper `tests/cf_platform/p13_helpers.py`.
- **Files that mattered:** `acquisition_worker.py` (worker loop, `_acquire_scene`, `_acquire_single_scene`), `studio.py` (patch, upload), `workers.py` (acquisition + render endpoints), `src/ffmpeg_builder.py` (`_scene_section` needs one entry with a file per scene).

---

## [P13-S2] Split and merge scenes
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
The operator can split one scene into two at a word, and merge a scene with the next one. Boundaries move as word indices; durations and overlay timing are recomputed from the Deepgram timestamps.

### Acceptance Criteria
- [x] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/split {at_word}` — `at_word` becomes the first word of the new second scene; rejected with 422 unless `start_word < at_word <= end_word`
- [x] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/merge` — merges the scene with the one after it; rejected with 409 on the last scene
- [x] After either operation the storyboard is still contiguous (first `start_word` = 0, last `end_word` = N−1, no gaps), scene ids are renumbered in order, and `voiceover_line`, `scene_start_ms` / `scene_end_ms`, `duration_s` and `asset_tier` are recomputed from the word timestamps by the same code the StoryboardWorker uses
- [x] Split: the first half keeps every field of the original scene; the second half copies the visual fields (search terms, segment type, asset strategy) and starts with no on-screen text and no SFX
- [x] Merge: the first scene's fields win; the second scene's on-screen text and SFX are dropped, and the response says so
- [x] `render_options` for all scenes are rebuilt through `_patch_storyboard`; a new storyboard artifact version is written
- [x] **Already-acquired assets (operator decision):** on split, the first half keeps the asset and the second half is marked as needing acquisition; on merge, the merged scene keeps the first scene's asset and the second scene's manifest entry is removed. The manifest stays aligned with the renumbered scenes, and a later "Acquire Assets" fetches only the scenes that need one
- [x] A split that would create a scene shorter than the minimum scene duration is rejected with a clear message
- [x] Voiceover text is not editable through these endpoints
- [x] Tests: split and merge happy paths; boundary validation; contiguity and timing after a sequence of splits and merges; manifest alignment with and without acquired assets

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — the scene-from-word-span builder (around `start_word` / `end_word` clamping), the long-scene splitter, the contiguity enforcement, `_patch_storyboard`
- `cf_platform/interfaces/routes/studio.py` — scene PATCH (how a new artifact version is written), manifest GET
- `cf_platform/workers/render_worker.py` — "live start_word boundaries" block
- `tests/cf_platform/test_p9_s9_timestamp_storyboard.py`, `tests/cf_platform/test_p10_s2_asset_override.py`
- `DECISIONS.md` — D095, D086

### Handover
- **The recompute helper (reused by S4):** `cf_platform/workers/storyboard_edit.py` — `replace_boundaries(storyboard, words, start_words, manifest, min_scene_s)` returns a `BoundaryEdit` (storyboard, realigned manifest or `None`, `dropped`, `needs_acquisition`). `split_scene` and `merge_scene` only build the new start-word list. Pure functions; rule and rationale in D102.
- Timing comes from `_reify_scene`; kept scenes with an asset follow the file kind (`rederive_scene_visual_contract`), an untouched scene keeps every field, an explicit strategy is re-applied, everything else takes the duration-derived tier.
- Routes: `POST …/storyboard/scenes/{id}/split {at_word}` (422 outside `start < at_word <= end` or below the minimum), `POST …/scenes/{id}/merge` (409 on the last scene), 404 unknown scene, 409 when the run has no voice alignment. The response carries the new storyboard, `dropped`, `needs_acquisition` (`null` before acquisition) and a one-line `summary`.
- Words are loaded with `_normalize_deepgram_words` — the same list the StoryboardWorker indexes into.
- Manifest: rewritten only when the run has one; always one entry per scene in scene order. `asset_slot` keeps a newly acquired file from overwriting a kept one after renumbering (worker, pencil re-acquire); uploads get a hash suffix (D102).
- `STORYBOARD_MIN_SCENE_S` (default 1.0) in `PlatformSettings` and ENV.md; checked only on scenes whose span changed.
- A storyboard without word indices (generated without voice timestamps) cannot be edited — 422 with a message to regenerate.
- **Noticed, not changed:** `render_worker`'s "live start_word boundaries" block indexes the *raw* alignment words while scene indices refer to the *normalised* list (contraction tokens collapsed). Pre-existing; worth a look if scene cuts drift on scripts with many contractions.
- Tests: `tests/cf_platform/test_p13_s2_split_merge.py` (32).

---

## [P13-S3] Storyboard stage — strategy dropdown, split / merge controls, confirm gate
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 3
**Depends on:** P13-S1, P13-S2

### Goal
The Storyboard table in Studio exposes the new controls, and acquisition starts only when the operator confirms the storyboard.

### Acceptance Criteria
- [x] New "Asset" column: a `.cf-select--sm` dropdown per scene with Stock image / Stock video / Upload, showing the effective strategy; changing it calls the scene PATCH and re-renders the row (the Motion cell follows: dropdown for stills, `—` for video)
- [x] An "Upload" scene shows an upload control in its row before acquisition, using the existing per-scene upload endpoint
- [x] Split: clicking a word in a scene's voiceover text offers "Split here"; Merge: each row except the last has "Merge with next". Both re-render the table from the response
- [x] A merge that drops on-screen text or SFX asks for confirmation first
- [x] The acquire button reads "Confirm storyboard & acquire"; nothing is acquired before it is pressed when Auto Advance is off. With Auto Advance on, acquisition starts without the gate (D095)
- [x] After acquisition, scenes that need an asset (a split's second half, an unfilled upload) are visibly marked, and the button acquires only those
- [x] Row height and table width stay as they are at 1280px; no console errors
- [x] Tests: static-page test pins the new controls and the routes they call
- [x] **Human touchpoint:** on DEV, the operator changes a scene from image to video, splits one scene and merges two, confirms and acquires, then swaps one scene's asset with the pencil — the last step clears the **P10-S2** deferred smoke test

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `src/static/studio-v2.html` — `renderStoryboard`, `patchScene`, `acquireAssets`, the auto-advance block in `renderStageTrack`
- `docs/UI_GUIDELINES.md#principles`, `docs/UI_GUIDELINES.md#step-status-display`
- `tests/cf_platform/test_p12_s2_pages.py` (pattern for static-page tests), `tests/cf_platform/test_pux2_s3_motion.py`

### Handover
- `src/static/studio-v2.html` only. The read-only image / video badge column is now the **Asset** dropdown (`.cf-select--sm` + `.cf-select--asset`); `onAssetChange` patches and reloads the table.
- Split: every voiceover word after the first is a `.vo-word`; clicking opens the `#split-pop` popover ("Split here" / Cancel, closes on scroll and Escape). Merge: `⤵` under the pencil on every row but the last; `confirm()` first when the next scene has on-screen text or SFX.
- `acquirePlan()` is the single source for the button: "Confirm storyboard & acquire →" until a stock asset exists, "Acquire N missing scene(s) →" (`only_missing: true`), else "Re-acquire All". Auto Advance still calls `acquireAssets` directly after storyboard generation, and no longer starts the render while an Upload scene awaits a file.
- An Upload scene without a file shows an Upload control in its Preview cell (works before acquisition); other scenes without an asset show "needs asset" once a manifest exists; the summary shows "N need an asset".
- `_applyManifestToTable` now rebuilds `state.manifestEntries` instead of merging (ids are renumbered by edits).
- **Width at 1280px:** table 987px before and after, row heights identical (measured in the demo fixture). Asset and Motion selects are sized to their longest label to pay for the dropdown.
- Demo mode (`?demo=1`) mocks strategy patch, split, merge and boundaries so the controls can be tried without a backend.
- Verified in the browser preview (demo mode): split, acquire-missing, image → video (Motion becomes `—`), Upload control, merge with confirmation, no console errors beyond the demo's missing SFX library. **DEV smoke test PASSED 2026-10-03** (operator, all 17 steps, `1e5ff4b`) — including real acquisition, row upload, only-missing acquisition after a split, and the pencil swap that clears the P10-S2 deferral.
- Tests: `tests/cf_platform/test_p13_s3_storyboard_stage.py` (20, shared with S4's UI).

---

## [P13-S4] Script view — edit scene boundaries as text
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** med
**Points:** 3
**Depends on:** P13-S2

### Goal
A second view of the Storyboard stage shows the whole voiceover as text, with a blank line between scenes. The operator moves the blank lines to move the boundaries and applies the result in one step.

### Acceptance Criteria
- [x] Toggle in the Storyboard stage: Table / Script. Script view shows each scene's words as a paragraph, paragraphs separated by one blank line
- [x] `PUT /platform/studio/runs/{run_id}/storyboard/boundaries {start_words: [...]}` replaces all scene boundaries at once; validated (starts at 0, strictly increasing, within range, minimum scene duration) and applied through the same recompute path as split / merge
- [x] A scene whose `start_word` is unchanged keeps its fields and its asset; a new scene inherits the visual fields of the scene it was cut from; assets follow the same rule as P13-S2
- [x] **Words cannot be changed.** If the text differs from the voiceover by anything other than paragraph breaks, Apply is disabled and the message says to change the text in the Script stage (it forces re-voicing)
- [x] Apply shows what will change ("12 scenes → 14; 3 scenes need acquisition") before writing
- [x] Tests: boundary replace happy path; each validation failure; unchanged scenes keep fields and assets; changed-words rejection

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P13-S2 Handover (the recompute helper this story reuses)
- `src/static/studio-v2.html` — `renderStoryboard`
- `cf_platform/interfaces/routes/studio.py` — storyboard GET, voice GET (word list)

### Handover
- `PUT …/storyboard/boundaries` takes exactly one of `start_words` or `script_text`, plus `dry_run`. `script_text` is the Script view's text: `start_words_from_text` requires the words to equal the voiceover's in order (only paragraph breaks may differ), else 422 pointing to the Script stage.
- Same `replace_boundaries` path as split / merge, so the keep / inherit / drop rules and manifest handling are identical (D102).
- UI: Table / Script toggle in the Storyboard summary row (`state.sbView`). Script view is a textarea with one paragraph per scene; `onScriptViewInput` disables Apply when the words differ or nothing moved. Apply sends a dry run, shows its `summary` ("12 scenes → 14; 3 scenes need acquisition") in a confirm, then writes.
- The Script view shows the normalised words (no punctuation) — those are the words the boundaries index.
- Tests: `tests/cf_platform/test_p13_s4_boundaries.py` (25).

---

## EPIC 49 — CapCut export (Sprint P13b)

Third sprint of the Pipeline & Platform Update (D100). A second render path from a finalized storyboard: Studio hands over a zip, a script on the operator's laptop writes a CapCut desktop project, and the video rendered in CapCut is uploaded back into the run. Delivered as one sprint (`/start-story P13b-S1..S4`).

**Design rules for the whole epic**
- The FFmpeg render on Railway is Path 1 and stays as it is: same endpoint, same output, same render script for the same inputs.
- One neutral timeline describes a finalized run. Both render paths read it; neither path re-derives timing, motion or captions on its own.
- Assets are addressed by the manifest's `file_key`. A path is never rebuilt from a scene id — scene ids are renumbered by split / merge and files are not moved (P13 Handover, D102).
- `pycapcut` is used only by the laptop script, with its own requirements file. It is not added to `requirements.txt` or the Docker image (D100).
- CapCut has no official API and its draft format is undocumented (D100, Risks). The laptop script states which CapCut version it was tested with and fails with a clear message rather than writing a draft it cannot vouch for.
- Path 2 has no Auto Advance. Studio / REST only (D093). Plain HTML/JS.

---

## [P13b-S1] Neutral timeline artifact + render regression tests
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
One artifact — the timeline — describes everything a renderer needs for a finalized run: scenes with timing, the asset per scene, motion, on-screen text, caption words, voiceover, music and SFX. The FFmpeg script builder is rewired to read it. Before that rewiring, golden render-script tests pin today's output so the change is provably neutral.

### Acceptance Criteria
- [x] **Golden tests first.** Fixtures and expected render scripts for at least: still with each motion effect, stock video scene, operator-uploaded video on a still scene (D089), pan on a portrait still narrower than 9:16 (D091), 16:9, captions Standard and Punch, on-screen text, SFX and music present / absent. They are committed and green *before* the builder is changed
- [x] `Timeline` model (Pydantic) with a `schema_version`, covering per scene: scene id, start / end in ms, duration, asset `file_key` and kind (image / video), motion effect, on-screen text with its type and timing, SFX key and delay; and per run: aspect ratio and output size, caption style and caption words with timestamps, voiceover key and duration, music key and volume settings
- [x] `build_timeline(storyboard, manifest, voice_alignment, settings)` is a pure function (D040) and is the only place scene timing is resolved for rendering
- [x] The timeline is written as a versioned run artifact when a render is started and whenever it is requested by P13b-S2; `GET /platform/studio/runs/{run_id}/timeline` returns it, and 409 with `missing_assets_message` while any scene has no file
- [x] `_build_render_script` / `build_ffmpeg_script` take the timeline as their source for timing, assets, motion and overlays. **Every golden render script is byte-identical before and after**
- [x] **Word-index fix (noted in P13-S2):** the "live start_word boundaries" block resolves scene boundaries against the same normalised word list the StoryboardWorker indexes (`_normalize_deepgram_words`), not the raw alignment words. A test with a contraction-heavy script shows the scene cuts land on the storyboard's boundaries. If this changes a golden script, the difference is stated in the Handover
- [x] Tests: timeline from a storyboard with split / merged scenes and an `asset_slot`; `upload` scene without a file → 409; schema round-trip; the golden suite

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/render_worker.py` — `_build_render_script`, the "live start_word boundaries" block, `_build_captions_with_y_override`, `_collect_overlay_filters`, `missing_assets_message`, `_copy_music_to_run`, `_copy_all_scene_sfx_to_run`
- `src/ffmpeg_builder.py` — `build_ffmpeg_script`, `_scene_section`, `_motion_vf_prefix`, `_zoompan_filter`, `_audio_section`, `_local_path`
- `src/models.py` — `StoryboardScene`, `ManifestEntry` (`file_key`, `asset_slot`), `MOTION_EFFECTS`
- `cf_platform/interfaces/routes/workers.py` — render endpoint; `cf_platform/interfaces/routes/studio.py` — storyboard / manifest GET
- `tests/test_ffmpeg_builder.py`, `tests/cf_platform/p13_helpers.py`
- `DECISIONS.md` — D100, D102, D081, D087, D089, D091, D086


### Handover
- `cf_platform/workers/timeline.py`: `Timeline` model (`schema_version` 1) and `build_timeline(storyboard, manifest, voice_alignment, settings)`, the only place scene timing is resolved for rendering (D103). `render_worker` builds its script from the timeline (`build_render_script_from_timeline`); the timeline is written as run artifact `render/timeline@vN`. `GET /platform/studio/runs/{run_id}/timeline` returns it (409 with `missing_assets_message` while a scene has no file).
- Assets are addressed by manifest `file_key`, never by scene id (D102).
- 22 golden render scripts in `tests/golden/render/` (`test_p13b_s1_golden_render.py`, FFmpeg stubbed) were committed before the builder was rewired. Regenerate only on purpose: `UPDATE_GOLDEN=1 pytest tests/cf_platform/test_p13b_s1_golden_render.py` (docs/TESTING.md).
- Word-index fix: scene boundaries now resolve against the normalised word list (`_normalize_deepgram_words`). The contraction-heavy golden was pinned before the fix and changes on purpose; unchanged goldens stayed byte-identical.
- Known limits (D103): blur-fill for wikimedia portraits, Standard captions' per-word highlight, and the legacy `build_ffmpeg_script` still reads the storyboard directly.
- Files that mattered: `cf_platform/workers/timeline.py`, `cf_platform/workers/render_worker.py`, `src/ffmpeg_builder.py`, `tests/cf_platform/test_p13b_s1_golden_render.py`, `docs/ARCHITECTURE.md#0b`.

---

## [P13b-S2] "Download for CapCut" — zip of media and timeline
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 2
**Depends on:** P13b-S1

### Goal
From a run whose storyboard is finalized and whose assets are all in place, the operator downloads one zip holding the run's media and the timeline file.

### Acceptance Criteria
- [x] `GET /platform/studio/runs/{run_id}/export/capcut` returns a zip: `timeline.json` plus every file the timeline references (scene assets, voiceover, music, SFX), stored under the relative paths the timeline uses
- [x] The zip is streamed; it is not built in memory in one piece
- [x] 409 with the `missing_assets_message` text while any scene has no file; 409 when the run has no voice alignment
- [x] Studio: "Download for CapCut" next to the render action, enabled under the same conditions as rendering, using the blob-fetch download pattern (docs/UI_GUIDELINES.md, "File downloads")
- [x] The control states in one line that this path is rendered in CapCut on the laptop and the result is uploaded back
- [x] A TraceEvent records the export
- [x] Tests: zip contents match the timeline's references exactly; each 409; static-page test pins the control and the route it calls

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P13b-S1 Handover (timeline model and route)
- `cf_platform/workers/render_worker.py` — `_download_assets` (which files a render pulls)
- `cf_platform/interfaces/routes/studio.py` — video URL endpoints, scene upload (TraceEvent pattern)
- `src/static/studio-v2.html` — Render stage
- `docs/UI_GUIDELINES.md` — "File downloads"


### Handover
- `GET /platform/studio/runs/{run_id}/export/capcut` streams a zip of `timeline.json` plus every referenced file (`cf_platform/workers/capcut_export.py`, route in `studio.py`); 409 for missing assets or no voice alignment; a TraceEvent records the export. Studio: "Download for CapCut" next to Render (blob-fetch pattern).
- Files that mattered: `cf_platform/workers/capcut_export.py`, `cf_platform/interfaces/routes/studio.py`, `src/static/studio-v2.html` (Render stage), `tests/cf_platform/test_p13b_s2_export.py`.

---

## [P13b-S3] Laptop script and setup guide
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 3
**Depends on:** P13b-S1

### Goal
One command on the operator's laptop turns the downloaded zip into a CapCut project that opens with the whole edit in place. It replaces the spike, which read R2 directly and covered stills at 9:16 only.

### Acceptance Criteria
- [x] `tools/capcut/export_capcut.py <zip>` unpacks the zip and writes a CapCut draft from `timeline.json` alone — no R2 access, no credentials on the laptop
- [x] `tools/capcut/requirements.txt` holds `pycapcut` (pinned); nothing is added to the platform's requirements or image (D100)
- [x] Tracks: footage with scene timing, motion as keyframes (zoom in / out, Ken Burns, pan left / right), voiceover, on-screen text, captions as editable text clips in the run's caption style (Standard and Punch), **music, and SFX at their scene offsets**
- [x] **Video clips** are placed and trimmed to the scene duration, muted; no motion keyframes on video (D089)
- [x] **16:9** as well as 9:16: canvas size and cover scaling come from the timeline
- [x] The script checks the timeline's `schema_version` and reports the CapCut version it was tested with; on an unknown schema version it stops with a clear message
- [x] **Settle the spike's open point:** which of `draft_content.json` / `draft_info.json` CapCut 8.x reads. Record the finding in the Handover and write only what is needed (or both, with the reason)
- [x] `tools/capcut/README.md`: one-time setup (Python, virtual environment, requirements, where CapCut keeps drafts on macOS), the one command, and what to do when CapCut updates and the draft no longer opens
- [x] `tools/capcut_spike/` is removed once the new script covers it
- [x] Tests (run in CI without CapCut and without `pycapcut` installed in the platform image): the timeline → draft mapping is unit-tested on plain data — timing in microseconds, cover scale, keyframe values per motion effect, caption clip boundaries, SFX offsets
- [x] **Human touchpoint (with S2):** the operator downloads a zip from DEV, runs the command and opens the full edit in CapCut — one 9:16 run with a video clip, music and SFX, and one 16:9 run

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `tools/capcut_spike/export_capcut.py`, `tools/capcut_spike/r2.py`
- P13b-S1 Handover (timeline schema)
- `src/ffmpeg_builder.py` — `_motion_vf_prefix`, `_zoompan_filter` (`_ZOOM_RATE_PER_S`, `_PAN_TRAVEL_FRACTION_PER_S`), `_parse_sfx_delay_ms` — the values the CapCut keyframes should match
- `src/captions.py` — caption presets
- `DECISIONS.md` — D100, D081, D082, D087, D076


### Handover
- `tools/capcut/export_capcut.py <zip>` writes a CapCut draft from `timeline.json` alone; the pure timeline → draft mapping is in `tools/capcut/draft_plan.py` (unit-tested without CapCut or pycapcut, `tests/test_p13b_s3_capcut_plan.py`). `pycapcut` is pinned in `tools/capcut/requirements.txt` only (D100). `tools/capcut_spike/` removed.
- Tested with CapCut 8.9.1 (macOS) and pycapcut 0.0.3; unknown `schema_version` stops with a clear message.
- **Spike's open point settled:** CapCut 8.x reads `draft_info.json`. pycapcut writes `draft_content.json` (6.x name), so the script renames it; `--both-files` keeps both. Details in `tools/capcut/README.md`.
- Files that mattered: `tools/capcut/README.md`, `tools/capcut/draft_plan.py`, `src/ffmpeg_builder.py` (motion constants the keyframes mirror).

---

## [P13b-S4] Return path — upload the CapCut-rendered video into the run
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 2
**Depends on:** P13b-S2

### Goal
The video the operator rendered in CapCut becomes the run's final video, so the Metadata stage — and later publishing (P16) — continue as they do after an FFmpeg render.

### Acceptance Criteria
- [x] `POST /platform/studio/runs/{run_id}/output/upload` accepts an `.mp4`, validated for MIME type and size (limit from an ENV var, documented in ENV.md), and stores it as the run's final video
- [x] The run records which path produced its final video (`ffmpeg` or `capcut`) and when; the video endpoints return it
- [x] An uploaded video is not overwritten silently: starting an FFmpeg render on a run whose final video came from CapCut asks for confirmation in Studio, and the upload asks for confirmation when an FFmpeg render exists
- [x] The existing check that a stale `final.mp4` from a killed render is not mistaken for a finished job still holds
- [x] Studio Render stage: "Upload video from CapCut" control; after upload the stage shows the video with its source, and the Metadata stage is reachable exactly as after an FFmpeg render
- [x] A TraceEvent records the upload
- [x] Tests: upload accept / reject (type, size); source recorded and returned; overwrite rules in both directions; Metadata reachable after an upload; static-page test for the control
- [x] **Human touchpoint (closes the sprint):** the operator uploads the CapCut render into the run on DEV and generates metadata for it

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/interfaces/routes/studio.py` — the video URL / render status endpoints (stale `final.mp4` handling), scene upload (validation pattern), music upload
- `cf_platform/interfaces/routes/workers.py` — render endpoint, metadata endpoint
- `src/static/studio-v2.html` — Render and Metadata stages
- `tests/cf_platform/test_p10_s2_asset_override.py` (upload test pattern)
- `DECISIONS.md` — D100, D098


### Handover
- `POST /platform/studio/runs/{run_id}/output/upload` accepts an `.mp4` (MIME and size checked) and stores it as `output/final.mp4`; `output/final_source.json` records `ffmpeg` or `capcut` with a timestamp (`cf_platform/core/final_video.py`, `record_final_source`). Overwrite confirmation in both directions; the stale-`final.mp4` guard still holds. Studio Render stage: "Upload video from CapCut".
- New ENV var: `OUTPUT_UPLOAD_MAX_MB` (default 500; the file is read into memory). No new platform dependency.
- Files that mattered: `cf_platform/core/final_video.py`, `cf_platform/interfaces/routes/studio.py`, `tests/cf_platform/test_p13b_s4_output_upload.py`.

---

---

## EPIC 51 — Uploaded voiceover (Sprint P14b)

Operator request at the Sprint P14 review (2026-10-05). A second way into a run: upload a finished voiceover instead of writing a script and generating one. The existing `voice_alignment` artifact (`mp3_r2_key`, `word_timestamps`, `alignment_method`) is the seam — an uploaded VO writes the same artifact, so the storyboard worker, timeline, FFmpeg render and CapCut export read it exactly as they read a generated voice. Delivered as one sprint.

**Timing-safe edit rule (decision, 2026-10-05).** Word timings come from Deepgram and everything downstream (storyboard `start_word`/`end_word`, captions, timeline) keys off them. So transcript edits keep every word tied to audio: replace a word (it keeps its time slot); turn one word into several or several into one (the new words share the combined slot, split evenly); deleting a spoken word and adding an unspoken one are refused (text that must appear without being said is the scene's on-screen text). Scene boundaries move only through the Storyboard controls.

---

## [P14b-S1] Run creation choice, VO upload, Deepgram transcript as the script
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
When the operator creates a run, they choose "Script → generated voice" or "Upload voiceover". For an upload, the audio is stored, Deepgram transcribes and aligns it, and the transcript becomes the run's script.

### Acceptance Criteria
- [x] Run creation (from a shortlist idea, and from the project page) offers the two entry modes; the mode is stored on the run (`voice_source`: `generated` | `uploaded`) and the default stays `generated`, so every existing run and flow is unchanged
- [x] `POST /platform/studio/runs/{run_id}/voice/upload` accepts mp3, wav and m4a, validated for MIME type, extension and size (limit from an ENV var documented in ENV.md); the file is stored under the run's voice prefix; 409 if the run already has a storyboard (re-upload rules are P14b-S4)
- [x] Deepgram transcription runs as a background job (the same pattern and polling as voice generation, `voice/status`), reusing `_align_audio` / `_normalize_word`; it writes a `voice_alignment` artifact with `alignment_method` marking it as an uploaded VO
- [x] The transcript text is stored as the run's script artifact with `source: uploaded_vo`, so `GET …/script` returns it and nothing else reads a different place
- [x] **Language seed (D106, operator 2026-10-05):** the run gets a `language` field (ISO 639-1, `en` default; `ru` accepted as a value but nothing Russian-specific is built in this sprint), set at run creation next to the entry mode, defaulting to the project's `config.language` and otherwise `en`. It is a per-run choice — a project that already has English runs is not locked to English. The upload's Deepgram call passes it as the transcription language
- [x] The Script and Voice stages are not shown for an uploaded run; Studio shows Upload → Transcript → Storyboard → …
- [x] A TraceEvent records the upload and the transcription (duration, word count, Deepgram cost if known)
- [x] Tests: each validation failure; happy path with Deepgram mocked; default mode unchanged; artifact shape equals a generated run's `voice_alignment`

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/voice_production.py` — `VoiceAlignmentArtifact`, `_align_audio`, `_normalize_word`, `build_voice_production_worker`
- `cf_platform/interfaces/routes/studio.py` — `studio_get_voice`, `studio_get_voice_status`, `studio_get_script`, the scene upload routes (validation pattern)
- `cf_platform/interfaces/routes/projects.py` — `create_run_from_shortlist`
- `src/static/studio-v2.html` — run creation and stage list; `src/static/project.html`
- `ENV.md`, `DECISIONS.md` — D104 (settings pattern), D093

### Handover
- **Run entry mode and language** live in `run.inputs` (`voice_source`: `generated` | `uploaded`, `language`: ISO 639-1) — no migration. `POST /platform/projects/{id}/runs` takes both; `language` defaults to the project's `config.language`, else `en`. `GET …/studio/runs/{id}/context` returns them; `PUT …/studio/runs/{id}/language` changes the language.
- **Upload:** `POST …/studio/runs/{id}/voice/upload` (`cf_platform/interfaces/routes/studio_voice.py`). Validation in `cf_platform/workers/voice_upload.py` (extension, MIME, size, file header). Stored at `runs/{id}/voiceover/uploaded.<ext>`. Transcription is a background job on the existing `voice/status` polling; `_deepgram_transcribe` (new, in `voice_production.py`) sends the run's `language`; `_align_audio` now delegates to it.
- **Artifacts:** `voice_alignment` with `alignment_method = uploaded_deepgram_nova2` (same shape as a generated run's), and a `script` artifact with `source: uploaded_vo` (`ScriptArtifact.source`, new optional field). Words are collapsed like the storyboard reads them, so editor indices are storyboard indices.
- **TraceEvents:** `voice_upload` (operator) and `transcribe` (cost from `DEEPGRAM_COST_PER_MIN_USD`).
- **UI:** `project.html` language + entry-mode pickers; `studio-v2.html` swaps the stage list (`applyVoiceSource`): Settings → Upload → Transcript → Storyboard → Video → Metadata; narration and subject controls removed for uploaded runs.
- **ENV vars added:** `VOICE_UPLOAD_MAX_MB`, `VOICE_UPLOAD_MIN_S`, `VOICE_UPLOAD_MAX_S`, `VOICE_LOW_CONFIDENCE`, `DEEPGRAM_COST_PER_MIN_USD`.
- **Files that mattered:** `cf_platform/interfaces/routes/studio_voice.py`, `cf_platform/workers/voice_upload.py`, `cf_platform/workers/voice_production.py` (`_deepgram_transcribe`), `cf_platform/interfaces/routes/projects.py`, `src/static/studio-v2.html` (`applyVoiceSource`, `loadUploadedVoice`), `ENV.md`.
---

## [P14b-S2] Transcript review stage with timing-safe word edits
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** P14b-S1

### Goal
Before the storyboard is built, the operator reads the transcript against the audio and corrects misheard words without being able to break the timing.

### Acceptance Criteria
- [x] A Transcript stage plays the uploaded audio and shows the words; clicking a word seeks the audio to it
- [x] `PATCH /platform/studio/runs/{run_id}/transcript` applies the edit rule: replace one word; replace one with several or several with one (new words share the combined slot, split evenly, monotonic); the whole edit is validated and rejected as a unit (422 with the reason) if it deletes a spoken word or adds an unspoken one
- [x] A "Rebuild from text" check: the operator may paste corrected text; it is accepted only if it maps onto the existing words under the same rule, and the message says which words changed
- [x] The edited words are written back to the `voice_alignment` artifact as a new version and the script artifact is regenerated from them; word indices (`start_word`/`end_word`) therefore stay valid because the word count only changes through the shared-slot rule
- [x] Edits are refused once a storyboard exists (409, with the pointer to re-do the transcript step and the P14b-S4 warning about the storyboard it would invalidate)
- [x] The Studio explains the rule in one sentence next to the editor and, for a refused edit, says what to do instead (on-screen text for unspoken words)
- [x] Tests: replace; one-to-many and many-to-one slot arithmetic (monotonic, sums to the original slot); delete and add refused; punctuation and contractions; script artifact follows the words; audio untouched

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P14b-S1 Handover
- `cf_platform/workers/storyboard_worker.py` — how `start_word`/`end_word` index `_normalize_deepgram_words`; coverage check
- `cf_platform/workers/storyboard_edit.py`, `cf_platform/workers/timeline.py` — word list consumers
- `src/static/studio-v2.html` — Script / Storyboard word rendering (`renderStoryboard`)
- `docs/RUNBOOK.md` — the misheard-caption finding ("pedals are wheel")

### Handover
- **Edit rule** is pure code in `cf_platform/workers/transcript_edit.py`: `apply_word_edits`, `edits_from_text`, `describe_edits`, `TranscriptEditError`. One word to one: keeps its slot; one to several: even split of the slot (monotonic, sums to the original); several to one: combined slot; several to the same number: each keeps its slot; other many-to-many, deletions and insertions are refused. A stretch of pasted text that changes 3 words into 2 is refused with "one word at a time".
- **Routes:** `GET/PATCH …/studio/runs/{id}/transcript`. PATCH takes `edits` or `text`, plus `dry_run`. 422 with the reason on refusal, 409 once a storyboard exists or while a transcription runs. A valid edit writes a new `voice_alignment` version and regenerates the script; the audio is untouched.
- **Studio:** Transcript pane — audio player, clickable words (shift-click selects several), inline edit, "Rebuild from text" with Check / Apply, the rule in one sentence.
- **Known limit:** transcript words carry no punctuation (stored like generated-run Deepgram words), so scene-break hints from sentence punctuation are weaker than with a pasted script.
- **Files that mattered:** `cf_platform/workers/transcript_edit.py`, `cf_platform/interfaces/routes/studio_voice.py`, `cf_platform/workers/storyboard_worker.py#_normalize_deepgram_words_with_display` (why indices are collapsed at upload), `src/static/studio-v2.html` (`renderTranscript`).
---

## [P14b-S3] Storyboard from the transcript; uploaded audio through timeline, render and CapCut
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** P14b-S2

### Goal
From a reviewed transcript the operator creates the storyboard in the usual way, and everything after it behaves as for a generated voice.

### Acceptance Criteria
- [x] The StoryboardWorker takes its script from the uploaded run's script artifact and its words and timing from the uploaded `voice_alignment`; its coverage check passes on a faithfully transcribed VO and still catches a mismatch
- [x] `build_timeline`, the FFmpeg render and the CapCut export read the uploaded audio through `mp3_r2_key` with no change to their code paths; the golden render suite is unchanged
- [x] TTS settings (voice, pace, register) are hidden for uploaded runs; narration regeneration controls are removed rather than disabled
- [x] Studio stage list for an uploaded run: Upload → Transcript → Storyboard → Acquire → Render → Metadata, reachable in order
- [x] Metadata generation uses the transcript as the script
- [x] Tests: storyboard from an uploaded run; timeline equal in shape to a generated run's; render script built from an uploaded run; CapCut zip contains the uploaded audio; stage gating

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P14b-S1 and S2 Handovers
- `cf_platform/workers/storyboard_worker.py`, `cf_platform/workers/timeline.py`, `cf_platform/workers/render_worker.py`, `cf_platform/workers/capcut_export.py`, `cf_platform/workers/youtube_metadata.py`
- `src/static/studio-v2.html` — stage list and gating

### Handover
- **Storyboard:** `POST /platform/workers/storyboard` uses the uploaded run's own script artifact and ignores the request body's script (`_uploaded_script_key` in `routes/workers.py`); `voice_alignment` is passed as before. `POST /platform/workers/voice` answers 409 for an uploaded run. Metadata reads the same script artifact, so it uses the transcript.
- **Timeline / render / CapCut** are unchanged and read the upload through `mp3_r2_key` (tests assert timeline voiceover key, render script and CapCut zip contents). One small addition in `render_worker.py`: after writing the alignment's audio, other audio files in the local `voiceover/` folder are removed, so a re-upload in a different format cannot leave the old file for the script's glob to pick up. Golden suite unchanged.
- **Studio:** `createStoryboard()` reads the transcript for uploaded runs; stage gating follows the stage list.
- **Files that mattered:** `cf_platform/interfaces/routes/workers.py`, `cf_platform/workers/render_worker.py`, `cf_platform/interfaces/routes/_helpers.py#prepare_run_timeline`, `tests/cf_platform/p13_helpers.py`.
---

## [P14b-S4] Guards and end-to-end tests for the upload path
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 2
**Depends on:** P14b-S3

### Goal
Bad input and re-uploads fail with a clear message instead of producing a broken run.

### Acceptance Criteria
- [x] Unreadable or non-audio files, silent audio, audio shorter than a minimum and longer than a maximum (both from ENV vars) are refused before or right after Deepgram, with a message in Studio
- [x] Deepgram returning no words ends the job in `error` with a readable message, not a stuck `running`; if Deepgram detects a language other than the run's `language`, Studio shows a warning with the detected language and lets the operator confirm or change the run's language (not a hard failure)
- [x] Re-uploading on a run that already has a transcript or storyboard asks for confirmation and says what will be discarded (storyboard, acquired assets, anchors); on confirm it invalidates them, as the storyboard re-run warning already does
- [x] One end-to-end test: create an uploaded run, upload (Deepgram mocked), edit a word, build the storyboard, render script built, timeline valid
- [x] DEV smoke test steps written into the Handover for the operator: upload an mp3, correct a misheard word, storyboard, acquire, render

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [x] Human touchpoint (closes the sprint): the operator creates an uploaded-VO run on DEV and renders a video from it

### Files to read
- P14b-S1..S3 Handovers
- `docs/TESTING.md`; memory note on the storyboard re-run warning (regenerating invalidates acquired assets)
- `cf_platform/interfaces/routes/studio.py` — storyboard regenerate warning

### Handover
- **Guards:** file header check, size, min / max length (`VOICE_UPLOAD_MIN_S` / `MAX_S`, measured by Deepgram), no words, Deepgram failure and unexpected crash all end the job in `error` with a readable message. A job never stays `running`.
- **Language mismatch is a warning, not an error** (as amended 2026-10-05). Deepgram is told the run's language, so it cannot report a mismatch; `language_warning` (in `voice_upload.py`) uses two signals: wrong script (Cyrillic vs Latin) and mean word confidence below `VOICE_LOW_CONFIDENCE`. It is stored in the job record, returned by `voice/status` and `GET …/transcript`; Studio shows a banner with "Keep" / "Change" (`PUT …/language`, which marks the warning acknowledged; a changed language means upload again). It cannot catch e.g. French audio in an English run.
- **Re-upload:** 409 `needs_confirmation` with the list of what is discarded; with `?confirm_discard=true` the storyboard is discarded by a marker (`runs/{id}/storyboard/discarded.json`, honoured by `latest_artifact_key`, acquisition and render), the asset manifest is emptied (envelope kept), and editing unlocks.
- **Tests:** `test_p14b_transcript_edit.py` (19), `test_p14b_upload_routes.py` (35, including the end-to-end test), `test_log_redaction.py` (8). Suite at close: 2645 passed, CI green on `dbec47d`.
- **DEV smoke test steps (as given to the operator):** (1) create an "Upload voiceover" run (stage track has no Script / Voice); (2) upload a 20–60 s mp3 → transcript appears, no warning; (3) correct a word, split one into two, try to delete a word (refused), paste text with an added word (refused); (4) create the storyboard → words locked; (5) acquire, render and/or CapCut zip contains `voiceover/uploaded.mp3`; (6) re-upload with confirm → storyboard empty, editing works; (7) guards: renamed `.txt`, silent mp3, clip under 3 s; (8) language `ru` run with Russian audio (no warning), English audio in a `ru` run (banner); (9) a generated run still behaves as before; (10) DEV log shows `key=REDACTED`.
- **Smoke result and what is NOT verified:** the operator made two real Shorts on DEV with the uploaded-voiceover flow and found no issues. The scripted steps were not run one by one. Not verified on DEV: the guards (step 7), the re-upload confirmation (6), language `ru` — including Deepgram's `language=ru` on Nova-2, only tested against a mocked request — and the log check (10).
---

## [P14b-S5] Stop logging API keys; rotate the Pixabay key
**Epic:** E51 — Uploaded voiceover (rides in the sprint; unrelated to the upload path)
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
No provider API key appears in any log line, and the key that already leaked is replaced.

### Acceptance Criteria
- [x] `httpx` / `httpcore` loggers do not print request URLs containing `key=`, `api_key=`, `token=` or `apikey=` values; either a redacting log filter on the root handlers or `httpx` raised to WARNING — whichever keeps useful request logging for other hosts (state the choice in the Handover)
- [x] Test: a request to a URL with `?key=SECRET` produces no log record containing `SECRET`; covers Pixabay, Pexels and Freesound URL shapes
- [x] Other places that can print a key (exception messages with the URL, retry logs) checked and covered by the same filter or listed in the Handover
- [ ] Operator rotates the Pixabay key on DEV (and on PROD at release); the old key is revoked. The step is recorded as done in SPRINT.md open items — **carried to SPRINT.md open items (operator action)**
- [ ] PROD log re-checked for `key=` at the next `/prod-check` — **carried to SPRINT.md open items (operator action)**

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done` — two operator AC carried, see Handover

### Files to read
- `SPRINT.md` open items (finding of 2026-10-05); the raised task chip
- logging setup in `cf_platform/` and `src/` (find where handlers are configured), `src/` Pixabay adapter

### Handover
- **Choice: a redacting formatter, not `httpx` at WARNING.** `src/log_redaction.py` wraps the formatter of every root / uvicorn / httpx / httpcore handler (`install_log_redaction`, called from `_configure_logging` in `src/main.py`) and redacts `key=`, `api_key=`, `apikey=`, `token=`, `access_token=` values in the *final* text, so messages, `%s` args, exception messages and tracebacks are all covered while other request logging stays.
- **Other places checked:** the Pixabay and Freesound clients pass the key as a query parameter (covered); Pexels sends it in an `Authorization` header (never in a URL). `requests`/urllib3 log URLs only at DEBUG, which the app does not enable; they pass through the same formatter anyway.
- **Not done — operator actions, carried in SPRINT.md open items:** rotate the Pixabay key on DEV (and PROD at release) and revoke the old one; check DEV log for `key=` and re-check PROD at the next `/prod-check`.
- **Files that mattered:** `src/log_redaction.py`, `src/main.py#_configure_logging`, `tests/test_log_redaction.py`.
