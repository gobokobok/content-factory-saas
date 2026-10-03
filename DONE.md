# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last two sprints (P13, P12) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P13] Storyboard control — S1 asset strategy, S2 split / merge, S3 Storyboard stage controls + confirm gate, S4 script view
**Completed:** 2026-10-03
**Handover:**
- **The storyboard is the gate (D095).** Each scene carries `asset_strategy` (`stock_image` / `stock_video` / `upload`, or `None` = derive from `asset_tier` as before). The vocabulary is one Literal in `src/models.py` (`AssetStrategy` → `ASSET_STRATEGIES`) — P14 adds `ai_image` there. The storyboard GET returns `effective_asset_strategy` per scene.
- **Acquisition obeys it.** `stock_video` goes straight to the stock video search (even on Character / Event scenes); `upload` scenes are never fetched — they keep an uploaded file or are reported as `awaiting_upload` (manifest status, and `footage_summary` only when non-zero). `POST /platform/workers/acquisition {only_missing}` keeps every scene that already holds an asset. `build_manifest_artifact` is the one place that counts acquired / failed.
- **Boundary edits** live in `cf_platform/workers/storyboard_edit.py`: `replace_boundaries` (plus `split_scene`, `merge_scene`, `start_words_from_text`). One rule — unchanged start word keeps fields and asset; a new start word is cut from the scene that contained it; a vanished start word is merged away (D102). Routes: `POST …/storyboard/scenes/{id}/split {at_word}`, `POST …/scenes/{id}/merge`, `PUT …/storyboard/boundaries {start_words | script_text, dry_run}`. Each writes a new storyboard version and, when the run has a manifest, a realigned manifest version.
- **Scene ids are renumbered by edits; asset files are not moved.** `ManifestEntry.asset_slot` (and a hash suffix on uploads) keeps a new file from overwriting one another scene still uses. Anything that writes a scene asset must go through `_asset_stem(entry)` / `assign_free_asset_slot` — P13b's CapCut export should read `file_key`, never rebuild a path from the scene id.
- **Render** is refused up front (409 from the endpoint, `RuntimeError` in the worker) while any scene has no file: `render_worker.missing_assets_message`.
- **The upload endpoint starts a manifest** from the storyboard when the run has none, so a manifest can now exist before acquisition with `pending` entries.
- **Studio:** Asset dropdown (replaces the image / video badge), word-click split, `⤵` merge, row upload, "needs asset" marking, `acquirePlan()` deciding the button ("Confirm storyboard & acquire →" / "Acquire N missing scenes →" / "Re-acquire All"), Table / Script toggle. Demo mode mocks all of it.
- **Visual Director is not run by the Studio stage-by-stage flow** — only by `full_pipeline.py`. Relevant to P14 (its prompt branch) and P17.
- New ENV var: `STORYBOARD_MIN_SCENE_S` (default 1.0). No new dependencies. Tests: 134 new (`test_p13_s1_asset_strategy.py`, `test_p13_s2_split_merge.py`, `test_p13_s3_storyboard_stage.py`, `test_p13_s4_boundaries.py`, helper `p13_helpers.py`). 2435 passing.
- Decision logged: **D102**.
**Smoke test:** PASSED — 2026-10-03 on Railway DEV (`1e5ff4b`), operator ran all 17 steps: gate before acquisition, image ↔ video with Motion following, split with the minimum-length rejection, merge with the dropped-text confirmation, upload at the gate, render refused for an empty Upload scene, only-missing acquisition after a split with every other asset untouched, Script view apply and changed-word block, pencil re-acquire and upload, final render.
**Promoted to backlog:** none. Noted for later, not a story yet: `render_worker`'s live-boundary block indexes raw alignment words while scene indices refer to the normalised list.

---

## [P12] Projects & Shortlist — S1 data model + API, S2 project landing + server-side run list, S3 persistent shortlist, S4 runs from shortlist items
**Completed:** 2026-10-03
**Handover:**
- **Hierarchy (D092):** Tenant → Project → Run. Migration `0002_projects_shortlist.sql` adds `projects`, `shortlist_items`, `run_shortlist_items`; `runs` gains `tenant_id`, `project_id` (NOT NULL, default `'default'`), `name`, `archived_at`. `tenant_id` is `PLATFORM_USER_ID` everywhere; there is still no multi-tenant auth.
- **Every run has a row now.** Before P12 a Studio run started from a pasted script had none (ids were minted in the browser). Runs are created by `POST /platform/projects/{id}/runs {item_ids}`; `create_run` defaults every other caller (Telegram, block routes) to the default project. Pre-P12 runs: the migration backfills rows that exist, and `POST /platform/projects/default/runs/import` registers browser-only runs the first time that browser opens `/` or the run's link.
- **Modules:** `cf_platform/core/projects.py` (`Project`, `create_project`, `update_project`), `cf_platform/core/shortlist.py` (`ShortlistItem`, `add_manual_item`, `remove_item`, `resolve_items_for_run`, `build_idea_context`), `cf_platform/core/postgres_project_repos.py`, `cf_platform/core/run_manager.py` (`register_existing_run`, `archive_run`, `RunRepository.list_for_project` / `count_by_project`). In-memory fallbacks exist for all of them (no `DATABASE_URL` → still works, not durable).
- **Routes** (`cf_platform/interfaces/routes/projects.py`): project CRUD, project-scoped run list / create / import / archive, shortlist list / add / read-one / soft-remove, and `GET /platform/studio/runs/{run_id}/context`. The shortlist has no bulk replace or clear, and a test pins its surface to those four operations (D094) — P15 research must add items one at a time through the repository's `add`.
- **`POST /platform/blocks/idea-to-script` takes an optional `run_id`** and generates into that run (same id, project niche when none is sent, fresh checkpoint thread per generation, run left `running` rather than `complete`). Without it, behaviour is unchanged.
- **Pages:** `/` → `projects.html`, `/project?id=` → `project.html`, `/studio#run/<id>/<stage>` → `studio-v2.html`. Studio no longer reads or writes `localStorage.studio_runs`; a run with no shortlist item cannot be created (Studio's "New run" goes to the project page).
- **Project defaults:** `project.config.run_defaults` uses the same keys as a run's `settings.json`; Studio seeds a just-created run from it once and never writes back to the project.
- **Known limits:** run status in the project list is the row's lifecycle (`created` / `running`), not per-stage pipeline progress — no Studio stage writes to the row. P17 (server-side Auto Advance) is the natural place to fix that.
- No new ENV vars, no new dependencies. Tests: 75 new (`test_p12_s1_projects.py`, `test_p12_s3_shortlist.py`, `test_p12_s4_runs_from_shortlist.py`, `test_p12_s2_pages.py`) plus `tests/integration/test_p12_migration_postgres.py` (real Postgres, excluded from CI; run with `CF_TEST_DATABASE_URL`). 2301 passing.
- Decision logged: **D101** (runs carry `name` + `archived_at`; idea-to-script generates into an existing run).
**Smoke test:** PASSED — 2026-10-03 on Railway DEV (`f00eefe`), operator ran all 16 steps: project list with pre-P12 runs imported into "Default project", new project + defaults, two hand-added ideas, a run from one idea and from two, script generated into the run without the run id changing, full pipeline to a rendered video, run deletion, soft-removed idea still listed on its run, same list in a second browser, phone layout.
**Promoted to backlog:** none. Operator action in progress: Google API audit application (lead time for P16) — operator will submit.
