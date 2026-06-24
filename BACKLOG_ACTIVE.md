# Backlog — Active Stories (Sprints P8–P10)

_Contains completed sprint (P8), active sprint (P9), and next sprint outline (P10). Full history in BACKLOG.md._
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

## [P8-S7] LLM-vision media scorer — emotion, mood, relevance
**Epic:** E35 — Footage Quality
**Sprint:** P8 → DEFERRED to P10
**Status:** todo
**Priority:** med
**Points:** 3
**Depends on:** P8-S4

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

---

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
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** P9-S5

### Goal
Add a `--format portrait|landscape` flag to `/run`, `/produce`, and `/pick` Telegram commands so the operator can choose output orientation per video. Default stays `portrait` (1080×1920) for Shorts. `landscape` outputs 1920×1080 for standard YouTube uploads.

### Acceptance Criteria
- [ ] `parse_run_args`, `parse_produce_args`, `parse_pick_command` all parse `--format portrait|landscape`; unknown values fall back to `portrait` with a warning
- [ ] `PipelineState` gains `format_track: Literal["portrait","landscape"] = "portrait"`
- [ ] Storyboard prompt header line updated dynamically: `"30–60 second YouTube Short, 9:16 vertical"` when portrait; `"30–180 second YouTube video, 16:9 horizontal"` when landscape
- [ ] RenderWorker selects output resolution from `format_track`: 1080×1920 (portrait) or 1920×1080 (landscape); all intermediate ffmpeg steps use the correct `scale`/`crop` targets
- [ ] Telegram command usage strings updated to mention `--format`
- [ ] Tests: `parse_run_args`/`parse_produce_args`/`parse_pick_command` flag parsing (portrait, landscape, missing, invalid); `PipelineState` default; RenderWorker resolution selection

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** `/run housing --format landscape` → 1920×1080 `final.mp4` delivered via Telegram

---

## [P9-S7] Caption word assignment by timestamp (drop script text-matching)
**Epic:** E36 — Native Documentary Production Graph
**Sprint:** P9
**Status:** planned
**Priority:** high
**Points:** 1
**Depends on:** P9-S5

### Goal
Replace the text-matching approach in `assign_words_to_scenes` with timestamp-based assignment. Each Deepgram word is placed in whichever scene's time window contains its `start_ms`. This mirrors how CapCut generates captions — it shows what was actually said, not what the script says — eliminating dropped numbers and mismatched tokens (e.g. TTS says "three" but script has "3").

### Root cause
`assign_words_to_scenes` normalises VO tokens and scans forward through Deepgram words looking for text matches. When the TTS pronounces a numeral as a word ("three", "thirty") but the script contains the digit ("3", "30"), `_norm("3") != _norm("three")` — the word falls outside `_MATCH_WINDOW` and is silently dropped from captions.

### Acceptance Criteria
- [ ] `assign_words_to_scenes` in `src/ffmpeg_builder.py` rewritten: compute cumulative scene start times from `scene.duration_s`; for each Deepgram `WordTimestamp`, assign it to the scene whose `[start_s, end_s)` window contains `word.start_ms / 1000`; words before the first scene or after the last go to the nearest boundary scene
- [ ] Caption display text comes from `word.word` (Deepgram transcript), not from the script's voiceover_line
- [ ] `fill_caption_gaps` (if still needed) updated or removed — timestamp assignment leaves no gaps by construction
- [ ] All existing caption tests pass or are updated to reflect the new assignment logic
- [ ] No regressions in other callers of `assign_words_to_scenes` (`src/ffmpeg_builder.py`, `cf_platform/workers/render_worker.py`)

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] **Human touchpoint:** next full `/run` → captions show "3 and 4 percent" / "thirty years" without dropped words

---

## Post-P9 backlog (outline only)

| Sprint | Theme | Key stories |
|--------|-------|-------------|
| P10 | Render quality | Dip-to-black + chapter title cards between segment sections; xfade dissolves within same segment type; slow motion for Emotion scenes (`setpts=2.0*PTS`); per-clip `loudnorm` audio normalization; quote cards (full-frame `drawtext` for Data scenes); chart PNG generation (matplotlib → R2 → overlay) |
| P11 | AI asset library | `/library/` R2 cache layer (portrait + map + chart); portrait colorization via Real-ESRGAN + DeOldify (Replicate); background removal for parallax (rembg); map generation via Mapbox Static API (D entry required); number callout overlays (`drawtext` large-type stat highlight) |
| P12 | Format tracks | `format_track: Literal["documentary","educational","animated"]` at PipelineState level; `--format` flag in Telegram `/run`; per-track storyboard prompts (different segment_type mix); per-track render templates (different filter presets); animated track stub (returns error until P13–P14) |
| P13 | Analytics & attribution | Publish linkage capture; YouTube metrics ingestion; retention-by-prompt-version report |
| P14 | n8n automation | Callback webhook for n8n; YouTube OAuth upload; scheduled publication with operator preview |
| P15 | Multi-tenant SaaS frontend | Multi-channel per tenant; multi-run per channel; operator UI rebuild |

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

## Post-MVP outlines (not yet detailed)

**EPIC 32 — Legacy Rebuild** (~3 sprints after P7): re-author Script→Video as native workers; retire `src/` + adapter.
**EPIC 34 — Replay & Evaluation Engine** (~3 sprints after P7): replay any worker, golden eval dataset, A/B routing, LLM-judge scoring.
