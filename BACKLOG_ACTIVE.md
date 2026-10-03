# Backlog — Active Stories

_Contains the next sprint (P13), the last completed sprint (P12), the outlines for P13b–P17, and open unassigned stories. Everything older is in BACKLOG.md._
_Updated at each sprint boundary: move the completed sprint's block to BACKLOG.md._

---

## Platform Update outlines — Sprints P13b–P17 (not yet detailed)

Detailed at each sprint boundary. Spec section numbers refer to the Pipeline & Platform Update specification (2026-10-03).

**EPIC 44 — Storyboard control (P13)** — detailed: see the EPIC 44 section below. Open for P13b: whether split / merge and asset strategy need anything extra in the CapCut timeline file.

**EPIC 49 — CapCut export (P13b, D100).** Second render path from a finalized storyboard; FFmpeg on Railway is unchanged. (1) A neutral timeline artifact — scenes, timing, asset per scene, motion, on-screen text, caption words, voiceover, music, SFX — that the FFmpeg script builder and the CapCut script both read. (2) "Download for CapCut" in Studio: a zip of the run's media plus the timeline file. (3) Laptop script (own requirements file with `pycapcut`; not in the platform image) that unpacks the zip and writes the CapCut project, with a one-time setup guide; starts from `tools/capcut_spike/`. (4) Return path: upload the CapCut-rendered video into the run so metadata and publishing continue. Still to test beyond the spike: music and SFX tracks, video clips (the spike run was stills only), 16:9, and which of `draft_content.json` / `draft_info.json` CapCut 8.x reads. Open: pin a CapCut version or detect format breaks; whether storyboard changes from P13 (split/merge, asset type) need anything extra in the timeline file.

**EPIC 45 — AI Created style (P14, D096, spec §8, 11, 12).** Opens with the side-by-side provider test from D096. `ImageProvider` interface, kie.ai implementation, generated images stored in the run's R2 folder. New style option with a general visual prompt / mood in Settings. Visual Director prompt branch: for this style it writes a per-scene visual prompt from the scene's voiceover plus the global mood, instead of stock keywords. Per-scene "AI image" option with an editable prompt, usable in any style. Open: keeping a consistent look across scenes (style reference image vs. prompt only); per-run spend cap.

**EPIC 46 — Research (P15, D094, D097, spec §2–5).** Project research page. Trend research: existing Google Trends, Reddit and YouTube adapters (D050) plus Google News, over a chosen time window, producing ~10 topics each with a summary and the evidence for why it is trending. Competitor research: port from `content-researcher` (D097), project-level channel list, publications from the last 24/48 hours with likes per 1,000 views and outlier score, daily snapshot job. Results are ticked into the shortlist with their evidence. Open: orchestrator-with-specialists vs. parallel agents with a synthesis step (spec §26 D); **X.com** — ENV.md records it as excluded under the free-tier constraint, so including it needs a decision on a paid source.

