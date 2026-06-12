# Content Factory v2 — Platform Migration Plan

**Status:** approved (planning), 2026-06-12 · **Owner:** operator + Claude Code
**Scope:** introduce a versioned, observable, multi-agent platform layer **around** the existing Script→Video pipeline without breaking it, then progressively absorb the legacy pipeline into the same model.

> This document is the north-star spec for the v2 pivot. It is the single source of truth for the platform's **contracts** and **decisions**. Sprint/story bodies live in BACKLOG.md and SPRINT.md and **reference** this document for schemas. Specs are reviewed at the start of each sprint and story; adjustments are made then.

---

## 1. Goal & key insight

Evolve Content Factory from a single operator-driven pipeline into a **platform that can run multiple pipelines**:

```
Niche → Ideas → Script → Storyboard → Assets → Video → Analytics
```

The platform must be: modular (each stage independently callable), observable, **artifact-first**, and **versioned for analytics** — so we can later answer questions like *"which prompt_version produced higher-retention videos?"*.

We do **not** start a new project and we do **not** rewrite the legacy system. We add a bounded `cf_platform/` subsystem alongside the running `src/` pipeline, with strict one-way isolation, and migrate over time.

This destination was already committed in DECISIONS.md D041 (multi-agent target) and is enabled by D040 (pure async functions). v2 re-sequences the work to build the platform seam **now** and supersedes the orchestration choice (D042 Inngest → **D052 LangGraph**).

---

## 2. Macro architecture

```
            Control plane:  Telegram  ·  REST API  ·  (UI later)  ·  (Scheduler later)
                                        │
                                Platform orchestrator        (graph-of-graphs, P6)
                                        │
                                LangGraph execution layer     (stages = StateGraphs)
                                        │
                                Worker Registry + wrapper      (resolves version/model, logs lineage, emits artifact)
                                        │
              ┌─────────────────────────┴───────────────────────────┐
              ▼                                                       ▼
        Artifact store: Cloudflare R2        ←── refs ──→     Metadata store: Postgres
        (durable truth: every artifact)                      (queryable index: runs, artifacts,
                                                              worker_executions, trace_events,
                                                              published_videos, video_metrics)
                                        │
                                Analytics + learning loop      (P7 attribution, Epic 34 replay/eval)
```

Legacy is reached **only** through an adapter:

```
cf_platform/  ──►  cf_platform/adapters/legacy_video.py  ──►  src/ (Script→Video, UNTOUCHED)
```

`src/` never imports `cf_platform/`. This is the only allowed coupling and the seam that lets us rebuild legacy later (Epic 32) without touching the platform.

---

## 3. Architectural laws (non-negotiable, enforced in code review)

1. **Dependency direction is one-way.** `cf_platform → adapter → src`. Nothing in `src/` imports `cf_platform/`. (D047)
2. **Worker = Node.** A worker *is* a LangGraph node implementation. Hierarchy: **Worker → Node**, **Stage → StateGraph**, **Platform → Graph-of-graphs**. (D056)
3. **Workers are pure state-transformers.** Stateless, side-effect-free (D040 applies). Their only output is the returned `WorkerOutput`; the artifact is written by the **wrapper**, not the worker body. Exactly **one artifact per worker execution**.
4. **Artifacts are truth; state is a message bus.** Graph state carries only **artifact references** and **control signals** — never bodies, never a free-form mutation channel. The durable source of truth is the artifact in R2, indexed in Postgres. State must never become a second data store. (D057)
5. **Adapters are IO, not workers.** Source adapters and the legacy adapter emit **trace events** (observability), never artifacts. `adapter → trace_event`, `worker → artifact`. (D050, D057)
6. **Execution is a recorded function of its inputs.** `execution = f(prompt_version, model, inputs, sampling_params)`. All of these are pinned and recorded in lineage so run-to-run variance is attributable to LLM sampling alone (no seed on Claude — variance is bounded, not eliminated). (D055)
7. **P0 produces interfaces only.** Contracts, types, Protocols, decisions, docs, schema-validation tests. Zero runtime behavior. The moment something executes a node or writes to R2/Postgres, it is P1+.

---

## 4. Core contracts (universal) — implemented in **P0-S3** (interfaces only)

