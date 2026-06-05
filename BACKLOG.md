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
curl -X POST https://content-factory-dev-production.up.railway.app/runs \
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