**EPIC 47 — Publishing via n8n (P16, D098, spec §18–21).** `channels` table (tenant level: name, platform, n8n channel key), project default channel, per-run destinations with publish time. Endpoints `due` / `claim` / `result`; API key for n8n. n8n workflow for YouTube (upload early with YouTube's own scheduled-publish time), exported JSON committed to the repo. Publication status in Studio's Metadata stage, replacing the disabled "Upload to channel" button; fills `published_videos`. Instagram as a second destination if time allows. Depends on the Google API audit started in P12.

**EPIC 48 — Server-side Auto Advance (P17, spec §22).** The Studio toggle hands the run to the server-side pipeline (`full_pipeline.py`, HITL gates from P6-S3) so it continues with the browser closed. First task: confirm that pipeline writes the same artifacts in the same places as the stage-by-stage Studio flow, so an auto-advanced run opens cleanly for review. Define which stages may run unattended, where it stops on error or missing input, and add OpenAI direct as the image fallback (D096). Optional: one-way Telegram notifications (D093).

**Parked by D099:** P11-S2 motion presets (EPIC 39), P11-S3 sub-scene asset timeline (EPIC 38), Format tracks, Analytics & attribution.

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
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
Each scene carries an operator-editable asset strategy — stock image, stock video, or upload — that is set before acquisition and that acquisition obeys. Without an explicit choice, behaviour is exactly as today.

### Acceptance Criteria
- [ ] `StoryboardScene` gains `asset_strategy: Literal["stock_image", "stock_video", "upload"] | None = None`; `None` means "derive from `asset_tier` as today". The vocabulary lives in one constant so P14 can add `ai_image`
- [ ] `asset_strategy` is in `_PATCHABLE_FIELDS` and validated in `PATCH /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}`; an unknown value is rejected with 422
- [ ] The storyboard GET returns, for every scene, the effective strategy (the explicit one, or the one derived from `asset_tier`) so the UI never has to re-derive it
- [ ] AcquisitionWorker: `stock_image` forces the photo path and `stock_video` the video path, regardless of `asset_tier` / `clip_type`; the render script treats the scene accordingly (a still gets its motion effect, a video does not)
- [ ] `upload` scenes are skipped by acquisition and reported as "awaiting upload" in the manifest and `footage_summary`; the existing per-scene upload endpoint fills them; render is refused with a clear message while any upload scene has no file
- [ ] Changing a still scene to video (or back) resets `motion_effect` to the correct default via `normalize_motion_effect`
- [ ] **Confirm at the start of the story:** whether the Studio stage-by-stage flow runs the Visual Director at all — it is only referenced from `full_pipeline.py`, not from the worker routes. Record the finding in the Handover; wiring it in is out of scope unless the strategy cannot work without it
- [ ] **No regression:** a storyboard with no `asset_strategy` on any scene produces a byte-identical manifest request and render script before and after
- [ ] Tests: patch accept/reject; each strategy's acquisition path; upload scene skipped and blocking render; legacy storyboard unchanged

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — `_assign_asset_tier`, `_asset_tier_to_clip_type`, `_patch_storyboard` / `_PATCHABLE_FIELDS`
- `cf_platform/workers/acquisition_worker.py` — the `asset_tier` / `clip_type` branch (two places), `visual_treatment` loading
- `cf_platform/interfaces/routes/studio.py` — scene PATCH, `reacquire`, `upload`
- `src/models.py` — `StoryboardScene`, `ManifestEntry`, `normalize_motion_effect`
- `cf_platform/models/visual_treatment.py` — `SceneVisualPlan.asset_class` / `preferred_source`
- `DECISIONS.md` — D095, D081, D089

### Handover
_filled on completion_

---

## [P13-S2] Split and merge scenes
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** planned
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
The operator can split one scene into two at a word, and merge a scene with the next one. Boundaries move as word indices; durations and overlay timing are recomputed from the Deepgram timestamps.

### Acceptance Criteria
- [ ] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/split {at_word}` — `at_word` becomes the first word of the new second scene; rejected with 422 unless `start_word < at_word <= end_word`
- [ ] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/merge` — merges the scene with the one after it; rejected with 409 on the last scene
- [ ] After either operation the storyboard is still contiguous (first `start_word` = 0, last `end_word` = N−1, no gaps), scene ids are renumbered in order, and `voiceover_line`, `scene_start_ms` / `scene_end_ms`, `duration_s` and `asset_tier` are recomputed from the word timestamps by the same code the StoryboardWorker uses
- [ ] Split: the first half keeps every field of the original scene; the second half copies the visual fields (search terms, segment type, asset strategy) and starts with no on-screen text and no SFX
- [ ] Merge: the first scene's fields win; the second scene's on-screen text and SFX are dropped, and the response says so
- [ ] `render_options` for all scenes are rebuilt through `_patch_storyboard`; a new storyboard artifact version is written
- [ ] **Already-acquired assets (operator decision):** on split, the first half keeps the asset and the second half is marked as needing acquisition; on merge, the merged scene keeps the first scene's asset and the second scene's manifest entry is removed. The manifest stays aligned with the renumbered scenes, and a later "Acquire Assets" fetches only the scenes that need one
- [ ] A split that would create a scene shorter than the minimum scene duration is rejected with a clear message
- [ ] Voiceover text is not editable through these endpoints
- [ ] Tests: split and merge happy paths; boundary validation; contiguity and timing after a sequence of splits and merges; manifest alignment with and without acquired assets

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — the scene-from-word-span builder (around `start_word` / `end_word` clamping), the long-scene splitter, the contiguity enforcement, `_patch_storyboard`
- `cf_platform/interfaces/routes/studio.py` — scene PATCH (how a new artifact version is written), manifest GET
- `cf_platform/workers/render_worker.py` — "live start_word boundaries" block
- `tests/cf_platform/test_p9_s9_timestamp_storyboard.py`, `tests/cf_platform/test_p10_s2_asset_override.py`
- `DECISIONS.md` — D095, D086

### Handover
_filled on completion_

---

## [P13-S3] Storyboard stage — strategy dropdown, split / merge controls, confirm gate
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** P13-S1, P13-S2

### Goal
The Storyboard table in Studio exposes the new controls, and acquisition starts only when the operator confirms the storyboard.

### Acceptance Criteria
- [ ] New "Asset" column: a `.cf-select--sm` dropdown per scene with Stock image / Stock video / Upload, showing the effective strategy; changing it calls the scene PATCH and re-renders the row (the Motion cell follows: dropdown for stills, `—` for video)
- [ ] An "Upload" scene shows an upload control in its row before acquisition, using the existing per-scene upload endpoint
- [ ] Split: clicking a word in a scene's voiceover text offers "Split here"; Merge: each row except the last has "Merge with next". Both re-render the table from the response
- [ ] A merge that drops on-screen text or SFX asks for confirmation first
- [ ] The acquire button reads "Confirm storyboard & acquire"; nothing is acquired before it is pressed when Auto Advance is off. With Auto Advance on, acquisition starts without the gate (D095)
- [ ] After acquisition, scenes that need an asset (a split's second half, an unfilled upload) are visibly marked, and the button acquires only those
- [ ] Row height and table width stay as they are at 1280px; no console errors
- [ ] Tests: static-page test pins the new controls and the routes they call
- [ ] **Human touchpoint:** on DEV, the operator changes a scene from image to video, splits one scene and merges two, confirms and acquires, then swaps one scene's asset with the pencil — the last step clears the **P10-S2** deferred smoke test

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `src/static/studio-v2.html` — `renderStoryboard`, `patchScene`, `acquireAssets`, the auto-advance block in `renderStageTrack`
- `docs/UI_GUIDELINES.md#principles`, `docs/UI_GUIDELINES.md#step-status-display`
- `tests/cf_platform/test_p12_s2_pages.py` (pattern for static-page tests), `tests/cf_platform/test_pux2_s3_motion.py`

### Handover
_filled on completion_

---

## [P13-S4] Script view — edit scene boundaries as text
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** planned
**Priority:** med
**Points:** 3
**Depends on:** P13-S2

### Goal
A second view of the Storyboard stage shows the whole voiceover as text, with a blank line between scenes. The operator moves the blank lines to move the boundaries and applies the result in one step.

### Acceptance Criteria
- [ ] Toggle in the Storyboard stage: Table / Script. Script view shows each scene's words as a paragraph, paragraphs separated by one blank line
- [ ] `PUT /platform/studio/runs/{run_id}/storyboard/boundaries {start_words: [...]}` replaces all scene boundaries at once; validated (starts at 0, strictly increasing, within range, minimum scene duration) and applied through the same recompute path as split / merge
- [ ] A scene whose `start_word` is unchanged keeps its fields and its asset; a new scene inherits the visual fields of the scene it was cut from; assets follow the same rule as P13-S2
- [ ] **Words cannot be changed.** If the text differs from the voiceover by anything other than paragraph breaks, Apply is disabled and the message says to change the text in the Script stage (it forces re-voicing)
- [ ] Apply shows what will change ("12 scenes → 14; 3 scenes need acquisition") before writing
- [ ] Tests: boundary replace happy path; each validation failure; unchanged scenes keep fields and assets; changed-words rejection

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P13-S2 Handover (the recompute helper this story reuses)
- `src/static/studio-v2.html` — `renderStoryboard`
- `cf_platform/interfaces/routes/studio.py` — storyboard GET, voice GET (word list)

### Handover
_filled on completion_

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

## Unassigned backlog

Open stories that belong to no sprint in the current roadmap (D099).

---

## [P8-S7] LLM-vision media scorer — emotion, mood, relevance
**Epic:** E35 — Footage Quality
**Sprint:** unassigned — deferred from P8 to P10, never picked up; not in the D099 roadmap
**Status:** backlog
**Priority:** low
**Points:** 3
**Depends on:** P8-S4

> **Groomed 2026-10-03:** priority med → low. Since this was written, P10-S3 (semantic enrichment + Entity Resolver) and P11-S1 (Visual Director) took over asset relevance, P13 puts the asset choice in the operator's hands, and P14 generates images outright. Revisit only if stock relevance is still a complaint after P14.

### Goal
Replace the metadata-only (resolution) ranking used in P8-S1 with a multimodal LLM evaluation that scores each candidate asset against the scene's `visual_description` on axes that can't be inferred from resolution alone: emotional tone, visual mood, subject relevance, and production quality. One Haiku vision call per candidate evaluated. Returns a numeric score (0.0–1.0); the acquisition loop picks the highest-scoring candidate that also passes the P8-S4 resolution + duration gate.

### Scorer axes (prompt → structured JSON)
| Axis | Weight | Description |
|------|--------|-------------|
| `relevance` | 0.4 | Does the image depict the described subject? |
| `emotional_tone` | 0.3 | Does the mood/feel match the scene intent? |
| `visual_quality` | 0.2 | Professional composition, lighting, not amateur/stock-cliché |
| `diversity` | 0.1 | Penalise if visually similar to already-selected scenes in this run |

### Module contract (`src/media_scorer.py`)
```python
async def score_candidate(
    image_url: str,
    scene_description: str,
    selected_scene_descriptions: list[str],
    anthropic_api_key: str,
    model: str = "claude-haiku-4-5",
) -> MediaScore

# MediaScore: relevance, emotional_tone, visual_quality, diversity, total, passed (total >= 0.60)
```

### Integration point
Plug into `acquire_scene` after resolution gate (P8-S4 hook point): for each resolution-passing candidate, call `score_candidate`; take the highest-scoring one. If none pass the `0.60` threshold, fall back to best-resolution candidate (never leave scene empty).

### Acceptance Criteria
- [ ] `src/media_scorer.py`: `score_candidate` — downloads image, sends to Claude vision, returns `MediaScore`
- [ ] Integrated into acquisition loop after P8-S4 resolution gate; highest-scoring candidate wins
- [ ] `MEDIA_SCORER_ENABLED: bool = False` in `src/config.py` + `ENV.md` (off by default — Haiku vision call adds ~$0.003/scene)
- [ ] `asset_manifest.json`: `qa_vision_score` + `qa_vision_axes` fields per scene when scorer enabled
- [ ] Scorer disabled → resolution-ranked winner selected (P8-S1 behaviour preserved)
- [ ] Tests: happy path (mocked Claude vision); low score → skip to next candidate; scorer disabled → skipped; diversity penalty applied

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