```python
# ── Lineage & artifacts ────────────────────────────────────────────────
class LineageEnvelope(BaseModel):
    run_id: str
    worker: str
    worker_version: str
    prompt_version: str
    model: str
    sampling_params: dict[str, Any] = {}     # temperature/top_p/top_k (D055)
    created_at: datetime

class Artifact(BaseModel):
    name: str                # e.g. "signals"
    stage: str               # e.g. "niche_to_ideas"
    version: int             # immutable; new write => version+1
    run_id: str
    content_type: str = "application/json"
    r2_key: str
    lineage: LineageEnvelope
    schema_version: str = "1"

# ── Run & execution records ────────────────────────────────────────────
class RunRecord(BaseModel):
    run_id: str
    user_id: str
    block: str               # which stage/graph this run belongs to
    status: Literal["created", "running", "complete", "failed"]
    inputs: dict[str, Any]
    error: str | None = None
    created_at: datetime
    updated_at: datetime

class WorkerExecution(BaseModel):
    run_id: str
    worker: str
    worker_version: str
    prompt_version: str
    model: str
    sampling_params: dict[str, Any] = {}
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    status: Literal["ok", "error"]
    artifact_r2_key: str | None = None
    started_at: datetime
    finished_at: datetime

# ── Worker / node contract (D056) ──────────────────────────────────────
ControlSignal = Literal["continue", "retry", "branch"]   # closed set; extend only by decision

class WorkerOutput(BaseModel):
    """Returned by a worker BODY. Pure — no storage knowledge.
    The wrapper persists `artifact` and produces the r2_key the worker cannot know."""
    artifact: BaseModel
    control: ControlSignal = "continue"

WorkerNode = Callable[["StageState"], Awaitable[WorkerOutput]]   # a worker IS this

# ── State base (D057): message bus, refs + control only ────────────────
def merge_refs(a: dict, b: dict) -> dict:
    return {**a, **b}

class StageState(BaseModel):
    run_id: str
    user_id: str
    inputs: dict[str, Any]
    artifacts: Annotated[dict[str, str], merge_refs] = {}   # stage_name -> r2_key (refs ONLY)
    # per-stage subclasses add typed control channels (e.g. iteration: int) — never a free dict

# ── IO adapters (NOT workers) ──────────────────────────────────────────
class TraceEvent(BaseModel):
    run_id: str
    worker: str              # the worker the adapter ran inside
    source: str              # e.g. "reddit", "google_trends", "legacy_video"
    op: str
    latency_ms: int
    cost_usd: float | None = None
    status: Literal["ok", "error"]
    meta: dict[str, Any] = {}

class SourceAdapter(Protocol):                # discovery IO (D050)
    async def fetch(self, niche: str, params: dict) -> list["Signal"]: ...
```

**Wrapper responsibility (Layer B, P1-S5).** Around every worker-node:
`resolve worker_version+prompt_version+model+sampling_params (registry)` → `out = await worker(state)` → `r2_key = artifact_manager.write(out.artifact)` → `record WorkerExecution(...)` → `return {"artifacts": {stage: r2_key}}` (reducer-merged). `out.control` routes the outgoing edge.

---

## 5. Per-stage StageState contracts (design locked now; implemented in their sprints)

**Which sprint owns each:**

| Contract | Designed (here) | Implemented in |
|---|---|---|
| `StageState` base + universal contracts | now | **P0-S3** |
| `NicheToIdeasState` | now | **P4-S4** |
| `IdeaToScriptState` | now | **P5-S5** |
| `PipelineState` | now | **P6-S2** |

```python
# Niche→Ideas (P4-S4). Sees: niche inputs + its own artifact refs. Never holds script data.
class NicheToIdeasState(StageState):
    mode: Literal["single", "top_n"] = "single"
    top_n: int = 3
    # artifacts populated across nodes:
    #   discovery        -> "signals"
    #   topic_generator  -> "candidate_topics"
    #   scoring          -> "scored_topics"
    #   selector         -> "ranked_ideas"   (terminal)

# Idea→Script (P5-S5). Loop bounded by the GRAPH, not the worker.
class IdeaToScriptState(StageState):
    iteration: int = 0                 # typed control channel; reducer increments
    max_iterations: int = 3
    quality_threshold: float = 0.8
    # artifacts:
    #   writer      -> "script_drafts"
    #   scorer      -> "script_scores"
    #   factcheck   -> "factcheck_report"
    #   (terminal)  -> "script"
    # control: scorer/factcheck return "retry" until iteration>=max OR score>=threshold

# Platform orchestrator (P6-S2). Composes subgraphs + legacy adapter node.
class PipelineState(StageState):
    hitl: bool = False                 # human-in-the-loop gates on/off
    # artifacts (terminal ref of each stage):
    #   niche_to_ideas  -> "ranked_ideas"
    #   idea_to_script  -> "script"
    #   legacy_render   -> "video"
    # interrupts: optional gate before idea_to_script (idea approval) and before render
```

Each stage may only read its `inputs` and its own `artifacts` refs. No cross-stage leakage — e.g. `NicheToIdeasState` never carries script content.

---

## 6. Data model

