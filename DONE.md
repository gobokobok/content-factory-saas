# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._

---

## [P1-S1] cf_platform/ scaffold + router mount
**Completed:** 2026-06-13
**Handover:**
- `cf_platform/interfaces/__init__.py` + `cf_platform/interfaces/api.py` (new): `APIRouter` with `GET /health` returning `{"status": "ok"}`.
- `cf_platform/sources/`, `cf_platform/workers/`, `cf_platform/blocks/`, `cf_platform/adapters/` (new): reserved empty packages, each with a one-line docstring tying it back to plan §2 / D047 / D050 / D056. `cf_platform/core/` already existed from P0-S3.
- `src/main.py`: new `_mount_platform_router(app)` helper — imports `cf_platform.interfaces.api.router` and mounts it at prefix `/platform` inside a `try/except Exception`; on failure logs `logger.exception(...)` and continues (D047 fault isolation). Called once at module load, after all legacy `include_router` calls.
- `tests/cf_platform/test_api.py` (new, 4 tests): `GET /platform/health` → 200; `GET /health` (legacy) still 200 with platform mounted; `_mount_platform_router` registers the route on a fresh `FastAPI()` app in the success path; with `cf_platform.interfaces.api` forced to fail import (via `sys.modules` patched to `None`), `_mount_platform_router` swallows the exception and `/platform/health` is simply absent (404) — legacy app unaffected.
- No new ENV vars, no new dependencies. 860 total passing (was 856).
- **Sprint P1 next story:** P1-S2 (Run Manager) and P1-S3 (Artifact Manager → R2) can proceed in parallel per SPRINT.md execution order; both depend only on P1-S1.
**Smoke test:** PASSED — `python3 -m pytest -q -m "not integration"` → 860 passed, no regressions. Human touchpoint (`POST /platform/echo` → artifact in R2) lands in P1-S6, after P1-S2–S5.
**Promoted to backlog:** none

---

## [P0-S5] Doc hygiene + abstraction-model docs
**Completed:** 2026-06-13
**Handover:**
- `docs/ARCHITECTURE.md` (new): **§0 — LangGraph abstraction model (v2 platform, D056/D057)** section added between "Document status" and "§1 Current state" — covers the Worker=Node / Stage=StateGraph / Platform=Graph-of-graphs hierarchy, the 5 worker invariants (stateless/pure, version-pinned, one-artifact-per-execution written by the observability wrapper, routing-as-graph-edges, IO-adapters-emit-trace-events-not-artifacts), and the state-as-message-bus rules (artifact refs + `ControlSignal` only, no `state_delta`, R2+Postgres as durable truth). Cross-references CONVENTIONS.md and docs/v2_platform_plan.md §3–§5. Top "⚑ v2 Platform direction" banner trimmed to point at §0 instead of duplicating its content. §3 "Orchestration engine" heading retitled to "Orchestration engine (superseded — see §0)" — the existing "Superseded" callout underneath (D052 supersedes Inngest/D042) is retained for history.
- `CONVENTIONS.md`: no change needed — the "Platform v2 — worker/node contract (D056) and state discipline (D057)" section (added in P0-S3, immediately after the D040 "Async function discipline" section) already covers worker=node + state-as-message-bus rules.
- `CLAUDE.md`: "Active story" updated from stale `P0-S3` (done since `d5fe9f4`) to `P0-S5 — Doc hygiene + abstraction-model docs (final story of Sprint P0)`. "Current sprint" line already correctly pointed at the Platform v2 / Sprint P0 track.
- `SPRINT.md`: top banner's stale "Start here: P0-S1" replaced with "P0-S1–S4 done; active story: P0-S5 (final story of Sprint P0)". P0-S5 row in the Sprint P0 stories table updated `planned` → `done`.
- No code changes, no new dependencies, no tests — pure documentation, consistent with P0 "interfaces only" scope (architectural law 7).
- **Sprint P0 complete** (P0-S1–S5, 13/13 pts). Next story: **P1-S1** (cf_platform/ scaffold + router mount), per SPRINT.md execution order P1-S1 → (P1-S2 ∥ P1-S3) → P1-S4 → P1-S5 → P1-S6.
**Smoke test:** N/A — design/doc-only story, no runtime behavior. Operator can review the new §0 in `docs/ARCHITECTURE.md` and the updated CLAUDE.md/SPRINT.md banners directly.
**Promoted to backlog:** none

---

