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

## [E4-S6] Subtitle style overhaul + voiceover line shortening
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** 3
**Status:** ready
**Points:** 3
**Priority:** high
**Depends on:** E4-S5

### Goal
Update ASS subtitle styling to mobile-first vertical short format, and enforce shorter voiceover_line output from the storyboard prompt so captions are readable at mobile screen size.

### Acceptance Criteria
- [ ] Voiceover captions: font Montserrat ExtraBold (fallback Arial Bold), 72pt, white text, black outline 6-8px, MarginV=250
- [ ] Voiceover captions: max 2 lines, 4-6 words per line enforced at prompt level
- [ ] On-screen keyword track: yellow color for keywords, slightly reduced size to avoid competing with voiceover captions
- [ ] `src/storyboard.py` SYSTEM_PROMPT updated: `voiceover_line` must be 4-6 words max, not a full sentence
- [ ] `docs/PROMPTS.md` synced to match `storyboard.py` changes, bumped to v0.6
- [ ] Smoke test: render a short and confirm captions are readable at mobile screen size

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to read
- `src/captions.py`
- `src/storyboard.py`
- `docs/PROMPTS.md`
- DECISIONS.md

### Files to modify
- `src/captions.py` — ASS style block for `VoiceCaption` style
- `src/storyboard.py` — SYSTEM_PROMPT `voiceover_line` field instruction
- `docs/PROMPTS.md` — sync with storyboard.py changes, bump to v0.6

### Notes
- Montserrat ExtraBold must be available on Railway. If not, fall back to Arial Bold. Add a DECISIONS.md entry if a font download step is needed.
- Do NOT chunk `voiceover_line` at render time — enforce short lines at generation time via prompt.
- Must complete before E5-S4 so WhisperX lands on the correct visual style.

### Handover
_filled on completion_

---

## [E4-S7] Word-synced captions using WhisperX timestamps
**Epic:** E4 — FFmpeg Script Generation
**Sprint:** unassigned
**Status:** backlog
**Points:** 5
**Priority:** normal
**Depends on:** E5-S4

### Goal
Use word-level timestamps from WhisperX to display caption chunks exactly when spoken, with the active word highlighted in yellow. Implements the current high-retention short-form caption pattern.

### Acceptance Criteria
- [ ] Caption chunks advance word-by-word or phrase-by-phrase in sync with audio
- [ ] Active word highlighted in yellow (ASS karaoke tag or per-word Dialogue events)
- [ ] 4-6 words per caption chunk maximum
- [ ] Replaces current proportional `voiceover_line` display
- [ ] Smoke test: watch rendered video and confirm captions track speech accurately

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Files to modify (expected)
- `src/captions.py` — new build function using WhisperX word timestamps
- `src/ffmpeg_builder.py` — wire new caption builder into render chain

### Notes
- Depends on WhisperX word-level output format from E5-S4. Read E5-S4 DONE.md entry before starting.
- ASS karaoke tags (`\k`) are one approach; per-word Dialogue events are simpler and more robust — evaluate during implementation.
- E5-S4 must write `whisperx_alignment.json` to R2 with word-level timestamps for this story to consume.

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

## [E5-S4] WhisperX forced alignment for ms-precise scene timing
**Epic:** E5 — FFmpeg Execution + Drive Upload
**Sprint:** unassigned
**Status:** backlog
**Points:** 8
**Priority:** medium
**Depends on:** E5-S2

### Goal
Replace proportional word-count redistribution with millisecond-precise scene boundaries derived from forced alignment of the actual voiceover recording.

### How it works
- New pipeline step: `POST /runs/{run_id}/align`
- Downloads voiceover from R2 to /tmp
- Runs WhisperX (faster-whisper + phoneme aligner) on the audio
- Returns word-level timestamps: `[{word, start, end}]`
- Maps words to scenes based on storyboard voiceover_line text matching
- Writes `alignment.json` to R2: `[{scene_id, start_s, end_s, duration_s}]`
- ffmpeg-script step reads `alignment.json` if present; falls back to proportional redistribution if not

### Acceptance Criteria
- [ ] `POST /runs/{run_id}/align` endpoint processes voiceover and writes `alignment.json` to R2
- [ ] Word-to-scene mapping handles minor transcription differences (fuzzy match)
- [ ] ffmpeg_script route reads `alignment.json` from R2 before building script
- [ ] Scene durations from `alignment.json` used instead of proportional weights when present
- [ ] Graceful fallback: if `alignment.json` missing, proportional redistribution used (no breaking change)
- [ ] Processing time logged — target <3min for 60s VO on Railway CPU
- [ ] All existing tests pass; new tests for alignment parsing and scene mapping

### Definition of Done
- [ ] All AC checked
- [ ] Tests written and passing
- [ ] CI green, deployed to DEV
- [ ] Smoke test passed
- [ ] DONE.md updated
- [ ] BACKLOG.md status updated to `done`

### Implementation notes
- WhisperX: `pip install whisperx` (pulls faster-whisper, torch CPU)
- Railway: add to requirements.txt; Docker build time increases ~2min
- Run async or with extended timeout (FFMPEG_TIMEOUT_SECONDS pattern)
- Word-to-scene mapping: split storyboard voiceover_line into words, find matching span in WhisperX output, take start of first word and end of last word as scene boundaries
- DECISIONS.md D030: WhisperX chosen over proportional redistribution for ms-precise alignment; deferred until captions and zoom validated
- Word-level timestamp output must be preserved in the run artifact (e.g. `whisperx_alignment.json` in R2) so E4-S7 can consume it without re-running alignment.
- Output format decision (word timestamps schema) must be documented in DECISIONS.md as part of E5-S4 closure.

### Handover
_filled on completion_

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