**Drafted DDL + queries (P0-S4):** `cf_platform/db/schema.sql` (full DDL with types, FKs, analytics indexes) and `cf_platform/db/queries.sql` (attribution query + supporting analytics queries). Design only — not applied by any code path until P2-S2. Migration tooling: raw SQL (D048).

### R2 — artifact store (durable truth)
Key scheme: `users/{user_id}/runs/{run_id}/{stage}/{name}@v{n}.json` (artifacts), `.../output/final.mp4` (media). Artifacts are **immutable**; a re-run writes a new version. R2 holds bodies; Postgres holds the queryable index pointing at these keys.

### Postgres — metadata index (queryable)
```sql
runs(run_id PK, user_id, block, status, inputs jsonb, error, created_at, updated_at)

artifacts(id PK, run_id FK, name, stage, version, r2_key, content_type,
          worker, worker_version, prompt_version, model, created_at)

worker_executions(id PK, run_id FK, worker, worker_version, prompt_version, model,
          sampling_params jsonb, input_tokens, output_tokens, cost_usd, latency_ms,
          status, artifact_r2_key, started_at, finished_at)

trace_events(id PK, run_id FK, worker, source, op,
          latency_ms, cost_usd, status, meta jsonb, created_at)        -- adapters

published_videos(id PK, run_id FK, platform, external_id, url, published_at)  -- P7
video_metrics(id PK, external_id, platform, metric, value, captured_at)       -- P7

-- indexes: worker_executions(prompt_version),(worker_version),(run_id);
--          artifacts(run_id),(prompt_version); trace_events(run_id),(source);
--          published_videos(external_id),(run_id); video_metrics(external_id, captured_at)
```

Record hierarchy: `run → worker_executions → trace_events`. One worker execution emits **one** artifact and **N** trace events (e.g. 3 source fetches).

### Attribution query (proves the analytics joins; P7-S3)
```sql
SELECT we.prompt_version, AVG(vm.value) AS avg_retention, COUNT(*) AS n
FROM video_metrics vm
JOIN published_videos pv ON pv.external_id = vm.external_id
JOIN runs r               ON r.run_id      = pv.run_id
JOIN worker_executions we ON we.run_id     = r.run_id AND we.worker = 'storyboard'
WHERE vm.metric = 'average_view_percentage'
GROUP BY we.prompt_version
ORDER BY avg_retention DESC;
```

### Block artifact shapes (JSON payloads)
```
signals          { niche, generated_at, signals:[{source,text,metric,score,url?}] }
candidate_topics { topics:[{id,title,angle,source_signal_ids}] }
scored_topics    { topics:[{id,title,scores:{novelty,audience_relevance,emotional_trigger,
                            search_demand,competition,evergreen_potential,
                            monetization_relevance,final_score}}] }
ranked_ideas     { selected:{...}, alternatives:[...], mode }
script_drafts / script_scores / factcheck_report / script
```

---

## 7. Decisions (full text in DECISIONS.md)

| # | Decision |
|---|---|
| D047 | Isolate legacy by **wrapping** (adapter interface), not moving; in-process impl now, HTTP/separate-service swap later |
| D048 | Postgres as metadata index — **required + early**, analytics-shaped (lineage as columns); R2 stays blob truth |
| D049 | Telegram trigger via `httpx` (no SDK); **interfaces emit only via a formatter** — never serialize internal schemas to chat |
| D050 | Discovery sources via a `SourceAdapter` Protocol (Reddit + Google Trends + YouTube now; X/others later via Apify); adapters emit trace events |
| D051 | Worker/lineage envelope (run_id, worker, worker_version, prompt_version, model, sampling_params, tokens, cost, latency, status) |
| D052 | **LangGraph** as orchestration/agent engine + Postgres checkpointer — **supersedes D042 (Inngest)**; keep `anthropic` SDK + `ModelRouter` inside nodes |
| D053 | Web-search tool for the Idea→Script fact-check loop (provider TBD at P5) |
| D054 | YouTube Analytics OAuth + scheduler for metrics ingestion (P7) |
| D055 | Replay-ready constraints: artifacts immutable, prompts version-pinned, `execution = f(prompt_version, model, inputs, sampling_params)` — enables Epic 34 |
| D056 | LangGraph abstraction model: **Worker = Node**, Stage = StateGraph, Platform = Graph-of-graphs; worker invariants |
| D057 | **Artifacts are truth; state is a message bus** (refs + control only; never a second data store) |

---

## 8. Sprint roadmap (P0 → P7) + post-MVP epics

