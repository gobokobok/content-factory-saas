# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._

Format:
## [E#-S#] Story title
**Completed:** YYYY-MM-DD
**Sprint:** N
**Handover:** [summary of what was built, key decisions, anything the next story needs to know]

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
