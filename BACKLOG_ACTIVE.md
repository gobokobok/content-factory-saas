# Backlog — Active Stories (Sprints P5–P7)

_Contains current sprint (P5) + next two sprints (P6, P7). Full history in BACKLOG.md._
_Updated at each sprint boundary: move completed sprint block to BACKLOG.md archive._

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
- Control: `"continue"` if `best_overall_score / 10.0 >= quality_threshold`, else `"retry"`
- `quality_threshold` read via `getattr(state, "quality_threshold", 0.8)` — forward-compatible with `IdeaToScriptState.quality_threshold`
- No loop bookkeeping — worker never reads `state.iteration`
- Model: `claude-sonnet-4-6`, prompt_version v1, worker_version 1.0.0
- 17 tests in `tests/cf_platform/test_script_quality_scorer.py`; total suite 1120 passing

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
- `cf_platform/workers/script_refiner.py`: `build_script_refiner_worker(storage, anthropic_api_key) → WorkerNode`. Exports `ScriptRefinerArtifact` (actually returns `ScriptDraftsArtifact`), `SCRIPT_REFINER_REGISTRATION`.
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

## EPIC 31 — Orchestrator + Legacy Bridge (Sprint P6)
Parent graph chains the blocks + legacy render via the adapter; HITL gates (D047, D052).

---

## [P6-S1] Legacy adapter (interface + in-process impl)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** P5-S5

### Goal
`cf_platform/adapters/legacy_video.py`: `LegacyVideoAdapter` Protocol + in-process impl calling `src/pipeline.py` (script artifact → storyboard → assets → render → `final.mp4` in R2). **Only module importing `src/`** (D047). HTTP-swappable contract. Emits `trace_event`s (not artifacts of its own).
**Tech:** Python Protocol; `src/pipeline.py`; R2. **Artifacts:** `VideoResult`.

> **Spike finding (2026-06-13, during P0-S5):** `src/pipeline.py` exposes only `summarize_step()`. The alignment → render chain is frontend-driven REST (no server-side `run_full_pipeline()`). Adapter must either (a) add a chaining function to `src/`, or (b) chain existing per-step functions itself. Decide during this story's design.

### Acceptance Criteria
- [ ] Adapter produces `final.mp4` in R2 from a script artifact
- [ ] Only `legacy_video.py` imports `src/`; `src/` unchanged
- [ ] Legacy DEV/PROD pipeline still works independently

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P6-S2] Legacy-as-node + parent graph (+ PipelineState)
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** planned
**Priority:** high
**Points:** 5
**Depends on:** P6-S1

### Goal
Implement `PipelineState` (plan §5); wrap the adapter as a LangGraph node; compile `cf_platform/orchestrator/full_pipeline.py` composing `niche_to_ideas → idea_to_script → legacy_render`. One run threads run_id + artifacts end-to-end with full lineage; checkpointed.
**Tech:** LangGraph (subgraph composition, PostgresSaver), adapter. **Schema:** `PipelineState`.

### Acceptance Criteria
- [ ] Parent graph runs all three stages in one run
- [ ] Lineage spans new blocks + legacy node

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P6-S3] Human-in-the-loop gates
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** planned
**Priority:** med
**Points:** 3
**Depends on:** P6-S2, P2-S4

### Goal
LangGraph `interrupt` at script-approval (and optional idea-selection); resume via `POST /runs/{id}/resume {decision}`; Telegram approve/edit; configurable auto-approve timeout (default fully autonomous).
**Tech:** LangGraph interrupts, Telegram, Postgres checkpoints.

### Acceptance Criteria
- [ ] Run pauses at the gate and resumes on decision
- [ ] Timeout auto-approves per config

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P6-S4] End-to-end /produce → video
**Epic:** E31 — Orchestrator + Legacy Bridge
**Sprint:** P6
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** P6-S2

### Goal
Telegram `/produce <niche>` runs the whole chain; returns a presigned R2 URL for `final.mp4`. Capstone smoke test.
**Tech:** all of the above.

### Acceptance Criteria
- [ ] One command → finished video; lineage spans blocks + legacy
- [ ] **Human touchpoint:** operator runs `/produce <niche>` and downloads the video

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## EPIC 33 — Analytics & Attribution (Sprint P7)
Close the loop: which prompt/worker version → higher retention (D054).

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

## Post-MVP outlines (not yet detailed)

**EPIC 32 — Legacy Rebuild** (~3 sprints after P7): re-author Script→Video as native workers; retire `src/` + adapter.
**EPIC 34 — Replay & Evaluation Engine** (~3 sprints after P7): replay any worker, golden eval dataset, A/B routing, LLM-judge scoring.