## [P0-S4] Postgres data model + analytics-join design
**Completed:** 2026-06-12
**Handover:**
- `cf_platform/db/schema.sql` (new) — full DDL draft for all 6 tables (`runs`, `artifacts`, `worker_executions`, `trace_events`, reserved `published_videos`/`video_metrics`). Lineage (`worker`, `worker_version`, `prompt_version`, `model`) is plain TEXT columns on `artifacts`/`worker_executions` per D048 — only `sampling_params`/`inputs`/`meta` are JSONB. `artifacts` has `UNIQUE (run_id, stage, name, version)` to enforce immutability (new write = new row, version+1). Analytics indexes per plan §6 (`prompt_version`, `worker_version`, `run_id`, `source`, `external_id`). FKs from `artifacts`/`worker_executions`/`trace_events`/`published_videos` → `runs.run_id`. Design only — not applied by any code path (P0 architectural law 7); P2-S2 turns this into `cf_platform/db/migrations/0001_init.sql`.
- `cf_platform/db/queries.sql` (new) — the P7-S3 attribution query (parametrized on `worker` rather than hardcoded `'storyboard'`, since the platform's content-generation worker name differs from the legacy pipeline), plus 3 supporting queries used by later sprints' human touchpoints: per-run worker cost/latency/version (P2), run-level cost rollup, and artifact lineage listing (Epic 34 replay). All join keys are plain TEXT columns — joins resolve conceptually without JSON unpacking.
- `DECISIONS.md` D048 updated: migration tooling finalized as **raw SQL** (not Alembic) — ~6-table analytics-shaped schema with no app-side ORM models; hand-written numbered SQL files (`cf_platform/db/migrations/NNNN_*.sql` + `schema_migrations` tracking table, applied via `psycopg` at startup) are simpler to audit than Alembic's autogenerate machinery. Implementation deferred to P2-S2.
- `docs/v2_platform_plan.md` §6 — added pointer to the new `cf_platform/db/schema.sql` / `queries.sql` design files.
- No code changes, no new dependencies, no tests — pure SQL/docs design artifact, consistent with P0 "interfaces only" scope.
**Smoke test:** N/A — design-only story, no runtime behavior (P0 architectural law 7). Operator can review `cf_platform/db/schema.sql` and `cf_platform/db/queries.sql` directly.
**Promoted to backlog:** none

---

## [P0-S3] Core contracts (Pydantic) — interfaces only
**Completed:** 2026-06-12
**Handover:**
- `cf_platform/core/schemas.py` (new): all P0-S3 universal contracts per plan §4 — `LineageEnvelope` (run/worker/prompt/model + `sampling_params: dict[str, Any] = {}`, D055), `Artifact` (immutable, versioned, nests `LineageEnvelope`), `RunRecord` (lifecycle `created|running|complete|failed`), `WorkerExecution` (cost/latency/token counters default to 0, `sampling_params` default `{}`, status `ok|error`), `ControlSignal = Literal["continue","retry","branch"]`, `WorkerOutput` (`artifact: BaseModel`, `control: ControlSignal = "continue"`, deliberately **no** `state_delta` per D057), `WorkerNode` type alias, `merge_refs` additive-reducer function, `StageState` (base graph state — `run_id`/`user_id`/`inputs`/`artifacts: Annotated[dict[str,str], merge_refs]`), `TraceEvent` (IO-adapter observability record, D050), `Signal` (minimal placeholder payload for discovery signals — full shape deferred to P3-S2), `SourceAdapter` Protocol (`async fetch(niche, params) -> list[Signal]`).
- `cf_platform/__init__.py`, `cf_platform/core/__init__.py` (new) — package scaffolding; reserved for `run_manager.py`, `artifact_manager.py`, `worker_registry.py`, `db.py` in P1.
- `tests/cf_platform/test_schemas.py` (new, 28 tests): defaults (`sampling_params={}`, token/cost/latency=0, `artifacts={}`), closed Literal-set validation for `RunRecord.status`, `WorkerExecution.status`, `WorkerOutput.control`, `TraceEvent.status` (valid + invalid-rejected cases), `merge_refs` additive-merge and override behavior, `StageState.artifacts` field carries `merge_refs` in its `Annotated` metadata, `WorkerOutput.model_fields` confirmed to exclude `state_delta`, `SourceAdapter` confirmed as a `Protocol` declaring `fetch`. 856 total passing (was 828).
- No new ENV vars. No new dependencies — pydantic 2.13 already in `requirements.txt`. Zero runtime behavior (no R2/DB/LangGraph imports), per P0 architectural law 7.
- **Naming fix — affects all future P1+ stories:** the plan's `platform/` package name collides with Python's stdlib `platform` module. With the repo root on `sys.path` (true for both `python -m pytest` locally and Railway's `uvicorn` invocation in production), `import platform` resolved to this new package instead of the stdlib module — broke pytest outright (`AttributeError: module 'platform' has no attribute 'python_version'`) and would have broken any dependency doing `import platform` at runtime (`requests`, `multiprocessing`, etc.). Operator selected **`cf_platform`** as the replacement name. Renamed package directory + every path reference (not HTTP routes) across `docs/v2_platform_plan.md`, SPRINT.md, BACKLOG.md, CONVENTIONS.md, DECISIONS.md (D047), CLAUDE.md. HTTP route prefixes (`/platform/echo`, `/platform/health`, `/platform/runs`, `/platform/analytics/attribution`) were left unchanged — pure URL strings, no import collision. **All P1+ work must use `cf_platform/...` for package paths.**
**Smoke test:** PASSED — `python3 -m pytest -q -m "not integration"` → 856 passed, no regressions. P0 is interfaces-only (architectural law 7); no operator-facing artifact to review beyond the schema module + tests, which the operator can inspect directly in `cf_platform/core/schemas.py`.
**Promoted to backlog:** none

---

## [P0-S2] Ratify decisions D047–D057
**Completed:** 2026-06-12
**Handover:**
- Both ACs were already satisfied by commit `642af5b` (the planning commit that also produced `docs/v2_platform_plan.md`): DECISIONS.md already carries full D047–D057 entries (Date, Decision, Rationale, Dependencies/See pointers), and D042 already carries `**Status:** SUPERSEDED by D052 (2026-06-12)`.
- This story formally ratifies that content as the P0-S2 deliverable — no further edits to DECISIONS.md were needed.
- Decisions ratified: D047 (legacy isolation via adapter wrap), D048 (Postgres metadata index), D049 (Telegram thin trigger + formatter rule), D050 (SourceAdapter protocol, adapters emit trace events), D051 (worker/lineage envelope), D052 (LangGraph supersedes D042/Inngest), D053 (web-search tool for fact-check), D054 (YouTube Analytics OAuth + scheduler), D055 (replay-ready constraints), D056 (Worker = Node abstraction model), D057 (artifacts are truth; state is a message bus).
- No code, ENV vars, or dependencies introduced — interfaces/design only, per architectural law 7.
**Smoke test:** N/A — documentation/decision-log ratification only, no runtime behavior.
**Promoted to backlog:** none

---

## [P0-S1] North-star spec — docs/v2_platform_plan.md
**Completed:** 2026-06-12
**Handover:**
- `docs/v2_platform_plan.md` (committed in `642af5b`) is the canonical north-star spec for the Content Factory v2 Platform Track (Sprints P0–P7). All P0–P7 stories reference it for contracts, schemas, and decisions.
- Covers: vision & key insight (§1), macro architecture (§2), the 7 architectural laws incl. the one-way `platform/ → adapter → src/` boundary (§3), core contracts (§4), per-stage StageState contracts (§5), R2/Postgres data model + attribution query (§6), D047–D057 decision table (§7), sprint roadmap P0–P7 + post-MVP epics (§8), migration arc (§9), new dependencies table (§10), Platform MVP DoD (§11), working agreement (§12).
- Legacy Script→Video pipeline (`src/`) stays untouched and operable (D047) — platform is additive.
- D047–D057 are recorded in the plan doc but not yet in DECISIONS.md — that's **P0-S2**'s scope (includes marking D042 superseded by D052).
- No code, ENV vars, or dependencies introduced — interfaces/design only, per architectural law 7 (P0 produces interfaces only).
**Smoke test:** PASSED — operator reviewed `docs/v2_platform_plan.md` and approved the platform/legacy boundary and P0–P7 sequencing on 2026-06-12.
**Promoted to backlog:** none

---

## [S14-S3] Asset Mode column in storyboard table
**Completed:** 2026-06-05
**Handover:**
- `src/models.py`: `ManifestEntry` gains `asset_mode: Optional[Literal["stock", "ai_generated"]] = None`. `ManifestPatchRequest(scene_id, field, value)` and `ManifestPatchResponse(status, scene_id, field)` added.
- `src/manifest.py`: `_PATCHABLE_MANIFEST_FIELDS = {"asset_mode"}` and `_STOCK_CLIP_TYPES = {"hard_cut"}` module-level constants. `_default_asset_mode(clip_type) → str` helper. `build_manifest` sets `asset_mode` per entry from `_default_asset_mode`. `patch_manifest_entry(run_id, scene_id, field, value, storage) → AssetManifest` — reads manifest from R2, validates field + value, mutates entry, writes back.
- `src/routes/manifest.py`: `PATCH /runs/{run_id}/manifest` — calls `patch_manifest_entry`; `ValueError` → 422; `ManifestError` → 422; `StorageError` → 404.
- `src/acquisition.py`: `acquire_scene` branches on `entry.asset_mode`: `"ai_generated"` → Replicate only; `"stock"` → Pexels only (miss marks entry failed, no Replicate fallback); `None` → legacy Pexels → Replicate chain.
- `src/static/pipeline.html`: `renderStoryboardHtml` gains `assetModeMap` param. Source column (last) added to storyboard table with `<select class="sb-source-select">` per row. `source-primary` / `source-ai` classes on the relevant cells; `highlight-active` (yellow `#FFF8C5`) applied to the active cell. `sbAssetModeChange(select)` updates highlights and fires `PATCH /runs/{run_id}/manifest`. `populateStoryboard` fetches manifest in parallel (when complete) to restore stored `asset_mode` values on reload.
- `tests/test_manifest.py`: `TestBuildManifestAssetModeDefault` (3+2), `TestPatchManifestEntry` (5 unit), `TestPatchManifestRoute` (5 route). 809 total passing.
- `tests/test_acquisition.py`: `TestAcquireSceneAssetMode` (6 tests — ai_generated-only, stock-only, None fallback).
- `tests/test_storyboard.py`: `TestPatchSceneField` extended with 4 asset_mode tests.
- Post-ship fixes (2026-06-05): (1) `sectionLocked.storyboard` was set true on storyboard completion instead of acquisition completion — fixed in `openRun`, `runCreateStoryboard`, `runAssetAcquisition` (commit `cd3788d`). (2) `asset_mode` moved from `ManifestEntry` to `StoryboardScene` so selections persist before the manifest exists; `sbAssetModeChange` now PATCHes `/storyboard`; `populateStoryboard` builds `assetModeMap` from storyboard scenes directly (commit `7adabf6`).
**Smoke test:** PASSED — 2026-06-05. Source dropdown changes persist after reload. Yellow highlight tracks the active source correctly. Storyboard section stays editable until acquisition completes.
**Promoted to backlog:** BUG-003 (storyboard generation cancels on run navigation — background task needed)

---

## [S14-S2] Editable AI Prompt in storyboard table
**Completed:** 2026-06-05
**Handover:**
- `src/models.py`: `StoryboardPatchRequest(scene_id, field, value)` and `StoryboardPatchResponse(status, scene_id, field)` added.
- `src/storyboard.py`: `_PATCHABLE_FIELDS = {"ai_generate_prompt"}` module-level constant. `patch_scene_field(run_id, scene_id, field, value, storage) → Storyboard` — reads `storyboard.json`, validates field against `_PATCHABLE_FIELDS` (ValueError on mismatch), finds scene by `scene.scene == scene_id` (StoryboardParseError if missing), mutates `visual_prompts.ai_generate`, writes back via `storage.upload_json`. Returns updated `Storyboard`.
- `src/routes/storyboard.py`: `PATCH /runs/{run_id}/storyboard` — calls `patch_scene_field`; ValueError → 422; StoryboardParseError → 422; StorageError → 404. Returns `StoryboardPatchResponse`.
- `src/static/pipeline.html`: AI Prompt column cell rendered with `class="text-lg ai-editable"` and `data-scene-id`. `sbAiPromptEdit(td)` converts cell to `<textarea>` on click (no-op when storyboard section is locked). `sbAiPromptSave(td, ta)` fires PATCH on blur/Enter, restores static text on success, shows 3s error indicator on failure. `sbAiPromptCancel(td, original)` handles Escape. CSS: `.ai-editable` (pointer cursor, hover bg), `.editing` (amber outline), `.saving` (reduced opacity), `.sb-ai-textarea`.
- `tests/test_storyboard.py`: `TestPatchSceneField` (5 unit tests), `TestPatchStoryboardRoute` (4 route tests). 784 total passing.
**Smoke test:** PASSED — 2026-06-05. Clicked an AI Prompt cell, edited the value, pressed Enter, reloaded the page — updated value persisted in the storyboard table. Confirmed edit is blocked after acquisition completes.
**Promoted to backlog:** none

---

## [S13-S3] Background render task + polling
**Completed:** 2026-06-05
**Handover:**
- `src/renderer.py`: `_RENDER_STATE: dict[str, dict]` module-level dict keyed by run_id. `parse_ffmpeg_progress(stderr_text, total_frames) → int` — finds last `frame=N` in accumulated ffmpeg stderr; returns 0–99 (capped; never 100 — completion signalled by `status="complete"`); falls back to 0 when `total_frames <= 0` or no match. `render_run` gains `total_frames: int = 0` param; initialises and finalises `_RENDER_STATE[run_id]`.
- `src/routes/render.py`: fully rewritten. `POST /runs/{run_id}/render` async, returns HTTP 202 `{status: "running", poll_url}` immediately. Route reads storyboard for `total_frames` (fallback 0), initialises state, registers `_background_render` via `BackgroundTasks`. `_background_render` is async, calls `await asyncio.to_thread(render_run, ...)`, then writes final `_RENDER_STATE`, updates `run_log.json`, and calls `pipeline.summarize_step`. `GET /runs/{run_id}/render/status` reads `_RENDER_STATE`; 404 if not started.
- `src/models.py`: `RenderAcceptedResponse(status, poll_url)` and `RenderStatusResponse(status, progress_pct, output_key?, error?)` added.
- `DECISIONS.md`: D044 added (BackgroundTasks rationale vs job queue).
- `tests/test_renderer.py`: route tests updated for 202; `TestRenderStatusRoute` (5 tests), `TestParseFfmpegProgress` (7 tests) added. 775 total passing.
**Smoke test:** DEFERRED — POST to `/runs/{run_id}/render` on Railway DEV; confirm immediate 202; poll `GET /runs/{run_id}/render/status` until `status=complete`; download video.
**Promoted to backlog:** none

---

## [S13-S2] Parallel asset acquisition
**Completed:** 2026-06-05
**Handover:**
- `src/acquisition.py`: `run_acquisition` is now `async`. Pending entries filtered up front, then processed in batches of `batch_size` (default 20) via `asyncio.gather(*[asyncio.to_thread(acquire_scene, ...) for entry in batch], return_exceptions=True)`. Per-scene exceptions caught inside the gather result loop — entry marked `failed`, batch continues uninterrupted. `acquire_scene` remains synchronous (sync core, easy to unit-test).
- `src/routes/assets.py`: route is now `async def acquire_assets`; calls `await run_acquisition(..., batch_size=settings.ACQUISITION_BATCH_SIZE)`.
- `src/config.py`: `ACQUISITION_BATCH_SIZE: int = 20` added.
- `ENV.md`: `ACQUISITION_BATCH_SIZE` documented in Pipeline config table.
- `tests/test_acquisition.py`: all `TestRunAcquisition` unit tests upgraded to `@pytest.mark.asyncio`; route tests use `new_callable=AsyncMock`; `TestRunAcquisitionBatching` class (4 tests: batch grouping, partial failure isolation, batch-size-1 sequential fallback, idempotent mixed-state). 762 total passing.
- No new pip dependencies.
**Smoke test:** DEFERRED — requires POST /runs/{run_id}/assets on Railway DEV with a 50+ scene manifest. Confirm acquisition completes in under 60 s and all scenes are acquired or explicitly failed with no partial hangs.
**Promoted to backlog:** none

---

## [S13-S1] Chunked storyboard generation
**Completed:** 2026-06-04
**Handover:**
- `src/storyboard.py`: `_split_script_into_chunks(script, max_paragraphs) → list[str]` — splits on blank-line paragraph boundaries; returns `[script]` when within limit; last chunk absorbs remainder.
- `src/storyboard.py`: `_slice_alignment_for_chunk(words, chunk_idx, chunks) → list[WordTimestamp]` — proportional character-count slicing; last chunk always gets remaining words.
- `src/storyboard.py`: `_merge_storyboard_chunks(storyboards) → Storyboard` — extends all scene lists, reassigns scene IDs as contiguous integers 1…N, recomputes summary (total_scenes, total_duration_s, rhythm joined with " / "), preserves GLOBAL from first storyboard. Raises `StoryboardParseError` on empty input; returns unchanged when called with one storyboard.
- `src/storyboard.py`: `generate_storyboard` refactored — calls `_split_script_into_chunks` first. Single-chunk path identical to previous behavior. Chunked path: `asyncio.gather(*api_calls)` fires one `_call_claude_api` per chunk in parallel; results parsed and merged before Haiku validation. No behavioral change for scripts ≤ `STORYBOARD_CHUNK_SIZE` paragraphs.
- `src/config.py`: `STORYBOARD_CHUNK_SIZE: int = 10` added.
- `ENV.md`: `STORYBOARD_CHUNK_SIZE` documented.
- `DECISIONS.md`: D043 added (rationale, no new deps).
- `tests/test_storyboard.py`: 24 new tests — `TestSplitScriptIntoChunks` (7), `TestSliceAlignmentForChunk` (6), `TestMergeStoryboardChunks` (7), `TestGenerateStoryboardChunked` (4 async via `@pytest.mark.asyncio`). 758 total passing.
**Smoke test:** DEFERRED — requires a 30+ paragraph script submitted on Railway DEV. Verify `storyboard.json` scene count > 50 and scene IDs are contiguous in the downloaded artifact.
**Promoted to backlog:** none

---

## [S12-S3] Publishing metadata UI
**Completed:** 2026-06-01
**Handover:**
- `src/routes/runs.py`: added `"metadata": ("runs/{run_id}/metadata.json", "application/json")` to `_STEP_ARTIFACT_KEYS` — enables `GET /runs/{run_id}/artifact/metadata` to return the stored metadata JSON content. No new route or model required.
- `src/static/pipeline.html`: `<div id="render-metadata" style="display:none;">` added below `#render-content` in `#section-render`.
- `populateMetadata()`: called from `populateRender()`. Hides section when render is not done. Shows "Generate Metadata" button when `stepSt('metadata') !== 'complete'`. When complete: fetches artifact, renders 7 labelled fields (Primary Title, Alt Title 1, Alt Title 2, YouTube Description, Instagram Description, Hashtags, SEO Tags) each with a Copy button.
- `generateMetadata()`: POSTs to `POST /runs/{run_id}/metadata`, updates `currentSteps['metadata'] = 'complete'`, calls `renderNavItems()`, then re-runs `populateMetadata()`. Handles error + retry.
- `copyField(btn, text)`: writes to clipboard, sets button text to "Copied ✓" + `.copied` CSS class (green) for 2s, falls back to "Failed" on rejection.
- No new ENV vars. 734 tests passing — no regressions.
**Smoke test:** PASSED — 2026-06-05. Clicked "Generate Metadata" on a completed render run; Haiku returned all 7 fields (Primary Title, Alt Title 1, Alt Title 2, YouTube Description, Instagram Description, Hashtags, SEO Tags). Clicked "Copy" on YouTube Description; content pasted correctly.
**Promoted to backlog:** none

---

## [S12-S2] Publishing metadata generator
**Completed:** 2026-06-01
**Handover:**
- `src/metadata_generator.py` (new): `generate_metadata(project_name, storyboard, api_key, router) → tuple[PublishingMetadata, int, int, float]`. Calls Claude Haiku via `TRANSFORM` task type. Strips markdown fences before JSON parse. Raises `MetadataError` on API failure or schema mismatch.
- `src/routes/metadata.py` (new): `POST /runs/{run_id}/metadata`. Reads `run_log.json` for `project_name` (falls back to `run_id`), reads `storyboard.json`, calls `generate_metadata`, stores `runs/{run_id}/metadata.json`, marks `run_log.json` step `metadata → complete`. On failure: marks step `failed`, operator can retry via re-POST.
- `src/models.py`: `PublishingMetadata` schema (`title`, `alt_titles: list[str]`, `youtube_description`, `instagram_description`, `hashtags: list[str]`, `seo_tags: list[str]`). `MetadataResponse` (`status`, `metadata_key`). `PIPELINE_STEPS` now includes `"metadata"` after `"render"`.
- `src/exceptions.py`: `MetadataError` added.
- `src/main.py`: `metadata_router` registered.
- `tests/test_metadata_generator.py` (new): 20 tests — `_extract_json` parser, `_build_user_message`, `generate_metadata` happy/API error/bad JSON/schema mismatch, route success/404/500/failure-marks-run-log/project-name-fallback.
- No new ENV vars. 734 tests passing.
**Smoke test:** PASSED — 2026-06-05. Batched with S12-S3 UI smoke test; metadata generated and displayed correctly end-to-end.
**Promoted to backlog:** none

---

## [BUG-002] Error message from Save Draft persists alongside "✓ Committed" status
**Completed:** 2026-06-01
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- `runCommit()` now clears `#save-draft-status` text at the top of the function (alongside hiding `#input-error`), so any stale error from a prior failed `saveDraft()` call is wiped before the commit sequence runs.
- `saveDraft()` success path already cleared `statusEl.textContent = ''` — no change needed there.
**Smoke test:** DEFERRED — requires the BUG-001 scenario reproduced on Railway DEV (network error mid-commit → Save Draft attempted and fails with "storyboard already complete" → Commit retried successfully). Confirm "✓ Committed" appears with no error text beside it.
**Promoted to backlog:** none

---

## [BUG-001] Storyboard Commit: re-poll run log on fetch failure
**Completed:** 2026-06-01
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars, no new dependencies.
- `runSequence` `catch` block extended: on any fetch-level network error, immediately re-polls `GET /runs` to read the actual backend step status before rendering a failure state.
- If re-poll shows step is `complete` → green dot, sequence continues to the next step (user sees "✓ Committed" with no error).
- If re-poll shows step is `failed` → red dot + "X failed — see run log for details".
- If re-poll itself fails (secondary network outage) → falls back to original "network error: …" message.
- Fix applies to all steps run through `runSequence` (alignment, storyboard, manifest, asset acquisition, ffmpeg-script, render).
- 714 tests passing — no regressions.
**Smoke test:** DEFERRED — requires Railway DEV under load or simulated connection drop during Commit. Trigger Commit, intercept the storyboard response at the network layer; confirm UI shows green "✓ Committed" rather than red error when backend log shows `storyboard: complete`.
**Promoted to backlog:** none

---

## [S12-S1] Video settings → pipeline wiring
**Completed:** 2026-06-01
**Handover:**
- `src/ffmpeg_builder.py`: `_ASPECT_DIMENSIONS` dict + `_dimensions_for_aspect_ratio(aspect_ratio) → (w, h)` added. `build_ffmpeg_script` gains `video_settings: Optional[VideoSettings] = None`; `audio` kwarg retained for backwards compat but `video_settings.audio` wins when provided. `_scene_section`, `_render_scene`, `_render_video_scene`, `_render_image_scene`, and `_zoompan_filter` all accept `out_w`/`out_h` params (default 1080×1920). When `subtitles == "none"`, caption heredoc + burn step are skipped; `_audio_section` receives `video_source="$WORK/video_only.mp4"` instead of `"$WORK/video_captioned.mp4"`.
- `src/captions.py`: `_CAPTIONS_ASS_HEADER_CLASSIC` added (Poppins, 64pt, Bold=0, Outline=3, MarginV=180). `_captions_header(subtitle_style) → str` selects header. `build_word_synced_captions_ass` and `build_captions_ass` gain `subtitle_style: str = "TikTok"` param.
- `src/replicate_client.py`: `_STYLE_MODIFIERS` maps Cinematic/Cartoonish/Documentary/Minimalist to prompt modifier strings. `acquire_for_entry` gains `visual_style: str = "Realistic"`; appends modifier when non-empty.
- `src/acquisition.py`: `acquire_scene` and `run_acquisition` gain `visual_style: str = "Realistic"` and pass it to `replicate.acquire_for_entry`.
- `src/routes/assets.py`: loads `settings.json` → `VideoSettings`; passes `visual_style` to `run_acquisition`; falls back to defaults on `StorageError`.
- `src/routes/ffmpeg_script.py`: passes `video_settings=video_settings` to `build_ffmpeg_script`.
- 714 total tests passing (28 new: `TestAspectRatioDimensions` ×5, `TestSubtitlesSetting` ×4, `TestSubtitleStyleVariants` ×9, `TestVisualStyleModifier` ×8). No new ENV vars. No new dependencies.
**Smoke test:** DEFERRED — requires Railway DEV deploy. Set aspect_ratio=16:9, render a video, confirm 1920×1080 output. Set subtitles=none, confirm no captions. Set visual_style=Cinematic, confirm Replicate prompt ends with "cinematic, shallow depth of field, golden hour lighting".
**Promoted to backlog:** none

---

## [S11-S3] Audio → ffmpeg integration
**Completed:** 2026-05-31
**Handover:**
- `src/ffmpeg_builder.py`: `_MUSIC_VOL = 0.15` removed; `_DUCKING_FACTOR = 0.4` added as module constant. `build_ffmpeg_script` gains `audio: Optional[AudioSettings] = None` — defaults to `AudioSettings()` when omitted. `_music_check(audio)` generates `-stream_loop -1` in `MUSIC_ARGS` for loop mode; fit mode unchanged. `_audio_section(storyboard, audio)` computes `effective_vol = music_volume/100.0 * _DUCKING_FACTOR` (ducking ON) or `music_volume/100.0` (ducking OFF); bakes value into `volume={effective_vol:.3f}[music]` at generation time — no bash arithmetic needed at render.
- `src/routes/ffmpeg_script.py`: loads `runs/{run_id}/settings.json` from R2 after alignment section; falls back to `VideoSettings()` on `StorageError`; passes `audio=video_settings.audio` to `build_ffmpeg_script`. Imports `VideoSettings`.
- `tests/test_ffmpeg_builder.py`: 9 existing route tests updated (added `StorageError("no settings")` as 4th `get_json.side_effect` entry). Default volume assertion updated (0.15 → 0.060). 11 new tests in `TestAudioSettings` (unit) and `TestFfmpegScriptRouteAudioSettings` (route). 686 total passing.
- No new ENV vars. No new dependencies.
- S12-S1 (video settings pipeline wiring) is now unblocked — it depends on both S9-S3 and S11-S3.
**Smoke test:** PASSED (engineering) — 2026-05-31 on Railway DEV (commit `71d8e3c`). Settings updated via API to `music_volume=40, ducking_enabled=true`; ffmpeg_script.sh regenerated and verified `volume=0.160` (40% × 0.4 ducking factor) and `volume=1.0` for VO. Render completed successfully (exit code 0, 61.5s) using run `2026-05-27_smoketest-pipelinereorder` (Elysian Fields mp3 + SmokeTest_PipelineReorder.wav). Audible listening check: download `final.mp4` from the Rendered Video page and confirm music ducks under the voiceover — **pending operator listen**.
**Promoted to backlog:** none

---

## [S11-S2] Audio controls UI
**Completed:** 2026-05-31
**Handover:**
- `src/models.py`: `AudioSettings(music_volume: int = 15, ducking_enabled: bool = True, playback_mode: Literal["loop","fit"] = "fit")` added as a new model. `VideoSettings` gains `audio: AudioSettings = Field(default_factory=AudioSettings)`. Backward-compatible — existing `settings.json` without the `audio` key deserialises cleanly using defaults.
- `src/static/pipeline.html`: Three controls added to the existing Settings `field-card--tight-v` below the Subtitles row: `#setting-music-volume` (range 0–100), `#setting-ducking` (checkbox in a `.toggle-switch` component), `#setting-playback-mode` (select: fit/loop). Separated from video settings by a `.settings-row--section-label` "AUDIO" divider. CSS added for toggle switch, section label, and disabled states.
- `loadVideoSettings()` extended to restore all three audio controls from `s.audio`; all audio controls disabled when `sectionLocked.input` is true.
- `saveVideoSettings()` extended to include `audio: {music_volume, ducking_enabled, playback_mode}` in the POST body. Single call — no new endpoint.
- `renderStoryboardHtml(content, audioSettings)` gains optional second param. `populateStoryboard()` now fetches `GET /runs/{run_id}/settings` in parallel with the storyboard artifact and passes `settings.audio` to the renderer. Storyboard settings panel Audio section shows real Volume, VO Ducking, and Playback values instead of storyboard-global placeholders.
- `tests/test_runs.py`: 7 new tests in `TestVideoSettings` — audio POST round-trip, R2 storage, GET returns stored audio, GET returns defaults on absent file, invalid playback_mode → 422, music_volume > 100 → 422, POST without audio block → defaults. 675 total passing.
**Smoke test:** PASSED — 2026-06-05. Volume slider set to 40%, ducking disabled, Loop full track selected; values persisted after reload. Commit locked all audio controls read-only.
**Promoted to backlog:** none

---

## [S11-S1] Background music upload
**Completed:** 2026-05-31
**Handover:**
- `src/models.py`: `MusicUploadUrlRequest(filename)` + `MusicUploadUrlResponse(upload_url, key)` added. `DraftResponse` gains `music_filename: Optional[str] = None`.
- `src/routes/runs.py`: `POST /runs/{run_id}/music-upload-url` — generates presigned R2 PUT URL; stores at `runs/{run_id}/music/{filename}`. Mirrors voiceover-upload-url pattern exactly. `DELETE /runs/{run_id}/music` — lists and deletes all keys under `runs/{run_id}/music/` prefix; no-op (204) if none exist. `GET /runs/{run_id}/draft` extended: detects first `.mp3/.wav/.m4a` in music prefix, returns as `music_filename`.
- `src/static/pipeline.html`: Background Music field-card moved to Content subsection (after Voiceover). Both audio cards redesigned to match identical `vo-widget` pattern: "Choose a file" (underlined link), filename span, Upload button (appears on file select), Delete button (appears after upload), status span. `DELETE /runs/{run_id}/voiceover` added to backend (mirrors music delete). JS: `deleteVoiceover()`, `deleteMusic()`, `_resetMusicWidget()`, `_setMusicLocked()`, `onMusicFileSelected()`, `uploadMusic()`. `populateInput()` restores both tracks from draft (filename + delete button shown). Settings card: "Voiceover Script" label rename, `field-card--tight-v` padding 0 top/bottom, `.vo-widget` uses `column-gap: 10px; row-gap: 0` to prevent empty flex-line inflation. All card spacing calibrated to 10px between content and borders/dividers. `settings-row` uses `align-items: center; padding: 9px 0`.
- No new ENV vars. No new dependencies.
- 12 new tests in `tests/test_runs.py` (`TestDeleteVoiceover` × 3, `TestMusicUploadUrl` × 4, `TestDeleteMusic` × 3, `TestGetDraftMusicFilename` × 2). 668 total passing.
**Smoke test:** PASSED — 2026-06-05. Uploaded .mp3 track, audio preview played, Remove cleared the track, re-upload succeeded, Commit locked all music controls read-only.
**Post-close fix (2026-05-31, commit `a680b00`):** `uploadMusic()` and `uploadVoiceover()` now issue a best-effort `DELETE` on the existing file before fetching a presigned URL for the new upload. Previously, uploading a replacement track with a different filename left both files in R2; the ffmpeg script picked up the old track. Fix applied in the same `pipeline.html`.
**Promoted to backlog:** none

---

## [S10-S1] TTS VO generation via ElevenLabs
**Completed:** 2026-05-31
**Handover:**
- `src/tts.py`: `split_into_chunks(script, target_chars=1000) → list[str]` — splits at `.`, `!`, `?` boundaries, merges short sentences until target reached. `generate_tts(script, api_key, voice_id) → (mp3_bytes, chunk_count)` — async; builds `_call_elevenlabs` coroutines with `previous_text`/`next_text` context, gathers all in parallel, concatenates PCM in order, calls `_encode_pcm_to_mp3` (ffmpeg subprocess: `-f s16le -ar 44100 -ac 1`). Raises `TTSError` on any failure.
- `src/routes/tts.py`: `POST /runs/{run_id}/tts` — reads `script.txt` from R2 (404 if missing); returns 503 if `ELEVENLABS_API_KEY`/`ELEVENLABS_VOICE_ID` unset; calls `generate_tts`; on success purges all `runs/{run_id}/voiceover/` keys then uploads `generated.mp3`; on failure leaves existing upload untouched (delete-on-success only). Returns `TTSResponse`.
- `src/exceptions.py`: `TTSError` added.
- `src/models.py`: `TTSResponse(status, key, chunk_count, duration_s)` added.
- `src/config.py`: `ELEVENLABS_API_KEY: str = ""`, `ELEVENLABS_VOICE_ID: str = ""` added (optional; 503 returned if unset when route is called).
- `src/main.py`: `tts_router` registered.
- `ENV.md`: `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` documented.
- `src/static/pipeline.html`: Voiceover field-card replaced with two-mode widget. "Upload File" / "Generate with ElevenLabs" tab toggle. Switching to Generate when a VO is uploaded shows `#tts-warn-modal` ("If generation succeeds, it will be permanently deleted. Continue?") — Cancel reverts; Confirm arms generate mode. `voMode` state var ('upload'|'generate'). `updateCommitBtn` allows Commit when `voMode==='generate'` and script is non-empty. `runCommit` prepends `POST /tts` step in generate sequence. `populateInput` restores generate mode when `vo_filename === 'generated.mp3'` and shows "✓ generated.mp3" status. Mode tabs disabled when section locked.
- `tests/test_tts.py`: 25 new tests — `split_into_chunks` (8), `_encode_pcm_to_mp3` (4), `generate_tts` (5), route integration (8). 656 total passing.
**Smoke test:** DEFERRED — requires `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` on Railway DEV. Operator switches to "Generate with ElevenLabs", pastes script, clicks Commit, observes "Generating VO…" progress, then pipeline advances through alignment → storyboard automatically.
**Promoted to backlog:** none

---

## [S9-S3] Video settings UI
**Completed:** 2026-05-31
**Handover:**
- `src/models.py`: `VideoSettings` (Literal-validated: `aspect_ratio`, `visual_style`, `subtitles_enabled`, `subtitle_style`) + `VideoSettingsResponse` added. Defaults: 9:16 / Realistic / true / TikTok.
- `src/routes/runs.py`: `POST /runs/{run_id}/settings` stores `settings.json` in R2. `GET /runs/{run_id}/settings` returns stored values or defaults — never 404.
- `src/static/pipeline.html`: Settings section replaced with three field-cards (Aspect Ratio, Visual Style, Subtitles). Auto-saves on change; loads on run open; all controls disabled when `sectionLocked.input` is true. Subtitle style selector conditionally shown.
- No new ENV vars. No new dependencies. 630 tests passing (+11).
**Smoke test:** PASSED — 2026-06-05. Aspect Ratio and Visual Style changes persisted after reload. Disabling the Subtitles toggle correctly hid the Caption Style selector.
**Promoted to backlog:** none

---

## [S9-S2] Commit system
**Completed:** 2026-05-31
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- `#commit-btn` replaces `#create-storyboard-btn`; onclick → `openCommitModal()`.
- `openCommitModal()` validates script present then shows `#commit-modal` with exact AC warning text.
- `closeCommitModal()` hides modal (Cancel path — no pipeline trigger).
- `confirmCommit()` closes modal and calls `runCommit()` (the renamed `runCreateStoryboard` — unchanged pipeline logic: alignment → storyboard).
- `updateCommitBtn()` replaces `updateCreateStoryboardBtn()` — when `sectionLocked.input` is true: hides button, makes `#committed-indicator` (✓ Committed, green) visible; when unlocked: standard enable/disable.
- `.commit-modal-*` CSS and `.committed-indicator` CSS added (same pattern as delete modal).
- 619 tests passing.
**Smoke test:** PASSED — operator confirmed Commit modal, ✓ Committed indicator, and read-only locked state on Railway DEV.
**Promoted to backlog:** none

---

## [S9-S1] Project Details tab restructure
**Completed:** 2026-05-31
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- All user-visible "Input" labels replaced with "Project Details": `SECTION_LABELS.input`, `renderNavItems` label, `section-title` hidden div, and two empty-state messages.
- Content section wraps Project Name, Voiceover, and VO Script fields under a `CONTENT` subsection heading.
- Settings section placeholder added below (`SETTINGS` heading + "Video settings coming soon.") — ready for S9-S3 controls with no further HTML restructuring needed.
- New CSS: `.subsection`, `.subsection-title` (11px uppercase muted), `.subsection-placeholder`.
- Internal JS IDs and function names (`section-input`, `sectionLocked.input`, `populateInput`) unchanged.
- 619 tests passing.
**Smoke test:** PASSED — accessibility tree confirmed nav label "Project Details", "CONTENT" heading with all 3 fields, "SETTINGS" heading with placeholder text, and both CTAs present.
**Promoted to backlog:** none

---

## [S8-S5] Project deletion flow
**Completed:** 2026-05-30
**Handover:**
- `src/storage.py`: `R2Client.delete_run(run_id) → int` — lists all keys under `runs/{run_id}/`, batch-deletes via `delete_objects` (up to 1000 keys/request), raises `StorageError("Run not found: {run_id}")` if prefix empty, returns key count.
- `src/routes/runs.py`: `DELETE /runs/{run_id}` — 204 on success, 404 on missing run, 500 on R2 error. Auth covered by existing middleware.
- `src/static/pipeline.html`: "Delete Project" button in breadcrumb bar (right-aligned via `.bc-spacer` flex push). Confirmation modal `#delete-modal` with exact AC text. `confirmDeleteRun()` resets all state, calls `renderRunList()`, and navigates back to root path.
- 619 tests passing. No new ENV vars. No new dependencies.
**Smoke test:** PASSED — confirmed delete modal, run removed from left panel, R2 prefix purged on Railway DEV.
**Promoted to backlog:** none

---

## [S8-S4] Storyboard settings header — collapsible grouped section
**Completed:** 2026-05-30
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- Replaced the flat `.sb-meta` row with a `.sb-settings` collapsible card rendered at the top of the storyboard section.
- Collapsed state: header bar with label "Storyboard Settings", one-line summary (`Style: X · Y · Subtitles ON/OFF · Music: Z`), `▾` chevron (rotates 180° via CSS transition when open).
- `toggleSbSettings()` added to global JS scope — toggles `.open` class on `#sb-settings-block`. Called via `onclick` on header.
- Expanded body (`display:flex; flex-wrap:wrap`) renders two side-by-side groups: **VIDEO STYLE** (Visual Style, Aspect Ratio, Subtitle Style, Rhythm, Total Duration) and **AUDIO** (Background Music, Volume, VO Ducking). Absent fields render `—` — ready for Sprint 9/11 data wiring with no further HTML changes.
- 612 tests passing. No new ENV vars.
**Smoke test:** PASSED — collapsed and expanded states verified via accessibility tree snapshot: summary line correct, all 8 detail fields present in expanded view, toggle works.
**Promoted to backlog:** none

---

## [S8-S3] Storyboard table UX — text wrapping and dynamic row height
**Completed:** 2026-05-30
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- Added `.data-table.sb-table { white-space: normal; }`, `.data-table.sb-table td { word-wrap: break-word; }` CSS rules — scoped to the storyboard table only, leaving the manifest table's `nowrap` behaviour unchanged.
- `class="data-table sb-table"` added to the storyboard `<table>` element in `renderStoryboardHtml`.
- Removed `class="trunc" title="..."` from the four text-heavy storyboard cells (Voiceover, Primary Query, Fallback Query, AI Prompt). Manifest table `.trunc` usage untouched.
- 612 tests passing.
**Post-close amendments (same session):** Additional storyboard table polish applied after story close:
  - `.section-pane.wide { max-width: none }` + `wide` class on `#section-storyboard` — panel extends to right edge of screen.
  - Font size reduced to 11px on `.data-table.sb-table`.
  - Per-column max-width classes: `text-sm` (160px, fallback query), `text-md` (220px, voiceover + primary query), `text-lg` (340px, AI prompt). Replaces the old uniform `text` class.
  - Column reordered: ID → Voiceover → Duration → Type → Primary Query → Fallback Query → AI Prompt → Motion → SFX → SFX Timing.
  - On-Screen Text column removed from storyboard table.
  - `humanize()` helper added to `renderStoryboardHtml` — replaces underscores with spaces in Type and Motion cell values (`still_with_motion` → `still with motion`, `zoom_in` → `zoom in`). Frontend-only; backend enum values unchanged.
**Smoke test:** PASSED — verified in preview: all columns present in correct order, humanized type/motion values, 11px font, `#section-storyboard` carries `.wide` class, no On-Screen Text column.
**Promoted to backlog:** none

---

## [S8-S2] Pipeline status simplification
**Completed:** 2026-05-30
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- **5 CSS dot states** replace Unicode characters. `dot-pending` (grey solid border), `dot-running` (dashed grey border + `dot-spin` CSS rotation animation), `dot-draft` (yellow fill, Input section when run exists but storyboard not started), `dot-complete` (green fill), `dot-failed` (red fill).
- `dotHtml(status)` updated to emit empty `<span class="dot dot-{state}"></span>` — no text content, works for all 5 states.
- `sectionStatus('input')` returns `'draft'` when `currentRunId !== null` and all input steps are still pending.
- Removed `#input-locked-bar`, `#storyboard-locked-bar`, `#assets-locked-bar` HTML divs, `.locked-bar`/`.locked-bar-spacer` CSS, and 3 JS display lines.
- Error bars (`#input-error`, `#storyboard-error`, `#assets-error`) moved to top of each section pane (immediately after `.section-title`) — visible without scrolling when a step fails.
- Left-panel run list dots also converted to CSS circles (no text chars).
- 612 tests passing.
**Smoke test:** PASSED — visual smoke test in preview: all 5 dot states confirmed (grey border, dashed spinning, yellow, green, red); no locked banners present; error bars at top of sections.
**Promoted to backlog:** none

---

## [S8-S1] Collapsible sidebar
**Completed:** 2026-05-30
**Handover:**
- `src/static/pipeline.html` only — no backend changes, no new ENV vars.
- Sidebar toggle (`#sidebar-toggle`) is `position: absolute` inside `.panels` (`position: relative`), pinned at `top: 11px; left: 10px; z-index: 10`. Lives outside `panel-runs` — always visible on page background regardless of collapse state.
- Toggling adds/removes `sidebar-collapsed` on `.panels`. Collapsed: `.panel-runs` animates to `width: 0; margin-right: 0` — fully gone. Expanded: `width: 200px; margin-right: 24px`. Icon flips `scaleX(-1)` when collapsed.
- Panel background `#F0EDEC` (slightly darker than page `#FBF9F8`). Panel starts flush with screen left edge (no left padding on `.panels`). Extends full viewport height (no bottom padding).
- "Content Factory" title removed. `+ New Project` is the first visible item in the left panel, styled as a borderless list row (48px top margin to clear the toggle icon).
- Session-only state via JS `sidebarCollapsed` variable. No page reload persistence.
**Smoke test:** PASSED — visual smoke test in preview: expanded shows project list flush with left edge; collapsed shows only toggle icon at top-left on page background with full-width content area; toggling back restores. 612 tests passing.
**Promoted to backlog:** none

---

## [S7-S3] E8-S4: Model router utility — centralize all Claude API model selection
**Completed:** 2026-05-30
**Handover:**
- `src/utils/model_router.py`: new `ModelRouter(settings)` class. Task type constants: `GENERATE`, `VALIDATE`, `SUMMARIZE`, `TRANSFORM`, `REASON`. `model_for(task) → str` returns the ENV-configured model; `log_cost(task, model, input_tokens, output_tokens) → float` emits a structured INFO log and returns the USD estimate. `PRICING` dict covers `claude-sonnet-4-6` and `claude-haiku-4-5-20251001`; unknown models log a warning and return 0.0.
- `src/config.py`: 4 new optional ENV vars: `MODEL_VALIDATE` (default haiku), `MODEL_SUMMARIZE` (default haiku), `MODEL_TRANSFORM` (default haiku), `MODEL_REASON` (default sonnet). Existing `CLAUDE_MODEL` maps to `GENERATE` task.
- `src/storyboard.py`: constructs `ModelRouter(settings)`, uses `router.model_for(GENERATE)` for model selection, captures `usage` from API response, calls `router.log_cost(GENERATE, ...)`. `_call_claude_api` now returns `(text, input_tokens, output_tokens)`.
- `src/validators/storyboard_validator.py`: `VALIDATOR_MODEL` and pricing constants derived from `ModelRouter.DEFAULT_MODELS` / `PRICING` (backward-compat exports preserved for tests). Accepts `router: Optional[ModelRouter] = None`; delegates model + cost when provided.
- `src/log_summarizer.py`: `HAIKU_MODEL` derived from `ModelRouter.DEFAULT_MODELS`. Accepts `router: Optional[ModelRouter] = None`; uses `router.model_for(SUMMARIZE)` and `router.log_cost()` when provided.
- `src/pipeline.py`: constructs `ModelRouter(settings)` in `summarize_step` and passes it to `write_run_log_summary`.
- `ENV.md`: 4 new vars documented.
- `tests/test_model_router.py`: 27 new tests. 612 total passing. No new pip dependencies.
**Smoke test:** PASSED — Railway DEV logs confirmed all 3 task types on 2026-05-30: `task=generate model=claude-sonnet-4-6 cost=$0.04746600` (storyboard), `task=validate model=claude-haiku-4-5-20251001 cost=$0.00329280` (validator), `task=summarize model=claude-haiku-4-5-20251001 cost~$0.00090` (run log, once per pipeline step).
**Promoted to backlog:** none

---

## [S7-S1] Full pipeline smoke test — validate all deferred smoke tests on Railway DEV
**Completed:** 2026-05-30
**Handover:**
- Full pipeline validated end-to-end on Railway DEV: login → new project → VO upload → alignment (Deepgram) → storyboard → asset acquisition → render → download.
- All 10 deferred smoke tests from Sprints 3–6 signed off in one session: S6-S6 (bounded player + modal + download), S6-S5 (assets Description + Open link), S6-S4 (storyboard 11-column table), S6-S3 (Save Draft + Create Storyboard lock), S6-S2 (project name identifier), S5-S5 (login/logout gate), S5-S4 (three-panel UI), S5-S2 (GET /runs latency), E5-S5 (VO-first pipeline), E5-S4 (Deepgram alignment.json).
- No blocking bugs found. No ENV vars added. No new dependencies.
**Smoke test:** PASSED — operator ran the complete pipeline on Railway DEV; all steps reached `complete` in `run_log.json`; video quality confirmed good.
**Promoted to backlog:** none

---

## [S6-S6] Render Video: bounded player + modal + Download button
**Completed:** 2026-05-29
**Handover:**
- `src/static/pipeline.html`: CSS — `.video-bounded` container (`max-height: 360px`, `overflow: hidden`, `cursor: pointer`, `background: #000`); `video` inside uses `object-fit: contain`. `.video-expand-btn` positioned absolute bottom-right. `.video-actions` flex row below the player. `.btn-download` styled as a light button. Modal CSS: `.video-modal-overlay` (`position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 1000; display: flex` when `.open`); `.video-modal-box` (max-width 640px, `max-height: 80vh`); `.video-modal-close` circular × button.
- HTML: `#video-modal` overlay injected between `.panels` and `<script>` — contains `#video-modal-box` with close button and `#video-modal-player` `<video>` element.
- JS: `populateRender()` now generates `.video-bounded` container with `onclick` → `openVideoModal`, `⤢ Expand` button, and `.video-actions` div with `.btn-download` anchor (`download="final.mp4"`). `openVideoModal(url)` sets player src and adds `.open` class. `closeVideoModal()` removes `.open` and pauses+clears src. `handleModalOverlayClick(event)` closes when clicking the backdrop (not the box).
- No backend changes. No new ENV vars. No new dependencies.
- 585 tests passing, no regressions.
**Smoke test:** PASSED — confirmed bounded video, modal expand/close, and download on Railway DEV.
**Promoted to backlog:** none

---

## [S6-S5] Assets stage: Description column + media link column
**Completed:** 2026-05-29
**Handover:**
- `src/models.py`: `AssetLinkResponse(url, expires_in)` added.
- `src/routes/runs.py`: `GET /runs/{run_id}/asset-link?key=...` — rejects keys outside `runs/{run_id}/` prefix and any containing `..` components (403); generates 1h presigned GET URL; returns `{url, expires_in: 3600}`.
- `src/static/pipeline.html`: `renderManifestHtml` rewritten — 6 columns: Scene, Type, Description, Source, Status, Link. Description = `primary_query` (truncated with tooltip). Link = "Open" anchor when `file_key` present, `—` when null. `openAssetLink()` async handler fetches presigned URL then calls `window.open`.
- No new ENV vars. No new pip dependencies.
- 585 tests passing (+6 new in `TestGetAssetLink`).
**Smoke test:** PASSED — confirmed Description column and asset media links on Railway DEV.
**Promoted to backlog:** none

---

## [S6-S4] Storyboard stage: full-data table view + permanent lock
**Completed:** 2026-05-29
**Handover:**
- `src/static/pipeline.html`: CSS — `.scene-cards`/`.scene-card` styles replaced with `.sb-meta` (global metadata row) and updated `.data-table` (added `white-space: nowrap`, removed fixed `width: 100%` to let table scroll freely). `renderStoryboardHtml(content)` rewritten: renders a `.sb-meta` row with bg_music, visual_style, subtitle_style, rhythm, total_duration_s from `content.global`, followed by a horizontally-scrollable `.table-wrap` table with 11 columns — Scene, Type, Duration, Voiceover, On-Screen Text, Primary Query, Fallback Query, AI Prompt, Motion, SFX, SFX Timing. Null/optional fields render as `—` (muted grey). Long text cells use `.trunc` with `title` tooltip.
- Storyboard CTA button: id `approve-assets-btn` → `run-acquisition-btn`; label "Approve & Get Assets" → "Run Asset Acquisition"; `onclick` → `runAssetAcquisition()`. Locked bar text updated to "✓ Asset acquisition complete".
- `runApproveAssets()` renamed to `runAssetAcquisition()`; internal button reference updated. Logic unchanged — sequences `POST /manifest` then `POST /assets`.
- `populateStoryboard()` updated to reference new button id and label.
- No backend changes. No new ENV vars. No new dependencies.
- 579 tests passing, no regressions.
**Smoke test:** PASSED — confirmed storyboard table, all columns, acquisition flow on Railway DEV.
**Promoted to backlog:** none

---

## [S6-S3] Input stage: Save Draft + Create Storyboard (lock mechanic)
**Completed:** 2026-05-29
**Handover:**
- `src/models.py`: `DraftRequest(project_name, script)` + `DraftResponse(status, project_name, script, vo_filename=None)` added. `StoryboardRequest.script` default changed to `""` (enables R2 fallback).
- `src/routes/runs.py`: `POST /runs/{run_id}/draft` — guards against storyboard-complete (409); saves script to `runs/{run_id}/script.txt`; idempotent overwrite otherwise. `GET /runs/{run_id}/draft` — returns project_name (from run_log), script (from script.txt, empty if absent), vo_filename (first audio file in voiceover/ prefix, null if none).
- `src/routes/storyboard.py`: If `body.script` is empty, reads `script.txt` from R2; returns 422 if both body and R2 are empty.
- `src/static/pipeline.html`: Input locked bar: "Regenerate" removed (permanent lock, MVP). CTA: "Save Draft" + "Create Storyboard" side by side. `saveDraft()` calls `_ensureRun()` + `POST /draft`. `populateInput()` async — loads `GET /draft` in both locked and unlocked states to populate script + VO filename. `updateSaveDraftBtn()` gates on name + script present + not locked. Post-deploy regression fix: removed `border-left: 2px solid #9A9A9A` from `.run-item.active` and `.nav-item.active`; restored `+ New Project` button inline in `.app-header` (linter had displaced it to a `.new-project-row` div in the left panel).
- `tests/test_runs.py`: 16 new tests (TestSaveDraft × 7, TestGetDraft × 5; 4 extra for new patterns). `tests/test_storyboard.py`: 2 new tests for script.txt fallback. 579 total tests passing.
- No new ENV vars. No new pip dependencies.
**Smoke test:** PASSED — confirmed full run creation, Save Draft, and pipeline trigger on Railway DEV.
**Promoted to backlog:** none

---

## [S6-S2] Project Name as primary identifier (auto-slug, backend + UI)
**Completed:** 2026-05-29
**Handover:**
- `src/models.py`: `RunCreateRequest` now accepts `project_name: str` (stripped, 1–120 chars). `RunCreateResponse` gains `project_name: str`. `RunSummary` and `RunLog` gain `project_name: Optional[str] = None` (backward-compatible; legacy run_log.json without the field deserialises cleanly).
- `src/routes/runs.py`: `_slugify(name) → str` helper (`re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")`). `POST /runs` accepts `project_name`, slugifies to build `run_id`, passes name to storage, returns it in response. Old `slug` field removed.
- `src/storage.py`: `_build_run_log(run_id, project_name=None)` and `create_run_folder(run_id, project_name=None)` write `project_name` into `run_log.json`. `list_runs._fetch` reads and returns `project_name` (null for legacy runs).
- `src/static/pipeline.html`: Left-panel new-project form removed entirely. "+ New Project" calls `openNewProjectForm()` — opens Input section with blank form, no run created yet. Input section field order: Project Name → Voiceover → VO Script → Create Storyboard button. `_ensureRun()` creates the run lazily on first VO Upload or Create Storyboard click. `openRun()` populates Project Name read-only for existing runs. Left panel list renders `project_name || run_id`.
- `tests/test_runs.py`: Fully rewritten; `TestCreateRunNameValidation` replaces `TestCreateRunSlugValidation`; old `slug` field tests removed; 8 net new tests.
- `tests/test_storage.py`: 4 new tests for `project_name` in `_build_run_log` and `create_run_folder`.
- No new ENV vars. No new pip dependencies. 543 total tests passing.
**Smoke test:** PASSED — confirmed project name display, R2 run_log.json, and slug generation on Railway DEV.
**Promoted to backlog:** none

---

## [S6-S1] Design system: color palette, typography, panel spacing
**Completed:** 2026-05-29
**Handover:**
- `src/static/pipeline.html` — CSS + HTML + JS only; no backend changes. Full design system applied.
- Color tokens in use: `#FBF9F8` bg (body, panels, inputs, tables), `#2D2D2D` primary text, `#9A9A9A` muted, `#EFECEB` hover/secondary, `#E8E5E4` card borders, `#F0EDEC` table row dividers.
- Font: `Inter, system-ui, sans-serif`. Weights: 400 body, 500 section labels, 600 CTAs.
- Layout: full-width `.app-header` (flex row, `padding: 40px 20px 28px`). `+ New Project` (`.btn-outline`) inline next to title. Left↔mid gap 32px, mid↔right 16px. All three panels start content at the same vertical baseline.
- Middle panel: `nav-run-id` and `← Projects` back nav removed. Clicking the active project in the left panel toggles `deselectRun()`.
- Nav items: triple-chevron SVG connector injected between steps via `renderNavItems()` join.
- Active state: `font-weight: 600` only — no border decoration, no blue.
- Dot logic: `○` pending, `●` complete/failed/in-progress; consistent across both panels.
- New `.btn-outline` class (transparent bg, `#d1d5db` border). Logout button has inline SVG icon.
- 535 tests passing, no regressions.
**Smoke test:** PASSED — layout verified in static preview at 800px; all three panels aligned at top baseline; active states, dot colours, chevron connectors, and header layout confirmed visually.
**Promoted to backlog:** none

---

## [S5-S5] Single-operator password gate
**Completed:** 2026-05-28
**Sprint:** 5
**Handover:**
- `src/auth.py`: `AUTH_COOKIE_NAME = "cf_session"`. `sign_cookie(secret_key) → str` — HMAC-SHA256 hex digest. `verify_cookie(value, secret_key) → bool` — constant-time compare.
- `src/routes/auth.py`: `POST /auth/login` — validates password, sets httponly cookie (`secure=True` in prod); `POST /auth/logout` — deletes cookie. Both exempt from middleware.
- `src/main.py`: auth middleware added — exempt paths: `/health`, `/login`, `/auth/login`, `/auth/logout`. Browser (Accept: text/html) → 302; API fetch → 401. Uses `request.app.dependency_overrides.get(get_settings, get_settings)()` to honour test DI. `GET /login` route added.
- `src/config.py`: `OPERATOR_PASSWORD: str` and `SESSION_SECRET_KEY: str` added (both required, no defaults).
- `src/static/login.html`: new light-mode login page; `POST /auth/login` on form submit; 200 → `/`; 401 → inline error.
- `src/static/pipeline.html`: `logOut()` wired to `POST /auth/logout` + redirect; global `window.fetch` wrapper redirects to `/login` on any 401.
- `tests/conftest.py`: `bypass_auth_middleware` autouse fixture patches `src.main.verify_cookie → True` for all non-auth tests.
- All VALID_ENV dicts updated with `OPERATOR_PASSWORD` and `SESSION_SECRET_KEY`.
- 535 total tests passing (20 new). No new pip dependencies. D037 in DECISIONS.md.
**Smoke test:** PASSED — confirmed auth gate, login/logout, and wrong-password error on Railway DEV.
**Promoted to backlog:** none

---

## [S5-S4] UI redesign: 5-step collapsed pipeline + new visual design
**Completed:** 2026-05-28
**Sprint:** 5
**Handover:**
- `src/static/pipeline.html`: full rewrite. Three-panel layout (`body { display:flex }`): left 240px run list / middle 188px section nav / right `flex:1` content area.
- Four operator sections replace six explicit backend steps: **Input** (alignment+storyboard), **Storyboard** (manifest+asset_acquisition), **Assets** (ffmpeg_script+render), **Rendered Video** (display only).
- Each section has a single primary CTA that runs its backend steps in sequence via `runSequence()` — inline per-step progress rows with live dot updates, no page reload.
- Lock mechanic: `sectionLocked={input,storyboard,assets}` initialised from `currentSteps` in `openRun()`. Set `true` on CTA success (shows green locked bar + "Regenerate"). `regenerateSection()` sets `false` — never re-derived from steps after init so Regenerate stays open.
- Auto-navigation: each CTA navigates to the next section on success.
- URL hash routing: `#run/{id}/section` (new depth) and `#run/{id}` (S5-S1, preserved). `popstate` covers browser back/forward.
- Auth stubs: "Log out" button in left-panel footer calls `logOut()` which is a no-op with `// TODO: S5-S3`. No `/login` redirect guard.
- Design: light bg `#f9fafb`, system sans-serif labels, monospace for IDs/data, `#1d4ed8` blue for primary CTAs only. No external dependencies.
- No backend changes. No new ENV vars. No new pip dependencies. 515 tests passing.
**Smoke test:** PASSED — confirmed three-panel layout, lock states, full pipeline flow, and URL navigation on Railway DEV.
**Promoted to backlog:** none

---

## [S5-S2] Page load performance diagnosis + fixes
**Completed:** 2026-05-28
**Sprint:** 5
**Handover:**
- `src/storage.py`: `list_runs()` rewritten with two targeted fixes. Fix 1 — delimiter listing: `list_objects_v2` now called with `Delimiter="/"` so R2 returns only run folder names via `CommonPrefixes` (e.g. `runs/2026-05-28_my-run/`), not every asset key inside each run. Eliminates O(runs × assets_per_run) key scan. Fix 2 — parallel fetch: `get_json()` calls dispatched concurrently via `ThreadPoolExecutor.map` instead of a sequential for-loop. Wall-clock time drops from N × ~70ms to ~70ms regardless of run count. Per-run `StorageError` is caught and logged as a warning; other runs are unaffected.
- `src/routes/runs.py`: `GET /runs` handler logs total elapsed ms via `logger.info("GET /runs: %d runs in %.0fms", ...)`.
- `docs/PERF.md`: new — root-cause analysis (O(N×M) listing + N serial round-trips), before/after timing estimates (~800ms → ~120ms for 10 runs), known limitations (pagination cap at 1000 runs; `showDetail()` double-fetch).
- `tests/test_storage.py`: 18 → 20 tests. `TestListRuns` updated to use `CommonPrefixes` mock format. Added `test_uses_delimiter_to_list_prefixes` and `test_partial_failure_returns_readable_runs`.
- No new ENV vars. No new pip dependencies (`concurrent.futures` is stdlib).
**Smoke test:** PASSED — confirmed GET /runs latency within target on Railway DEV.
**Promoted to backlog:** `showDetail()` in `pipeline.html` calls `GET /runs` a second time to populate step state — a `GET /runs/{run_id}` endpoint would halve the request count on run-open. Noted in `docs/PERF.md`; deferred to future sprint.

---

## [S5-S1] URL-based run navigation (fix refresh bug)
**Completed:** 2026-05-28
**Sprint:** 5
**Handover:**
- `src/static/pipeline.html`: `showDetail(runId)` calls `history.pushState(null, '', '#run/' + runId)` to set the URL hash without triggering `hashchange`. `showList()` calls `history.pushState(null, '', window.location.pathname)` to clear the hash. A `popstate` listener routes back/forward button presses by parsing `location.hash` and calling the appropriate view function. An IIFE at script init reads the hash on first load, enabling refresh-in-run and deep links.
- Implementation detail: used `history.pushState` rather than `window.location.hash =` to avoid double-execution — `pushState` does not fire `hashchange`, so `showDetail`/`showList` won't be called twice.
- No backend changes. No new ENV vars. No new pip dependencies.
- 512 tests passing (no regressions).
**Smoke test:** PASSED — deep link `/#run/2026-05-27_st-finetune` landed directly on detail view; reload stayed in detail; "← Runs" cleared hash and returned to list; browser back restored detail. Verified live on Railway DEV with Claude in Chrome.
**Promoted to backlog:** none

---

## [E4-S7] Word-synced captions using Deepgram timestamps
**Completed:** 2026-05-28
**Sprint:** 4
**Handover:**
- `src/captions.py`: `build_word_synced_captions_ass(scene_words: list[list[WordTimestamp]], chunk_size=5) -> str` — accepts Deepgram words grouped per scene. For each word, emits one Dialogue event: active word in yellow `{\c&H0000FFFF&}`, rest white `{\c&H00FFFFFF&}`. Event end time = next word's `start_ms` (fills inter-word gaps; caption stays visible continuously). Last word of a non-final chunk extends to next chunk's first word start. Last word of final chunk ends at its own `end_ms`. Chunks never cross scene boundaries.
- `src/ffmpeg_builder.py`: `assign_words_to_scenes(scenes, words) -> list[list[WordTimestamp]]` — greedy sequential text matching; normalises via `re.sub(r"[^\w]","",w).lower()`; splits voiceover tokens on hyphens so "6-minute" → ["6","minute"] and both Deepgram words are matched. `compute_scene_durations_from_alignment(scenes, scene_words) -> list[StoryboardScene]` — scene N duration = `(next_scene_first_word.start_ms - this_scene_first_word.start_ms)/1000` (inter-phrase pauses absorbed into preceding scene, eliminating video-shorter-than-VO bug); last scene uses own word span; unmatched scenes keep original `duration_s`; all durations floored at `_MIN_SCENE_DURATION_S`. `build_ffmpeg_script` gains `scene_words: Optional[list[list[WordTimestamp]]] = None`; falls back to `build_captions_ass` when None.
- `src/routes/ffmpeg_script.py`: when `alignment.json` present with words → calls `assign_words_to_scenes` + `compute_scene_durations_from_alignment` to correct scene durations deterministically; passes `scene_words` to `build_ffmpeg_script`.
- 512 total tests passing (+42 new). No new ENV vars. No new pip dependencies.
**Smoke test:** PASSED — operator watched rendered Short on Railway DEV; visuals sync with VO; captions advance word-by-word with yellow highlights; no intra-scene jumping; cross-scene caption merging fixed; "6-minute" style hyphenated words display correctly.
**Promoted to backlog:** none

---

## [E5-S5] Pipeline reorder: VO-first with Deepgram-driven storyboard
**Completed:** 2026-05-27
**Sprint:** 4
**Handover:**
- `src/models.py`: `PIPELINE_STEPS` reordered — `"alignment"` is now first, before `"storyboard"`. New run initializations reflect the VO-first order.
- `src/storyboard.py`: `generate_storyboard(script, settings, word_timestamps=None)` — new optional param. When `word_timestamps` is provided, `_call_claude_api` prepends a `WORD TIMESTAMPS (Deepgram Nova-2 — use these for scene duration_s):` block to the user message. `_format_timestamps(words) → str` helper added. Prompt bumped to v0.8.
- `src/routes/storyboard.py`: Before calling Claude, attempts `storage.get_json(f"runs/{run_id}/alignment.json")`; builds `list[WordTimestamp]` and passes to `generate_storyboard`. Falls back to `word_timestamps=None` on `StorageError` (legacy runs unchanged).
- `src/routes/ffmpeg_script.py`: After loading storyboard + manifest, checks for `alignment.json` via `storage.get_json`. If found → skips ffprobe redistribution block entirely. If `StorageError` → falls through to existing ffprobe redistribution (backward compat for runs without alignment).
- `src/static/pipeline.html`: Full UI rewrite. New run panel: slug only (no script textarea). Step order: VO Upload → Alignment → Storyboard → Manifest → Assets → FFmpeg Script → Render. Storyboard shows amber `"run Alignment first"` gate until `currentSteps.alignment === 'complete'`. `refreshAllActions()` called after every step completion. `autoRunNewRun` removed — operator drives steps manually.
- `docs/PROMPTS.md`: Bumped to v0.8. Changelog + TIMESTAMP ALIGNMENT section added.
- `tests/test_storyboard.py`: `_mock_storage()` defaults `get_json` to `StorageError`; 2 new tests for alignment passthrough and no-alignment-passes-None.
- `tests/test_ffmpeg_builder.py`: All route tests updated with 3rd `StorageError` for alignment check; `test_alignment_present_skips_redistribution` added.
- 470 total tests passing (+8 net). No new ENV vars. No new pip dependencies.
**Smoke test:** PASSED — confirmed full VO-first pipeline and word-boundary scene cuts on Railway DEV.
**Promoted to backlog:** none

---

## [E8-S3] Haiku run log summarizer
**Completed:** 2026-05-27
**Sprint:** 3
**Handover:**
- `src/log_summarizer.py`: `generate_run_log_summary(run_log_data, api_key) → str` — calls Haiku (`claude-haiku-4-5-20251001`), max_tokens=512. `write_run_log_summary(run_id, storage, api_key) → None` — reads `run_log.json`, calls Haiku, writes `run_log.txt` to R2; catches all exceptions (never raises).
- `src/pipeline.py`: `summarize_step(run_id, storage, settings) → None` — thin wrapper. All 6 pipeline routes import it and call it after every `update_run_log` (complete and failed paths).
- `src/routes/runs.py`: new `GET /runs/{run_id}/run-log-txt` → `RunLogTxtResponse(content, available)`. Returns `available=False` if file not yet written.
- `src/models.py`: `RunLogTxtResponse` added.
- `src/static/pipeline.html`: Run Log collapsible section below step rows. Fetches on `showDetail` and after every step completion.
- `tests/conftest.py`: autouse fixture patches `src.log_summarizer.Anthropic` globally — prevents real HTTP calls in all tests.
- `tests/test_manifest.py` + `tests/test_alignment.py`: two `get_json.assert_called_once_with` → `assert_any_call` (summarizer adds a second `get_json` call).
- R2 key: `runs/{run_id}/run_log.txt`. No new ENV vars. No new pip deps.
- 462 total tests passing (18 new).
**Smoke test:** POST a pipeline step on DEV — confirm `run_log.txt` appears in R2 with Haiku-generated step summary. Open run detail in UI and verify Run Log section appears and is collapsible.
**Promoted to backlog:** none

---

## [E8-S1] Haiku schema validator — storyboard.json
**Completed:** 2026-05-27
**Sprint:** 3
**Handover:**
- `src/validators/__init__.py` — new package.
- `src/validators/storyboard_validator.py` — `validate_storyboard(storyboard, api_key) → ValidationResult` (async). Calls `claude-haiku-4-5-20251001` with an 8-rule validation system prompt + serialised storyboard JSON. Parses `{"valid": bool, "errors": [...]}` response. Raises `StoryboardValidationError` on API failure or unparseable Haiku response. `_INPUT_COST_PER_TOKEN = 0.80/1M`, `_OUTPUT_COST_PER_TOKEN = 4.00/1M` — cost calculated and returned in `ValidationResult`.
- `src/models.py` — `StepLog` gains `input_tokens: Optional[int]`, `output_tokens: Optional[int]`, `cost_usd: Optional[float]` fields. `ValidationResult(valid, errors, input_tokens, output_tokens, cost_usd)` model added.
- `src/exceptions.py` — `StoryboardValidationError` added.
- `src/storage.py` — `update_run_log` gains `input_tokens`, `output_tokens`, `cost_usd` optional kwargs; writes them to the step dict when provided.
- `src/storyboard.py` — `generate_storyboard` changed to `tuple[Storyboard, ValidationResult]` return type. Calls `validate_storyboard` after parsing; raises `StoryboardValidationError` with joined error list if `valid=False`.
- `src/routes/storyboard.py` — `StoryboardValidationError` added to the caught exception tuple. On success, passes `input_tokens`, `output_tokens`, `cost_usd` from the `ValidationResult` to `update_run_log`.
- `tests/test_storyboard_validator.py` — 11 new tests: valid/invalid paths, token recording, cost calculation formula, API error, unparseable JSON, missing `valid` key, model string assertion, storyboard serialisation check, errors list type.
- `tests/test_storyboard.py` — all mocks updated to return `(storyboard, ValidationResult)` tuple. `test_success_uploads_and_updates_run_log` renamed to `test_success_uploads_and_updates_run_log_with_cost` with cost field assertions added. Two new tests: `test_validation_error_returns_500` and `test_validation_failure_updates_run_log_as_failed`.
- 444 total tests passing (13 new).
- No new pip dependencies. No new ENV vars (reuses `ANTHROPIC_API_KEY`).
**Smoke test:** Submit a valid storyboard on DEV — confirm pipeline proceeds. Submit a storyboard with a missing `sfx` field — confirm halt + error in `run_log.json`.
**Promoted to backlog:** none

---

## [E5-S4] Word-level timestamp extraction via Deepgram
**Completed:** 2026-05-27
**Sprint:** 3
**Handover:**
- `src/alignment.py`: `align_audio(audio_url, api_key) → list[WordTimestamp]` — async; `POST` to `https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true` with `{"url": audio_url}`; raises `AlignmentError` on non-200 or network error. `_normalize_word(raw)` converts float seconds → int ms, strips punctuation via `[^\w\s]` regex. `proportional_fallback(text, total_duration_s)` distributes total_ms by char count per word; confidence=0.0 flags estimates.
- `src/routes/alignment.py`: `POST /runs/{run_id}/alignment` — discovers voiceover in R2 via `list_keys(runs/{run_id}/voiceover/)` filtering `.mp3/.wav/.m4a`; generates 5-min presigned GET URL for Deepgram; falls back to `_proportional_from_storyboard` (reads `storyboard.json`) if key absent or API fails. Stores `alignment.json`: `{run_id, word_count, used_fallback, words: [...]}`. `update_run_log` wrapped in broad try/except — non-fatal for old runs without the "alignment" step key.
- `src/models.py`: `WordTimestamp(word, start_ms, end_ms, confidence)` and `AlignmentResponse(status, alignment_key, word_count, used_fallback)` added. `PIPELINE_STEPS` gains `"alignment"` between `"asset_acquisition"` and `"ffmpeg_script"`.
- `src/config.py`: `DEEPGRAM_API_KEY: str = ""` — empty default triggers proportional fallback path.
- `src/exceptions.py`: `AlignmentError` added.
- `ENV.md`: `DEEPGRAM_API_KEY` documented.
- R2 key: `runs/{run_id}/alignment.json`. No new pip dependencies. D034 was pre-existing in DECISIONS.md.
- `tests/test_alignment.py`: 37 new tests — unit for `_normalize_word`, `_extract_words`, `proportional_fallback`, `align_audio` (httpx mocked), 13 route integration tests. 431 total passing.
- **Pipeline position:** Standalone step, not yet wired into UI or auto-triggered. E5-S5 will integrate.
**Smoke test:** PASSED — confirmed alignment.json in R2 with word-level timestamps on Railway DEV.
**Promoted to backlog:** none

---

## [E4-S6] Subtitle style revision (Poppins Bold, TikTok-style) — Iteration 2
**Completed:** 2026-05-27
**Sprint:** 3
**Handover:**
- `src/captions.py`: `_CAPTIONS_ASS_HEADER` VoiceCaption style — `Poppins` (fontname), Bold=1, 92pt, white, black outline 8px, shadow 1px, MarginV=350, Alignment=2 (bottom-center). Replaces Montserrat ExtraBold 72pt from Iteration 1. `_ASS_HEADER` Default style (on-screen keywords) — PrimaryColour reverted to white `&H00FFFFFF` (was yellow `&H0000FFFF`).
- `assets/fonts/Poppins-Bold.ttf` — bundled in repo (152 KB), sourced from Google Fonts. `fonts-poppins` does not exist as a Debian apt package (D035).
- `Dockerfile` — `COPY assets/fonts/Poppins-Bold.ttf /usr/local/share/fonts/Poppins-Bold.ttf` + `RUN fc-cache -f /usr/local/share/fonts` added after the apt layer.
- `DECISIONS.md` — D035 was pre-written; no new entry required.
- `tests/test_captions.py` — 4 tests renamed/updated, 1 new test added (`test_voicecaption_shadow_is_1`). 394 total tests passing.
- No new Python dependencies. No new ENV vars.
- Prior Iteration 1 artifacts retained: Montserrat apt package (harmless), v0.6 prompt voiceover_line constraint (4–6 words), D033.
**Smoke test:** PASSED — Poppins Bold renders on Railway DEV; captions match SampleDis reference at mobile screen size. MarginV bumped 250→350 post-render for better bottom clearance (committed in `628474b`).
**Promoted to backlog:** none

---

## [E6-S4] End-to-end production smoke test
**Completed:** 2026-05-27
**Sprint:** 3
**Points:** 2
**Handover:**
- Full pipeline validated on Railway DEV from browser UI: create run → storyboard → manifest → assets → ffmpeg-script → voiceover upload → render → watchable `final.mp4` in R2.
- R2 CORS configured on `content-factory-dev` bucket — browser PUT for voiceover direct-upload confirmed working.
- All deferred smoke tests from Sprint 1 and Sprint 2 validated in a single session.
**Bugs found:**
- Pacing: visuals rush/lag behind VO — expected; deferred to E5-S4 (WhisperX forced alignment).
- Subtitle size too small for mobile (42pt) — promoted to E4-S6 (style overhaul).
- Voiceover lines too long for larger font — promoted to E4-S6 (prompt fix, enforce 4-6 words).
**Smoke test:** PASSED — full pipeline ran end-to-end from browser UI; `final.mp4` rendered and watchable.
**Promoted to backlog:** E4-S6 (subtitle style overhaul + voiceover line shortening)

---

Format:

---

## [E4-S4] CLIP semantic reranking of Pexels results
**Completed:** 2026-05-25
**Sprint:** unassigned
**Handover:**
- `src/clip_reranker.py`: new module. `CLIPReranker(model)` — `rerank_videos(videos, query)` and `rerank_photos(photos, query)` score Pexels thumbnails against query text using CLIP cosine similarity (numpy only, no torch in application code). Module-level singleton via `load_model()` (lazy-loads `clip-ViT-B-32` via `sentence-transformers`) and `get_reranker() → Optional[CLIPReranker]`. Unscoreable items (missing/unfetchable thumbnails) placed after scored items. Raises `CLIPError` on encoding failure, which callers catch and fall back from.
- `src/pexels.py`: `_acquire_video` reranks video results by CLIP score before the `_pick_best_video_file` loop. `_acquire_photo` reranks photo results then picks via new `_pick_first_qualifying_photo` (first photo ≥ 1920×1080 in CLIP order); falls back to `_pick_best_photo` on `CLIPError` or when reranker is None (default).
- `src/pexels.py`: `_pick_first_qualifying_photo(photos) → Optional[dict]` — new module-level helper; existing `_pick_best_photo` (min excess area) retained for non-CLIP path.
- `src/main.py`: lifespan hook calls `clip_reranker.load_model()` when `CLIP_RERANK_ENABLED=True`.
- `src/config.py`: `CLIP_RERANK_ENABLED: bool = False` added.
- `src/exceptions.py`: `CLIPError` added.
- `requirements.txt`: `sentence-transformers>=3.0.0`, `Pillow>=10.0.0` added (D032).
- `ENV.md`: `CLIP_RERANK_ENABLED` documented.
- `tests/test_clip_reranker.py`: 17 new tests. 390 total passing. Zero regressions.
- Smoke test deferred: set `CLIP_RERANK_ENABLED=True` in Railway DEV, run full pipeline, confirm footage topics visually match VO better than Pexels-order baseline.
**Promoted to backlog:** none

---

## [E5-S3] Visual-semantic matching improvement
**Completed:** 2026-05-25
**Sprint:** 2
**Handover:**
- `docs/PROMPTS.md` v0.5: VISUAL PROMPTS RULE rewritten — PRIMARY = 3–4 concrete nouns only (no adjectives); FALLBACK = 1–2 words (core subject); AI_GENERATE = cinematic direction terms (shallow depth of field, golden hour lighting, cinematic, 9:16 vertical). Four housing-economics few-shot examples added. No code changes to acquisition pipeline — queries flow through unchanged.
- `src/storyboard.py`: `SYSTEM_PROMPT` updated to v0.5. Parser hardened: section split now uses `(?m)^\s*---\s*$` (line-anchor, handles any surrounding blank-line count); `_get_field` is now case-insensitive and tolerates leading `- ` bullets; both log diagnostic content on failure.
- `src/static/pipeline.html`: storyboard scene cards now show PRIMARY / FALLBACK / AI fields for visual QA.
- No new ENV vars. No new dependencies.
- Smoke test passed on DEV: `2026-05-25_mind-drain-video-temp` — concrete nouns in PRIMARY, cinematic direction in AI_GENERATE confirmed.
**Promoted to backlog:** none

---

## [E4-S5] Real-time captions from voiceover_line
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/captions.py`: `_CAPTIONS_ASS_HEADER` — new ASS header with `VoiceCaption` style (Open Sans Regular/Bold=0, 42pt, white + black outline, Alignment=2 bottom-center, MarginV=80). `build_captions_ass(scenes) -> str` — generates ASS from `voiceover_line` per scene; empty/whitespace-only lines produce no Dialogue event; text is displayed as-is (no quote stripping, no uppercasing). Timing accumulated from `duration_s` same as `build_ass`.
- `src/ffmpeg_builder.py`: `_write_voiceover_captions_ass(ass_content)` — heredoc with `'__VCAP_EOF__'` delimiter → `$WORK/voiceover_captions.ass`. `_burn_voiceover_captions()` — burns into `video_captioned.mp4` → `video_captioned2.mp4`. `build_ffmpeg_script` wires both new calls after `_burn_captions()` and before `_audio_section()`. `_audio_section` updated to read `video_captioned2.mp4` (was `video_captioned.mp4`).
- Render chain: `video_only.mp4` → on-screen overlay → `video_captioned.mp4` → voiceover captions → `video_captioned2.mp4` → audio mix → `final.mp4`.
- `tests/test_captions.py`: 17 new tests in `TestBuildCaptionsAss`. `_scene` helper gains optional `voiceover_line` param.
- `tests/test_ffmpeg_builder.py`: 2 existing tests updated (audio input reference + null-on-screen narrowed). 6 new tests in `TestCaptionsInScript` covering chain ordering, second-pass wiring, and no-uppercase assertion.
- 369 total tests passing (28 new). No new ENV vars. No new pip dependencies.
- Smoke test deferred.
**Promoted to backlog:** none

---

## [E4-S2] Captions and on-screen text overlay
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/captions.py`: `format_ass_time(seconds: float) -> str` — converts seconds to ASS `H:MM:SS.cc`. `build_ass(scenes: list[StoryboardScene]) -> str` — generates complete ASS file from storyboard scenes; accumulates `duration_s` offsets; skips scenes where `on_screen_text=None`; uppercases all text.
- `src/ffmpeg_builder.py`: `_write_captions_ass(ass_content)` embeds ASS content via quoted heredoc (`'__ASS_EOF__'`) — prevents bash from expanding `$`-vars or ASS override-tag braces inside the heredoc body. `_burn_captions()` runs `ffmpeg -vf "ass=$WORK/captions.ass"` producing `$WORK/video_captioned.mp4`. `_audio_section` now reads `video_captioned.mp4` (was `video_only.mp4`). `build_ffmpeg_script` calls both new builders between `_filter_complex_concat` and `_audio_section`.
- `Dockerfile`: `fonts-open-sans` added to the apt install layer so Open Sans is available to FFmpeg's libass inside the Railway container.
- 341 total tests passing (30 new). No new ENV vars. No new pip dependencies.
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed assets + voiceover; verify `captions.ass` heredoc in generated script and captions visible in rendered video.
**Promoted to backlog:** none

---

## [E4-S3] Ken Burns zoompan effect on static images
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `_render_image_scene` pre-scale corrected from 2×(2160×3840) to 1×(1080×1920). The centering formula `iw/2-(iw/zoom/2)` used in `_zoompan_filter` requires `iw` (input width) to equal `ow` (s= output width). With 2× input, `iw=2160` and `ow=1080`, causing the formula to produce x=0 (left-edge crop) at z=1 instead of centered behavior.
- `_SCALED_W` and `_SCALED_H` constants removed from `ffmpeg_builder.py` — were only used by the broken 2× scale path.
- `_zoompan_filter()` unchanged. Frame count `d=duration_s*25`, output `s=1080x1920`, `fps=25`, zoom expressions all correct.
- `tests/test_ffmpeg_builder.py`: 3 new regression tests — `test_still_with_motion_prescales_to_output_dimensions`, `test_animated_prescales_to_output_dimensions`, `test_image_scene_vf_chain_order_is_scale_zoompan_setsar`. These guard against re-introduction of 2× scale.
- 311 total tests passing (3 new).
- No new ENV vars. No new dependencies.
- Smoke test deferred — POST `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed assets exists; verify image scenes show Ken Burns motion in the rendered video.
**Promoted to backlog:** none
## [E#-S#] Story title
**Completed:** YYYY-MM-DD
**Sprint:** N
**Handover:** [summary of what was built, key decisions, anything the next story needs to know]

---

## [E5-S2] Pacing calibration — sync scene durations to voiceover
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `get_audio_duration(path: Path) -> float` — runs `ffprobe -v quiet -print_format json -show_format`, parses `format.duration`, raises `FFmpegBuildError` on non-zero exit or unparseable output.
- `src/ffmpeg_builder.py`: `redistribute_scene_durations(scenes, audio_duration) -> list[StoryboardScene]` — pure function; uses word count of `voiceover_line` as weight (minimum 1 for empty lines); enforces minimum 0.5s per scene; returns new instances, originals unchanged.
- `src/ffmpeg_builder.py`: `_filter_complex_concat(n_scenes)` replaces `_concat_list` + `_concat_command`. Produces a single ffmpeg call: all `$WORK/scene_XX.mp4` as inputs → filter_complex `[i:v]setpts=PTS-STARTPTS[vi]` per clip → `concat=n=N:v=1:a=0[vout]` → re-encode to `$WORK/video_only.mp4`. Fixes non-monotonic DTS from the old concat demuxer.
- `src/routes/ffmpeg_script.py`: before calling `build_ffmpeg_script`, lists `runs/{run_id}/voiceover/` in R2, downloads the first `.mp3/.wav/.m4a` to a `TemporaryDirectory`, measures duration with ffprobe, redistributes scenes, passes updated storyboard to builder. If no voiceover or any error, logs a warning and continues with original durations.
- **Bug fix:** `n_scenes` in `build_ffmpeg_script` now derived from `len(manifest.entries)` not `storyboard.summary.total_scenes`. Stale summary values caused dangling `scene_XX.mp4` references → ffmpeg exit 254.
- **Bug fix:** `,setsar=1:1` appended to every `-vf` chain in `_render_video_scene` and `_render_image_scene`. Source images/videos carry varying SAR values (e.g. `6778880:6778343`) which caused `filter_complex` concat to fail with "Input link parameters do not match".
- No new ENV vars. No new pip dependencies (ffprobe ships with ffmpeg, already required by E5-S1).
- 308 total tests passing (28 new).
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed storyboard + manifest + assets + uploaded voiceover; verify video cuts align with speech cadence.
**Promoted to backlog:** none

---

## [E6-S2] Operator UI — Run list and pipeline runner (+ E6-S3 inline)
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/static/pipeline.html`: complete rewrite — two-view SPA (list + detail), no frameworks. List view calls `GET /runs`, renders rows with colored status dot; click → detail. "+ New Run" panel has slug + VO script fields; on submit auto-triggers storyboard → manifest. Detail view shows 5 step rows: complete = [View]+[Rerun], pending/failed = [Run]. Storyboard [Run]/[Rerun] expands inline VO textarea. [View] fetches `GET /runs/{run_id}/artifact/{step}` and renders inline (storyboard → scene cards; manifest → table; ffmpeg_script → `<pre>`; render → `<video>`). Voiceover section (dashed row, between FFmpeg Script and Render): file picker → presigned PUT → direct R2 upload.
- `src/storage.py`: `R2Client.generate_presigned_put_url(key, expires_in=600) → str` added. Same exception pattern as `generate_presigned_url`.
- `src/models.py`: `VoiceoverUploadUrlRequest(filename: str)`, `VoiceoverUploadUrlResponse(upload_url: str, key: str)` added.
- `src/routes/runs.py`: `POST /runs/{run_id}/voiceover-upload-url` added. Key pattern: `runs/{run_id}/voiceover/{filename}`. Returns presigned PUT URL valid 10 min.
- `tests/test_runs.py`: `TestVoiceoverUploadUrl` — 4 tests. 286 total passing.
- No new ENV vars. No new pip dependencies.
- **Deployment prerequisite**: R2 bucket CORS must allow `PUT` from the Railway domain for browser direct-upload to work.
- E6-S3 (presigned upload URL) fully implemented inline — backend + UI both done.
**Promoted to backlog:** none

---

## [E1-S4] Run list and artifact retrieval endpoints
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/storage.py`: `R2Client.list_runs() → list[dict]` — scans `runs/` prefix, filters keys ending in `/run_log.json`, fetches each log, returns `[{run_id, created_at, steps: {step: status_str}}]` sorted by `created_at` descending. Empty bucket returns `[]`. `R2Client.generate_presigned_url(key, expires_in=3600) → str` — wraps boto3 `generate_presigned_url("get_object", Params={Bucket, Key}, ExpiresIn=expires_in)`.
- `src/models.py`: `RunSummary(run_id, created_at, steps: dict[str, str])`, `RunListResponse(runs: list[RunSummary])`, `ArtifactResponse(step, content_type, content=None, url=None)` added. `content` is `Optional[Any]` (JSON dict or text string depending on step).
- `src/routes/runs.py`: `GET /runs` → `RunListResponse` (500 on `StorageError`). `GET /runs/{run_id}/artifact/{step}` → `ArtifactResponse` (404 on `StorageError`, 422 for unrecognised step). `_STEP_ARTIFACT_KEYS` module-level dict maps step name → `(key_template, content_type)`. `_make_r2_client(settings)` helper DRYs up construction. The three JSON/text steps call `get_json`/`get_bytes`; the `render` step calls `generate_presigned_url`.
- Step → R2 key mapping: `storyboard` → `runs/{run_id}/storyboard.json`; `manifest` → `runs/{run_id}/asset_manifest.json`; `ffmpeg_script` → `runs/{run_id}/ffmpeg_script.sh`; `render` → `runs/{run_id}/output/final.mp4`.
- No new ENV vars. No new dependencies.
- 35 new tests (282 total passing). Smoke test deferred — GET /runs and GET /runs/{run_id}/artifact/{step} on DEV once a run with completed steps exists.
**Promoted to backlog:** none

---

## [E5-S1] FFmpeg execution and output upload
**Completed:** 2026-05-22
**Sprint:** unassigned
**Handover:**
- `src/renderer.py`: `render_run(run_id, manifest, storage, timeout_seconds) → dict` — full render orchestration. Always cleans up `/tmp/{run_id}/` in a `finally` block. Returns `{status, output_key, duration_seconds, exit_code}`. Raises `StorageError` on unexpected R2 failures (propagates to route as 500).
- Module-level helpers (importable and tested): `download_run_assets(run_id, manifest, storage)` — downloads all manifest `file_key` entries + `voiceover/`, `music/`, `sfx/` prefix files; `download_script(run_id, storage) → Path` — downloads `ffmpeg_script.sh`, makes executable; `execute_script(script_path, timeout_seconds) → CompletedProcess`; `upload_output(run_id, storage) → str` — uploads `/tmp/{run_id}/output/*` to R2, returns key for `final.mp4`, raises `RenderError` if absent; `cleanup(run_id)` — `shutil.rmtree` with `ignore_errors=True`; `_write_run_log_txt(run_id, content, storage)` — non-fatal, swallows `StorageError`.
- `src/routes/render.py`: `POST /runs/{run_id}/render` — reads `asset_manifest.json` from R2 (→ 404), calls `render_run`, updates run_log `complete`/`failed`. HTTP 200 for both outcomes; 500 on unexpected `StorageError`.
- `src/storage.py`: `R2Client.get_bytes(key) → bytes` and `R2Client.list_keys(prefix) → list[str]` added.
- `src/models.py`: `RenderResponse(status, output_key, duration_seconds, exit_code)` added.
- `src/exceptions.py`: `RenderError` added.
- `src/config.py`: `FFMPEG_TIMEOUT_SECONDS: int = 300` added (configurable via ENV).
- R2 key pattern: `runs/{run_id}/output/final.mp4`. Timeout (`subprocess.TimeoutExpired`) yields `exit_code=-1` and `status="failed"`.
- `tests/test_renderer.py`: 30 tests. 247 total passing.
- Smoke test deferred — POST to `/runs/{run_id}/render` on DEV once a run with completed storyboard + manifest + assets + ffmpeg_script exists; verify `final.mp4` in R2 console.
**Promoted to backlog:** none

---

## [E4-S1] FFmpeg script generator
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `build_ffmpeg_script(run_id, storyboard, manifest) → str` — pure function, no I/O. Raises `FFmpegBuildError` (with offending `scene_id`) if any manifest entry has `file_key=None`. Module-level helpers (importable, tested): `_local_path(run_id, file_key) → str` (R2 key → `/tmp/{run_id}/...`); `_zoompan_filter(clip_type, motion_effect, frames) → str`; `_parse_sfx_delay_ms(sfx_timing, duration_s, scene_offset_s) → int`.
- Generated script: `set -euo pipefail` → BASE/WORK vars → voiceover guard (`exit 1` if no `.mp3` in `$BASE/voiceover/`) → music check (anullsrc silence fallback via ffmpeg if absent, WARNING not error) → per-scene ffmpeg commands → concat list heredoc → concat command → audio assembly → done echo.
- Clip type handling: `hard_cut` → trim + `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`; `still_with_motion` → `-loop 1 -framerate 25`, source scaled 2160×3840, zoompan 1.0→1.05 centered; `animated` → zoompan 1.0→1.1 zoom_in/zoom_out or 1.1x pan_left/pan_right, driven by `motion_effect` field (unknown → zoom_in fallback).
- Audio: voiceover at 1.0, music at 0.15, SFX via `adelay={ms}|{ms}` per scene; `sfx="silence"` scenes skipped entirely; `amix=inputs=N:duration=first:normalize=0`.
- `src/routes/ffmpeg_script.py`: `POST /runs/{run_id}/ffmpeg-script` — sync; reads storyboard + manifest from R2 (→ 404), builds script (→ 422 + run_log `failed`), uploads via `storage.upload_text` (→ 500), updates run_log `complete`. Returns `FFmpegScriptResponse`.
- `src/models.py`: `FFmpegScriptResponse(status, script_key)` added.
- `src/exceptions.py`: `FFmpegBuildError` added.
- `src/storage.py`: `R2Client.upload_text(key, content, content_type)` added — UTF-8 encode + delegate to `upload_bytes`.
- R2 key: `runs/{run_id}/ffmpeg_script.sh`. No new ENV vars. No new dependencies.
- `tests/test_ffmpeg_builder.py`: 59 tests — unit for `_local_path`, `_parse_sfx_delay_ms`, `_zoompan_filter`, `build_ffmpeg_script`; 7 route integration tests. 217 total passing.
- Smoke test deferred — POST to `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed storyboard + manifest exists; inspect `ffmpeg_script.sh` in R2 console.
**Promoted to backlog:** none

---

## [E3-S3] Asset acquisition orchestrator
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/acquisition.py`: `MIN_ACQUIRED_FOR_COMPLETE = 1` at module level with explicit docstring — step is `complete` if ≥ 1 entry acquired after the loop, `failed` only when total acquired = 0. `acquire_scene(entry, run_id, pexels, replicate, storage) → bool` — single-entry fallback chain, mutates entry in-place; `PexelsError` treated same as `None` result (falls through to Replicate). `run_acquisition(run_id, manifest, pexels, replicate, storage) → dict` — full loop over manifest entries; skips `acquired` entries (idempotent); returns `{acquired: N, failed: N, sources: {pexels: N, replicate: N}}` where `acquired` is the total post-loop count including pre-existing acquired entries.
- `src/routes/assets.py`: `POST /runs/{run_id}/assets` — reads `runs/{run_id}/asset_manifest.json` from R2 (404 if missing), instantiates `PexelsClient` + `ReplicateClient` from settings, calls `run_acquisition`, uploads updated manifest back to same key, calls `update_run_log` with `complete`/`failed` + `output_url=manifest_key`. HTTP 200 for both complete and failed outcomes; 500 only on unexpected exception or R2 write failure.
- `src/models.py`: `AcquisitionResponse(status, acquired, failed, sources, manifest_key)` added.
- `src/main.py`: `assets_router` registered.
- R2 manifest key pattern: `runs/{run_id}/asset_manifest.json` (read and written back in-place with updated source/file_key/status fields).
- `tests/test_acquisition.py`: 18 tests — all passing. 158 total tests.
- No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

## [E3-S2] Replicate/Flux AI image generation fallback
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/replicate_client.py`: `ReplicateClient(api_token, model, poll_interval_seconds=3, max_poll_attempts=60)`. Key method: `acquire_for_entry(entry, run_id, storage) → ReplicateAcquireResult`. Submits prediction via `client.predictions.create(model=model, input={"prompt": ai_generate_prompt})`, polls `prediction.reload()` until terminal status or timeout, downloads image bytes from `str(output[0])`, uploads to `runs/{run_id}/images/{scene_id}.webp`. Always `.webp` — extension never inferred from CDN URL.
- `src/models.py`: `ReplicateAcquireResult(scene_id, source="replicate", file_key, status="acquired")` added (symmetric with `PexelsAcquireResult`).
- `src/exceptions.py`: `ReplicateError` added — raised on create failure, poll failure, `failed`/`canceled` prediction status, timeout, empty output, and download failure.
- All config vars pre-existing: `REPLICATE_API_TOKEN`, `REPLICATE_FLUX_MODEL`, `REPLICATE_POLL_INTERVAL_SECONDS`, `REPLICATE_MAX_POLL_ATTEMPTS`.
- No new dependencies (`replicate>=1.0.0` already in `requirements.txt` per D007).
- 140 total tests passing (19 new). End-to-end smoke test deferred to E3-S3 (requires orchestrator route).
**Promoted to backlog:** none

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