| Sprint | Theme | Pts | Depends on | Human touchpoint |
|---|---|---|---|---|
| **P0** | Boundary design & contracts (interfaces only) | 13 | — | Operator approves spec + schemas |
| **P1** | Platform skeleton & core (LangGraph-aware) | 16 | P0 | `POST /platform/echo` → run_id + artifact in R2 |
| **P2** | Lineage & observability store (Postgres) | 16 | P1 | Inspect per-worker cost/latency/version; graph resumes after restart |
| **P3** | Telegram trigger + Discovery worker | 10 | P1, P2 | `/ideas <niche>` → signals summary in Telegram |
| **P4** | Niche→Ideas block complete | 13 | P3 | Telegram niche → ranked ideas w/ 7-axis scores |
| **P5** | Idea→Script block | 16 | P4 (soft) | Telegram idea → fact-checked script |
| **P6** | Orchestrator + legacy bridge | 13 | P4, P5 | One Telegram command → finished video via legacy |
| **P7** | Analytics & attribution (Epic 33) | 11 | P2, P6 | Report ranking prompt versions by retention |

Platform MVP (P0–P6) = **97 pts**; with analytics (P7) = **108 pts**.

- **Epic 32 — Legacy Rebuild** (post-P7, ~3 sprints): re-author Script→Video as native LangGraph blocks/workers, reach parity, retire `src/` + adapter.
- **Epic 34 — Replay & Evaluation Engine** (post-P7, ~3 sprints, ~30 pts): replay primitive, golden dataset, LLM-judge comparison, A/B routing, eval leaderboard. Turns passive analytics into active behavioral evolution.

**Critical path:** `P0 → P1 → P2 → P3 → P4 → P6 → P7` (P5 hangs off P4 for the chain; buildable in parallel after P2 with a manual topic input).

### Sequencing watch-outs
1. **P1-S4/S5 (LangGraph engine + observability wrapper) is the keystone** — spike before committing.
2. **P2 must precede P3** so discovery runs have persisted lineage from run #1.
3. **HITL (P6-S3) depends on the PostgresSaver checkpointer (P2-S4)** — interrupts must be durable.
4. ~~**Adapter (P6-S1) assumes `src/pipeline.py` exposes a clean full-run entry** — confirm its signature in P0.~~ **Confirmed false (2026-06-13, P0-S5 spike):** `src/pipeline.py` only contains `summarize_step()`; no full-run entry exists — the chain is currently frontend-driven. P6-S1 must add a chaining function in `src/` or chain the per-step domain functions itself (see P6-S1 backlog note).
5. **P7-S1 introduces an operator habit** (record the published video URL) until a publish agent exists.

---

## 9. Migration arc

```
Now      legacy monolith in src/   (running in DEV + PROD)
P0–P6    cf_platform/ added · new blocks = LangGraph graphs · legacy called via adapter
P7       analytics loop closed (retention → prompt_version)
Epic 32  re-author Script→Video AS LangGraph blocks/workers → parity → retire src/ + adapter
Epic 34  replay & evaluation → active, measurable behavioral evolution
End      one uniform platform: every stage is a graph of versioned workers
```

Relationship to the existing roadmap: Sprints **S14–S17** (video-UX polish) are **paused** — they resume later behind the adapter as "legacy pipeline UX." S18 (API) concepts and S19's `users/{user_id}/…` key scheme are pulled **forward** into the platform foundation.

---

## 10. New dependencies (each needs a DECISIONS entry before `requirements.txt`)

| Sprint | Dependency | Decision |
|---|---|---|
| P1 | `langgraph` | D052 |
| P2 | `psycopg`, `langgraph-checkpoint-postgres`, Railway Postgres | D048 / D052 |
| P3 | Telegram (httpx); optionally `praw`/`pytrends` | D049 / D050 |
| P5 | web-search tool | D053 |
| P7 | YouTube Analytics OAuth client + scheduler | D054 |

Keep `anthropic` SDK + `ModelRouter` inside LangGraph nodes — do **not** adopt `langchain-anthropic` (preserves cost lineage, minimizes dep surface).

---

## 11. Platform MVP — definition of done

- A single Telegram command (`/produce <niche>`) runs **Niche→Ideas → Idea→Script → legacy render** and returns a downloadable video.
- Every worker execution is recorded in Postgres with full lineage (worker/prompt/model/sampling_params/cost/latency) and points at an immutable R2 artifact.
- Every run is resumable after a Railway restart (Postgres checkpointer).
- Legacy DEV/PROD pipeline is **unchanged** and still operable independently.
- The attribution query returns retention grouped by `prompt_version` once videos are published and metrics ingested.

---

## 12. Working agreement

Specs in this document and in BACKLOG.md/SPRINT.md are **reviewed at the start of each sprint and each story**, and adjusted if relevant. This plan preserves the decisions of the 2026-06-12 planning session; it is expected to evolve as implementation reveals detail.
