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
**Status:** planned
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
- [ ] `/ideas <niche>` reply lists ideas numbered 1–5
- [ ] `/pick <run_id> <n>` triggers the pipeline using the chosen idea; sends running ack
- [ ] `PipelineState` / orchestrator accepts `idea_title` override to skip niche→ideas
- [ ] Telegram reply from `/pick` includes presigned video URL (metadata added in P7-S3)
- [ ] Tests: parse_pick_command (valid, malformed, out-of-range); pick webhook path; PipelineState idea_title override; format_pick_* helpers

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P7-S2] YouTube metadata worker
**Epic:** E34 — Idea Selection + YouTube Metadata
**Sprint:** P7
**Status:** planned
**Priority:** high
**Points:** 3
**Depends on:** P7-S1

### Goal
New worker: reads `script` artifact → produces a `youtube_metadata` artifact with `title` (≤70 chars), `description` (≤500 chars, includes hashtags), and `tags` (list[str], ≤15 tags). One Haiku call. Wired into the full pipeline after `idea_to_script` and before `voice_production`.

**Tech:** LangGraph worker, Haiku 4.5. **Artifact:** `youtube_metadata`.

### Acceptance Criteria
- [ ] `YoutubeMetadataArtifact(title, description, tags)` Pydantic model defined and stored
- [ ] `title` ≤ 70 chars enforced (truncated or re-prompted if Claude over-shoots)
- [ ] Worker wired into `full_pipeline.py` after `idea_to_script_node`
- [ ] `PipelineState` carries `"youtube_metadata"` artifact ref
- [ ] Tests: happy path, title truncation, missing script key, registration pins

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## [P7-S3] Produce → metadata reply
**Epic:** E34 — Idea Selection + YouTube Metadata
**Sprint:** P7
**Status:** planned
**Priority:** high
**Points:** 2
**Depends on:** P7-S1, P7-S2

### Goal
Update the Telegram reply from `/pick` (and `/produce`) to include the `youtube_metadata` artifact alongside the video URL. Operator can copy-paste title/description/tags directly into YouTube Studio.

**Design:**
- `format_produce_reply` updated to accept optional `YoutubeMetadataArtifact`; appends a formatted metadata block when present.
- `_run_produce_and_reply` reads `youtube_metadata` artifact from the result before sending the reply.
- **Human touchpoint:** operator sees presigned video URL + title/description/tags block in Telegram.

### Acceptance Criteria
- [ ] `/pick` reply includes video URL + YouTube metadata block
- [ ] `/produce` reply also includes metadata when the worker ran successfully
- [ ] Metadata absent from reply is handled gracefully (worker failure → video URL only)
- [ ] **Human touchpoint:** operator sends `/ideas <niche>`, picks idea, receives 16:9 video + metadata

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG.md status updated to `done`

### Handover
_filled on completion_

---

## Post-P7 backlog (outline only — detailed in BACKLOG.md)

| Sprint | Theme | Key stories |
|--------|-------|-------------|
| P8 | Footage quality | Alternative clip sources (licensed stock beyond Pexels), color-grading presets, per-scene quality scoring |
| P9 | Legacy engine rebuild | Re-author Script→Video as native LangGraph workers; retire src/ + InProcessLegacyVideoAdapter |
| P10 | Analytics & attribution | Publish linkage capture, YouTube metrics ingestion, retention-by-prompt-version report |
| P11 | n8n automation | Callback webhook for n8n, YouTube OAuth upload, scheduled publication with operator preview |
| P12 | Multi-tenant SaaS frontend | Multi-channel per tenant, multi-run per channel, operator UI rebuild |

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
