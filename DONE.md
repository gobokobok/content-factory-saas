# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._

Format:
## [E#-S#] Story title
**Completed:** YYYY-MM-DD
**Sprint:** N
**Handover:** [summary of what was built, key decisions, anything the next story needs to know]

---

## [E3-S1] Pexels stock footage integration
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/pexels.py`: `PexelsClient(api_key, per_page=5)` — synchronous `requests`-based client. Key method: `acquire_for_entry(entry, run_id, storage) → Optional[PexelsAcquireResult]`. Tries `primary_query` then `fallback_query`. `hard_cut` → Videos API → `runs/{run_id}/video/{scene_id}.mp4`; `still_with_motion`/`animated` → Photos API → `runs/{run_id}/images/{scene_id}.jpeg`. Returns `None` when both queries miss (E3-S3 chains to Replicate). Raises `PexelsError` on non-retryable API error.
- Module-level helpers: `_pick_best_video_file(video)` — highest height ≤ 1080px, tie-broken by width; `_pick_best_photo(photos)` — requires ≥ 1920×1080, minimum excess area.
- `src/models.py`: `ManifestEntry` gains `source: Optional[str]` and `file_key: Optional[str]`. `PexelsAcquireResult(scene_id, source="pexels", file_key, status="acquired")` added.
- `src/storage.py`: `R2Client.upload_bytes(key, data, content_type)` added.
- `src/exceptions.py`: `PexelsError` added.
- Rate limiting: exponential backoff on 429 — up to 3 retries (1s, 2s, 4s).
- No new ENV vars (uses existing `PEXELS_API_KEY`, `PEXELS_PER_PAGE`). No new dependencies.
- 121 total tests passing (26 new). End-to-end smoke test deferred to E3-S3 (requires orchestrator route).
**Promoted to backlog:** none

---

## [E6-S1] End-to-end pipeline UI (Runs + Storyboard + Manifest)
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/static/pipeline.html`: self-contained HTML page (inline CSS/JS, no frameworks). Slug validated before enabling submit; VO script textarea required. Sequentially calls `POST /runs` → `POST /runs/{run_id}/storyboard` → `POST /runs/{run_id}/manifest`. Per-step status dots: `○` pending / `◌` running / `●` complete / `✕` failed. Storyboard step shows 30–60s loading message. Manifest step displays scene count + clip type breakdown dict. Any failed step stops the chain, surfaces error detail, re-enables submit.
- `src/main.py`: `GET /` now serves `pipeline.html` (was `create-run.html`). `create-run.html` preserved in `/static` as reference.
- No new ENV vars. No new dependencies. 95 tests passing.
- Smoke test passed on Railway DEV: slug `messy-house-messy-head`, 10 scenes, all steps complete (still_with_motion: 4, animated: 3, hard_cut: 3).
**Promoted to backlog:** none

---

## [E2-S1] Asset manifest generation
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/manifest.py`: `build_manifest(run_id, storyboard_data) → AssetManifest` — pure transformation, no API calls. Maps `visual_prompts.primary_stk → primary_query`, `fallback_stk → fallback_query`, `ai_generate → ai_generate_prompt`. Raises `ManifestError` on invalid storyboard. `clip_type_breakdown(manifest) → dict[str, int]` helper for summary stats.
- `src/routes/manifest.py`: `POST /runs/{run_id}/manifest` — reads `runs/{run_id}/storyboard.json` from R2 (→404 on missing), builds manifest (→422 + run_log `failed` on bad storyboard), uploads `runs/{run_id}/asset_manifest.json`, updates run_log `asset_manifest: complete`. Returns `{status, manifest_key, scene_count, clip_type_breakdown}`.
- `src/models.py`: `ManifestEntry`, `AssetManifest`, `ManifestResponse` added. E3 asset acquisition reads `AssetManifest.entries` — each entry has `primary_query`, `fallback_query`, `ai_generate_prompt`, `clip_type`, and `status: "pending"`.
- `src/exceptions.py`: `ManifestError` added.
- `src/main.py`: manifest router registered via `app.include_router(manifest_router.router)`.
- R2 key pattern: `runs/{run_id}/asset_manifest.json`.
- `tests/test_manifest.py`: 27 tests, all passing. 95 total.
- No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

## [E6-S0] Minimal run creation UI
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/static/create-run.html`: self-contained HTML form (inline CSS/JS). Slug validated with `/^[a-z][a-z0-9-]*[a-z0-9]$/` before enabling Submit. POSTs to `/runs`, displays `run_id` + `storage_prefix` on 201, surfaces error detail on non-201, catches network errors.
- `src/main.py`: `GET /` serves `create-run.html` via `FileResponse`. `_STATIC_DIR = Path(__file__).parent / "static"` — future pages/assets go here.
- No `StaticFiles` mount — skipped to avoid `aiofiles` dependency (page has no external assets). Add `StaticFiles` + `aiofiles` when E6-S1 introduces `app.js` / `style.css`.
- No new ENV vars. No new dependencies. 68 tests passing.
**Promoted to backlog:** none

---

## [E1-S3] Storyboard generation
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/storyboard.py`: `generate_storyboard(script, settings) → Storyboard` (async). Internally: `_call_claude_api` uses `AsyncAnthropic` with prompt caching (`cache_control: ephemeral`) on the v0.4 system prompt. `_parse_storyboard_response` splits Claude text output on `---` into GLOBAL / SCENE blocks / SUMMARY, then delegates to `_parse_global`, `_parse_scene`, `_parse_summary`.
- `src/routes/storyboard.py`: `POST /runs/{run_id}/storyboard`. On success: uploads `storyboard.json` to `runs/{run_id}/storyboard.json` and calls `update_run_log(..., "complete", output_url=key)`. On failure: calls `update_run_log(..., "failed", error=str(exc))` then returns HTTP 500.
- `src/models.py`: `Storyboard` model — the `global` field is aliased (`Field(alias="global")`); always serialise with `model_dump(by_alias=True, mode="json")`. `StoryboardScene.clip_type` validated as `Literal["hard_cut", "still_with_motion", "animated"]`.
- `src/exceptions.py`: `StoryboardAPIError` (Claude failures), `StoryboardParseError` (parse failures).
- `src/storage.py`: `update_run_log` now accepts optional `error: str` to persist failure messages to `run_log.json`.
- `tests/test_storyboard.py`: 21 tests (parser unit + route integration). Route mock pattern: `patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock)`.
- Response field is `storyboard_key` (R2 key path), not `storyboard_url` — Drive was removed in E1-S2b.
- 68 total tests passing.
**Promoted to backlog:** none

---

## [E1-S2b] Migrate storage from Google Drive to Cloudflare R2
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/storage.py`: `R2Client(account_id, access_key_id, secret_access_key, bucket_name)`. Methods: `create_run_folder(run_id) → prefix`, `upload_json(key, data)`, `get_json(key) → dict`, `update_run_log(run_id, step, status, output_url=None)`. R2 is flat — all "folders" are key prefixes; no folder creation needed.
- `src/exceptions.py`: `StorageError` — the single domain exception for all storage failures. Catch in routes, raise from storage.py.
- `src/models.py`: `RunCreateResponse.storage_prefix` replaces `drive_folder_id`. `StepLog.output_url: Optional[str]` added.
- `src/config.py`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` — all required.
- `src/routes/runs.py`: run_id built as `{today}_{slug}` in route; passed to `R2Client.create_run_folder(run_id)`.
- `tests/test_storage.py` (18 tests) + `tests/test_runs.py` (13 tests) + `tests/test_health.py` updated. 47 total passing.
- Key pattern for E1-S3: `storage.upload_json(f"runs/{run_id}/storyboard.json", data)` then `storage.update_run_log(run_id, "storyboard", "complete")`.
- Railway DEV bucket: `content-factory-dev`. Account ID token type: **Account API Token** (not User API Token).
**Promoted to backlog:** none

---

## [E1-S2] Google Drive integration
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/exceptions.py`: `DriveError` — base exception for all Drive failures. Catch in route handlers; never let it propagate as an untyped 500.
- `src/models.py`: `StepStatus` enum (`pending`/`complete`/`failed`), `StepLog`, `RunLog` (run_log.json schema), `RunCreateRequest` (slug validator), `RunCreateResponse`. `PIPELINE_STEPS` tuple is the canonical step order for all stories that write to run_log.json.
- `src/drive.py`: `DriveClient(service_account_json_b64)` — init from base64 SA JSON string. Key methods: `create_run_folder(slug, root_folder_id) → (run_id, folder_id)` (idempotent, reuses existing folders by name); `upload_json(data, filename, folder_id) → file_id`. Module-level `_build_run_log(run_id)` available for tests.
- `src/routes/runs.py`: `POST /runs` router — validates slug, instantiates `DriveClient`, returns 201 `{run_id, drive_folder_id}` or 500 on `DriveError`. Import pattern for future routes: `from src.routes import runs as runs_router`.
- `src/main.py`: `runs_router` registered. Follow same pattern for all future routers.
- `tests/test_drive.py` (17 tests) + `tests/test_runs.py` (13 tests): Drive API fully mocked via `unittest.mock.patch`. Test fixture pattern: patch `src.drive.service_account.Credentials.from_service_account_info` and `src.drive.build`.
- 43 total tests passing.
**Promoted to backlog:** none

---

## [E1-S1] Railway service skeleton
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/config.py`: `Settings` (pydantic-settings) — validates all 7 required ENV vars at startup. Import with `from src.config import get_settings`. Inject into routes via `Depends(get_settings)`.
- `src/main.py`: FastAPI app entry point. Lifespan hook crashes fast on bad ENV with a clear error log. `GET /health` live. Register all future routers here via `app.include_router()`.
- `tests/test_health.py`: 13 passing tests. Settings injection pattern: `app.dependency_overrides[get_settings] = lambda: settings`. ENV isolation in tests: `monkeypatch.delenv(key, raising=False)`.
- Railway DEV deployed and verified: `https://content-factory-dev-production.up.railway.app/health` → `{"status":"ok","environment":"dev"}`.
- All 8 ENV vars live in Railway Variables tab (including `LOG_LEVEL=INFO`).
- `railway.toml` (DEV) and `railway.prod.toml` (PROD) already correct — no changes needed.
**Promoted to backlog:** none
