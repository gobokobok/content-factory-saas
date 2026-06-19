# Architecture & Dependency Decisions

All significant architecture decisions and new dependency introductions are logged here.
**Rule:** No new dependency may be added to `requirements.txt` without a corresponding entry in this file.

---

## D062 — voice_production as a platform worker (not a legacy bridge call)
**Date:** 2026-06-19
**Status:** ACTIVE
**Decision:** TTS + alignment lives in `cf_platform/workers/voice_production.py` — a first-class platform worker — rather than inside `InProcessLegacyVideoAdapter.render()` or as a call through `src/tts.py`. The adapter only receives the finished `VoiceAlignmentArtifact` (mp3 R2 key + word timestamps) and uses it for scene timing and caption sync. The voice_production worker uses httpx/google-generativeai directly without importing `src/` (D047).
**Rationale:** Putting TTS inside the adapter would make it untestable in isolation (adapter calls require the full legacy chain: storyboard → manifest → acquisition → ffmpeg → render). As a platform worker, voice_production can be triggered standalone via `/testvoice`, unit-tested with mocks, and observed via the standard lineage system. The platform→adapter boundary stays clean: adapter is IO-only (D057).
**Consequence:** `full_pipeline.py` topology is `niche_to_ideas → idea_to_script → voice_production → legacy_render`. The `render()` method gains a keyword-only `voice_alignment: Optional[VoiceAlignmentArtifact] = None` parameter — when provided, TTS is skipped in the adapter and word timestamps are passed to `build_ffmpeg_script()` for caption sync.
**See:** `cf_platform/workers/voice_production.py`, `cf_platform/adapters/legacy_video.py`. **No new dependencies (httpx already present).**

---

## D061 — TTS provider: Gemini 2.5 Flash (replacing ElevenLabs)
**Date:** 2026-06-18 (decision) · 2026-06-19 (implementation target: P6-S7)
**Status:** ACTIVE — implementing in P6-S7
**Decision:** Use **Gemini 2.5 Flash TTS** as the TTS engine in `voice_production.py`. Replaces the ElevenLabs placeholder built in P6-voice session (2026-06-19). ElevenLabs placeholder was built first to validate the worker architecture (D062); Gemini is the intended production engine.
**Rationale:** Cost is the driver. Gemini TTS is free within Google AI Studio free tier at POC volumes (~30–50 runs/month); ElevenLabs is ~$22/M chars. The operator has validated Gemini TTS output quality from manual use.
**Consequence:** `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` removed from `PlatformSettings`; replaced by `GEMINI_API_KEY: str = ""` + `GEMINI_TTS_VOICE: str = ""`. Gemini returns PCM/WAV — still re-encode to MP3 via ffmpeg subprocess (same pattern). Deepgram alignment and proportional fallback unchanged. New dependency: `google-generativeai` added to `requirements.txt` in P6-S7.
**Runners-up considered:** Google Cloud TTS Neural2 (~$4/M, 1M chars/month free tier, requires GCP service account); OpenAI TTS `tts-1` (~$15/M, simplest REST shape).
**See:** `cf_platform/workers/voice_production.py`. **Dependency `google-generativeai` added in P6-S7.**

---

## D060 — Information Ownership Principle
**Date:** 2026-06-18
**Decision:** Every worker in the pipeline owns exactly one type of information and may not cross into another worker's ownership domain. Current assignments: Discovery Worker owns research; Evaluator owns truth (fact-checking + alignment scoring); Narrative Lens Worker owns storytelling; Script Generator owns prose; Integrity Checker owns enforcement. Workers may transform information received from upstream workers but may not create information that belongs to another worker's domain.
**Rationale:** As the pipeline grows from 12 to 30+ workers, unscoped information creation is the primary failure mode — any worker that can generate facts is a second hallucination source. Formalising ownership boundaries makes this structurally impossible: the Narrative Lens cannot generate facts because it only receives verified claims from the Evaluator; the Script Generator cannot verify claims because it does not have access to raw research. Ownership also makes observability clean: any factual error can be attributed to exactly one node.
**Consequence:** Applied strictly to the Narrative Lens Worker (D059). Future workers must declare their ownership domain in their module docstring. Workers that would need to cross boundaries require a new architecture decision first.
**See:** D059. **No new dependencies.**

---

## D059 — Narrative Lens Worker Contract: no new factual content
**Date:** 2026-06-18
**Decision:** The Narrative Lens Worker (node [4]) receives only verified blueprint claims and evaluation corrections. It MUST NOT invent any fact, number, statistic, study, brand, country, timeline, or comparison. Its output (`NarrativeLens`) contains four storytelling reframings (identity, contrarian, philosophical, emotional) and a list of story devices, all derivable exclusively from the verified claims supplied to it. This is enforced by: (1) prompt contract — explicit forbidden list; (2) input restriction — the worker reads only `merged_blueprint` and `evaluation` artifacts, never signals, raw research, or web results; (3) schema constraint — `NarrativeLens` fields are plain strings (reframings), not claim objects, removing the structural temptation to invent.
**Rationale:** Without this contract, a creative model (even Haiku) will connect dots inventively and produce plausible-sounding but unverified assertions (e.g. "80% of Europeans prefer durability"). This would silently introduce a second hallucination source after the Evaluator, undermining the Blueprint IR pipeline's factual integrity guarantee. The Narrative Lens is a translator, not a researcher: Facts → Storytelling, not Facts → New Facts.
**Consequence:** `NarrativeLens` schema has no `supporting_claim_ids` at this stage — enforcement is in the prompt and input restriction. The `_build_user_message()` in narrative_lens.py deliberately omits signals and context; it passes only blueprint.claims, evaluation.factual_corrections, and blueprint.required_evidence.
**See:** D060. **No new dependencies.**

---

## D058 — Idea→Script stage: Blueprint IR + single-pass generation + patch repair
**Date:** 2026-06-18
**Decision:** The Idea→Script block is redesigned as a deterministic content compiler with three phases: (1) Blueprint IR generation — a structured intermediate representation (hook angle, sections, claims, evidence requirements) produced once by a cheap model before any script text is written; (2) Single-pass script generation — the LLM writes the script exactly once from the finalised blueprint + selected hook, no regeneration loops; (3) Patch-based integrity repair — if the integrity check fails, a Haiku model emits structured `Patch` objects (operation/target/replacement) applied deterministically, never a full rewrite. MAX_INTEGRITY_LOOPS = 2.
**Rationale:** The previous write→score→fact-check→refine loop re-generated the full script on every pass ($1–$3/run observed in production). The root cause was conflating planning, evaluation, and generation into one agent loop. Separating them into a compiler pipeline eliminates regeneration cost while preserving correction capability. Blueprint IR is the key abstraction: it constrains the generation space before the expensive Sonnet call, making first-pass quality high enough that integrity repair is the exception, not the norm. `web_search` is removed entirely — evaluation uses model knowledge.
**Consequence:** Replaces `script_writer`, `script_quality_scorer`, `fact_checker`, `script_refiner` workers with 10 specialised nodes. `build_idea_to_script_graph` topology changes completely. Target cost per `/script` run: $0.05–$0.10. Implemented in P5-S6.
**See:** BACKLOG_ACTIVE.md [P5-S6]. **No new dependencies.**

---

## D057 — Artifacts are truth; state is a message bus
**Date:** 2026-06-12
**Decision:** In the platform layer, LangGraph graph state carries **only** artifact references (`stage_name -> r2_key`) and strict control signals. It never carries artifact bodies and never exposes a free-form mutation channel. The durable source of truth for every output is the artifact in R2, indexed in Postgres. State is ephemeral intra-run transport.
**Rationale:** An untyped state-delta channel is the seam through which lineage-first systems decay — it becomes a hidden side-channel and a second, unversioned data store, making analytics untrustworthy and runs un-reproducible. Restricting state to refs + control makes that failure mode structurally impossible, keeps LangGraph checkpoints small, and guarantees the body of record is always the versioned R2 artifact.
**Consequence:** `WorkerOutput` has no `state_delta`. Control *values* (iteration counters, mode) are typed channels on the per-stage `StageState`, updated by graph reducers; the graph (not the worker) enforces loop bounds.
**See:** docs/v2_platform_plan.md §3, §4. **No new dependencies.**

---

## D056 — LangGraph abstraction model: Worker = Node
**Date:** 2026-06-12
**Decision:** A worker **is** a LangGraph node implementation. The hierarchy is fixed: **Worker → Node** (atomic state-transformer), **Stage → StateGraph** (composition of workers), **Platform → Graph-of-graphs** (orchestrator composing stages). A worker is stateless and pure (D040 applies), receives a typed `StageState`, returns a typed `WorkerOutput`, is version-pinned (worker_version + prompt_version + model), and **emits exactly one artifact per execution** — written by the observability wrapper, not the worker body. Control-flow/routing is graph edges, not workers (no artifact, not logged as a worker_execution). IO adapters (source adapters, legacy adapter) are not workers (see D050, D057).
**Rationale:** The plan previously *implied* this model but never stated it contractually, risking drift during implementation (workers becoming services, nodes becoming wrappers, lineage fragmenting). Making it an enforceable contract — the same way D040 is enforced in review — keeps decomposition stable and lineage consistent.
**Enforcement:** Code review. Documented in ARCHITECTURE.md (LangGraph abstraction model) and CONVENTIONS.md.
**See:** docs/v2_platform_plan.md §3–§5. **No new dependencies** (contract only).

---

## D055 — Replay-ready constraints (enables Epic 34)
**Date:** 2026-06-12
**Decision:** Logged now to constrain present work (same pattern as D040/D041): (1) artifacts are immutable — a re-run writes a new version, never mutates in place; (2) prompts are version-pinned and stored by version in the Worker Registry so they are retrievable for replay; (3) `execution = f(prompt_version, model, inputs, sampling_params)` — `sampling_params` (temperature/top_p/top_k) are pinned and recorded in lineage.
**Rationale:** The platform's analytics thesis requires causal clarity. Holding inputs + prompt_version + model + sampling_params fixed makes run-to-run variation attributable to LLM sampling alone (averageable across N runs), never confounded with silent config drift. This is the foundation that makes the Epic 34 replay/evaluation engine cheap to add later.
**Honest limit:** Anthropic exposes no request seed, so executions are reproducible *up to sampling noise at fixed params* — params are a controlled, recorded variable, not a hidden one. Full bitwise reproducibility is not claimed.
**See:** docs/v2_platform_plan.md §3 (law 6), Epic 34. **No new dependencies.**

---

## D054 — YouTube Analytics ingestion (channel-owner OAuth + scheduler)
**Date:** 2026-06-12
**Decision:** Analytics attribution (P7) ingests retention/views/avg-view-%/CTR per video from the YouTube Analytics API using a channel-owner OAuth token, on a schedule (Railway scheduled task), writing time-series rows to `video_metrics`. Run↔video linkage is captured in `published_videos` (operator records the published URL until a publish agent exists).
**Rationale:** Closing the learning loop ("which prompt_version → retention") requires online performance data joined to lineage. YouTube Analytics is the first metrics source; OAuth here is a precursor to the per-user identity work (S19).
**Dependency (when implemented):** YouTube Analytics OAuth client + a scheduler. Must be reflected in requirements.txt with this entry.
**See:** docs/v2_platform_plan.md §6, Epic 33 (P7).

---

## D053 — Web-search tool for the Idea→Script fact-check loop
**Date:** 2026-06-12 · **Resolved:** 2026-06-17 (P5-S3)
**Decision:** The Idea→Script block (P5) includes a fact-check node that verifies claims via a web-search tool, isolated in its own story (P5-S3) so the cyclic refine loop (P5-S4) is not blocked by tool-integration issues. **Provider chosen at P5-S3: Anthropic's built-in `web_search_20260209` server-side tool**, passed as `tools=[{"type": "web_search_20260209", "name": "web_search"}]` in the Messages API call. Claude executes searches server-side; no client-side tool loop required.
**Rationale:** Fact-checking is the quality gate that makes generated scripts trustworthy. Isolating the external dependency de-risks the convergence logic and keeps the loop deterministic in structure. The built-in tool was chosen over a standalone search API because: (1) no new dependency — reuses the existing `anthropic` SDK and `ANTHROPIC_API_KEY`; (2) satisfies the free-tier constraint (billed through Anthropic API usage); (3) no additional ENV vars; (4) consistent with how every other worker calls the SDK.
**Dependency:** No new dependency. Uses `anthropic>=0.40.0` already in `requirements.txt`.
**See:** docs/v2_platform_plan.md §8 (P5). `cf_platform/workers/fact_checker.py`.

---

## D052 — LangGraph as orchestration/agent engine (supersedes D042)
**Date:** 2026-06-12
**Decision:** The platform's blocks and workers are authored in **LangGraph** (StateGraph of nodes), with the **Postgres checkpointer** providing durability, resume across Railway restarts, and human-in-the-loop via `interrupt`. This **supersedes D042 (Inngest)**. The `anthropic` SDK + existing `ModelRouter` are kept **inside** nodes — `langchain-anthropic` is not adopted (preserves cost lineage, minimizes dependency surface).
**Rationale:** The D041 target is full of reasoning loops (write→score→fact-check; generate→critique→refine) — graphs with cycles, which is LangGraph's core strength and awkward in Inngest. The future legacy rebuild (Epic 32) as "a workflow of workers" is LangGraph's exact use case. D040's pure async functions already satisfy the LangGraph node contract, so adoption is drop-in.
**Honest limit:** LangGraph + PostgresSaver gives durable *state* + resume, but not a managed always-on, auto-resume-after-deploy service (that is LangGraph Platform, paid). At single-operator POC scale, graphs run in a background worker and resume from the checkpoint — acceptable; revisit if true fire-and-forget across deploys is needed.
**Dependencies (P1/P2):** `langgraph`, `langgraph-checkpoint-postgres`. Add to requirements.txt at P1/P2 with this entry.
**See:** docs/v2_platform_plan.md §2, §8.

---

## D051 — Worker / lineage envelope
**Date:** 2026-06-12
**Decision:** Every worker execution records a `WorkerExecution` row: `run_id, worker, worker_version, prompt_version, model, sampling_params, input_tokens, output_tokens, cost_usd, latency_ms, status, artifact_r2_key, started_at, finished_at`. Lineage fields are **columns, not JSON** so analytics joins are SQL `GROUP BY`, not blob scans. The Worker Registry resolves version/model/sampling_params and the observability wrapper writes the row (D056).
**Rationale:** Lineage is the differentiator of the whole platform. Promoting `ModelRouter`'s ad-hoc cost logging into a first-class, queryable execution record is what makes the system observable and the analytics loop (P7) and replay engine (Epic 34) possible.
**See:** docs/v2_platform_plan.md §4, §6. **No new dependencies** (uses Postgres from D048).

---

## D050 — Discovery via SourceAdapter Protocol; adapters emit trace events
**Date:** 2026-06-12
**Decision:** The Discovery worker (P3) reads signals through a `SourceAdapter` Protocol (`fetch(niche, params) -> list[Signal]`). The contract is defined in P0; concrete adapters (`reddit`, `google_trends`, `youtube`) are implemented in P3 with partial-failure isolation (one dead source ≠ dead worker). Adapters are **IO, not workers** — they emit `TraceEvent` rows (source, op, latency, cost, status), never artifacts. Adding a 4th source (NewsAPI, Apify) is a new adapter file, not a rework. **X/Twitter is dropped** for the free-tier constraint and added later, likely via **Apify**.
**Rationale:** Multi-source discovery sprawls without a fixed interface. Separating IO adapters (trace events) from workers (artifacts) preserves per-source observability — contribution, cost, retrieval debugging — without polluting the worker/lineage layer or breaking the one-artifact-per-worker rule.
**Dependencies (when implemented, P3):** Reddit/Trends/YouTube access (httpx-first; `praw`/`pytrends` only if pragmatic — separate entry if added). Env: `REDDIT_*`, `YOUTUBE_API_KEY`.
**See:** docs/v2_platform_plan.md §3 (law 5), §4.

---

## D049 — Telegram as a thin trigger layer (httpx); formatter rule
**Date:** 2026-06-12
**Decision:** Telegram integration is a trigger-only layer: `POST /telegram/webhook` validates a secret token, parses commands (`/ideas`, `/script`, `/produce`), and calls a block — **no business logic**. Implemented with plain `httpx` (no bot SDK), mirroring the Deepgram/ElevenLabs pattern. **Rule:** interfaces (Telegram, REST-chat) emit output **only via a formatter** (`format_for_chat(artifact) -> str`); they never serialize an internal `Artifact`/state schema directly to chat.
**Rationale:** Keeping Telegram thin prevents business logic from fragmenting across interfaces. The formatter rule prevents internal schema coupling from leaking into UX (which would make schema changes break chat).
**Dependencies:** none (httpx already present). Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`.
**See:** docs/v2_platform_plan.md §8 (P3).

---

## D048 — Postgres as the metadata index (required + early, analytics-shaped)
**Date:** 2026-06-12
**Decision:** Introduce Railway Postgres as the queryable metadata index for the platform, from the skeleton phase (P2). **R2 remains the source of truth for artifact bodies; Postgres is the index** — `artifacts` rows store the R2 key + lineage columns, never the body. Core tables: `runs`, `artifacts`, `worker_executions`, `trace_events`; reserved for P7: `published_videos`, `video_metrics`. DDL drafted at P0-S4 in `cf_platform/db/schema.sql`.
**Migration tooling (decided P0-S4):** **Raw SQL**, not Alembic. P2-S2 will add `cf_platform/db/migrations/NNNN_description.sql` (numbered, idempotent — `CREATE TABLE IF NOT EXISTS`, etc.) plus a `schema_migrations` tracking table and a small runner (`psycopg`, applied at startup, fault-isolated like the rest of the platform DB init). Schema is ~6 tables with no ORM models in the app — Alembic's autogenerate/versioning machinery is overhead the platform doesn't need; a handful of hand-written, reviewable SQL files is simpler to audit for an analytics-shaped schema that changes rarely after P2.
**Rationale:** The platform's purpose is observability and version-vs-outcome analytics. R2 blobs are not queryable; "which prompt_version → retention" must be a SQL join, which requires lineage as columns. Retrofitting this later means rebuilding the blocks, so Postgres is required and early — not deferrable. Railway Postgres is one click and fault-isolated from the legacy app.
**Dependencies (P2):** `psycopg`, Railway Postgres plugin. Add to requirements.txt at P2 with this entry.
**See:** docs/v2_platform_plan.md §6, `cf_platform/db/schema.sql`, `cf_platform/db/queries.sql`.

---

## D047 — Isolate legacy by wrapping (adapter), not moving
**Date:** 2026-06-12
**Decision:** The existing Script→Video pipeline in `src/` stays in place and **untouched**. The new `cf_platform/` package reaches it **only** through `cf_platform/adapters/legacy_video.py`, which is the single module permitted to import from `src/`. The adapter is defined as an interface (Protocol) with an in-process implementation now (calls `src/pipeline.py`), designed so a separate-service HTTP implementation is a one-class swap later.
**Rationale:** Physically relocating a working, ~750-test tree on day one is high-risk for zero functional gain. Enforcing isolation by *dependency direction* (`cf_platform → adapter → src`, never reverse) achieves the same separation with no migration risk — and D040 (pure async functions) makes the adapter nearly free. The interface is also the stable seam that lets the legacy implementation be rebuilt later (Epic 32) without the platform noticing.
**Constraint:** No module in `src/` may import `cf_platform/`. Enforced in code review, like D040.
**See:** docs/v2_platform_plan.md §2, §3 (law 1). **No new dependencies.**

---

## D046 — Bound assign_words_to_scenes lookahead to prevent drift
**Date:** 2026-06-11
**Decision:** Limit `assign_words_to_scenes` (src/ffmpeg_builder.py) to scanning at most `_MATCH_WINDOW` (15) Deepgram words ahead of the current position for each voiceover token. A token with no match in that window is skipped without advancing position, instead of scanning unboundedly to the end of the transcript.
**Rationale:** D045 fixed the systematic digit-vs-word mismatch, but `assign_words_to_scenes` remained fragile to *any* single-token mismatch — e.g. Deepgram transcribing "0.03%" as "point oh three percent" while the storyboard spells it "zero point zero three percent" ("zero" vs "oh", and a missing leading "zero"). With unbounded scanning, the failed "zero" match causes the next token ("point") to match correctly, but the leftover unmatched "zero" leaves `pos` one step behind — and in worse cases (a token that matches a common word much later) `pos` can jump tens of seconds forward, corrupting every subsequent scene exactly like the D045 bug. Observed in run with scene 30's voiceover_line "...zero point zero three percent." causing captions to disappear from scene 31 onward.
Bounding the lookahead means a single mismatched/missing token only costs that one token's match — it cannot drag `pos` to an unrelated later occurrence of a common word.
**No new dependencies.**

---

## D045 — Disable Deepgram smart_format for word-level alignment
**Date:** 2026-06-10
**Decision:** Set `smart_format: "false"` on the Deepgram Nova-2 `align_audio()` call (src/alignment.py).
**Rationale:** Storyboard `voiceover_line` text always spells out numbers, percentages, and large quantities for TTS pronunciation (e.g. "ninety percent", "ten thousand", "zero point zero three percent", "twenty-year"). With `smart_format: "true"`, Deepgram collapses these to digit/symbol form ("90", "10000", "0.03%"), which never matches the spelled-out tokens produced by `_vo_tokens()` in `assign_words_to_scenes` (ffmpeg_builder.py).
A single such mismatch is catastrophic, not just cosmetic: `assign_words_to_scenes` does a greedy forward scan, so when a token like "ninety" fails to match "90", the next token ("percent") can match a *different, much later* occurrence of "percent" elsewhere in the transcript. This drags `pos` forward by tens of seconds, corrupting alignment for every subsequent scene — observed in run `2026-06-10_the-3-fund-portfolio` as one scene's clip stretching to 98s (nearly the entire video) while ~25 following scenes were compressed to the 0.08s minimum.
With `smart_format: "false"`, Deepgram transcribes numbers as the words actually spoken, matching the storyboard convention and eliminating both the drift bug and missing captions for numeric/percentage phrases.
**No new dependencies.**

---

## D044 — FastAPI BackgroundTasks for render decoupling (S13-S3)
**Date:** 2026-06-05
**Decision:** Use `fastapi.BackgroundTasks` to decouple `POST /runs/{run_id}/render` from Railway's HTTP request timeout. The route returns 202 immediately; the render executes in a background task via `asyncio.to_thread` (blocking subprocess kept off the event loop). An in-process `_RENDER_STATE` dict tracks status per run_id; `GET /runs/{run_id}/render/status` exposes it for polling.
**Rationale:** Railway's free-tier HTTP timeout (~60 s) is shorter than a typical FFmpeg render. A job queue (Redis + Celery/RQ) adds operational complexity and cost that is unjustified for a single-operator POC on a single Railway instance. `BackgroundTasks` requires zero new dependencies and survives the current single-process deployment model.
**Limitations:** In-process state is lost on Railway redeploy/restart — the status endpoint returns 404 for runs started before the restart. Acceptable for POC; a durable state store (Redis, R2 polling) can replace `_RENDER_STATE` in a future sprint without changing the API contract.
**No new dependencies added.**

---

## D043 — Chunked parallel storyboard generation (S13-S1)
**Date:** 2026-06-04
**Decision:** When a script exceeds `STORYBOARD_CHUNK_SIZE` paragraphs (default 10), split it into chunks at blank-line boundaries and call Claude concurrently for each chunk via `asyncio.gather`. Merge and renumber results before Haiku validation.
**Rationale:**
- Claude's `max_tokens=8192` cap means a 30-paragraph script (~50+ scenes) will be silently truncated mid-storyboard. Chunking removes this ceiling entirely.
- Parallel calls (asyncio.gather) keep wall-clock latency proportional to the longest single chunk, not the total script length.
- Splitting at blank-line paragraph boundaries guarantees no sentence is cut mid-phrase — each chunk is a coherent segment of the script.
- Alignment timestamps are sliced proportionally by character count per chunk so scene durations remain anchored to real audio timing even in the chunked path.
- Single-chunk path is preserved exactly — no behavioral change for scripts ≤ STORYBOARD_CHUNK_SIZE paragraphs.
**No new dependencies** — uses only stdlib `asyncio`.

---

## D042 — Inngest as durable workflow engine for Sprint 20+
**Date:** 2026-06-04
**Status:** SUPERSEDED by D052 (2026-06-12) — LangGraph + Postgres checkpointer chosen as the orchestration/agent engine for the v2 platform. Retained for history.
**Decision:** When the pipeline transitions from human-triggered steps to autonomous multi-agent orchestration (Sprint 20+), the orchestration layer will be **Inngest** (managed durable workflow engine).
**Rationale:**
- FastAPI `BackgroundTasks` (Sprint 13) solves the Railway 60s timeout problem but is not durable — it dies with the process. A 15-minute agentic pipeline needs checkpointed state that survives Railway deploys and restarts.
- Inngest is managed (no infrastructure to run), Railway-compatible (HTTPS endpoint registration), event-driven (each agent fires an event; the next picks it up), and has a generous free tier sufficient for POC.
- `step.waitForEvent()` provides native human-in-the-loop gates with configurable timeouts — the review pattern needed for asset candidate approval and script approval.
- Alternative considered: Temporal (most powerful, best guarantees, but self-hosted or expensive cloud). Rejected for POC — Inngest is simpler to operate.
- Alternative considered: DIY (Redis + BullMQ). Rejected — adds infra; Inngest is purpose-built.
**Migration path:** Sprint 13 `BackgroundTasks` → Sprint 20 Inngest functions. The route handler changes from `background_tasks.add_task(render_run, ...)` to `inngest_client.send_event("pipeline/render.requested", ...)`. The `render_run` function itself is **unchanged** because it is a pure async function (D040).
**Constraint:** Do not add Inngest to `requirements.txt` until Sprint 20 planning begins. Do not design Sprint 13–19 code assuming Inngest is present.

---

## D041 — Target architecture: multi-agent autonomous content factory (Sprint 20+)
**Date:** 2026-06-04
**Decision:** The long-term product direction is a fully autonomous content factory where a topic string as input produces published video on social platforms as output. Sprints 13–19 are explicitly designed as its foundation — nothing built in those sprints is discarded.
**Agent graph (Sprint 20+):**
- Agent 0 — Trend Research: web_search + Reddit + Google Trends + NewsAPI → viral ideas
- Agent 1 — Script Writer: write × 3 → score → fact-check loop → polished script
- Agent 2 — Storyboard: generate → self-critique → refine loop → storyboard.json
- Agent 3 — Asset Acquisition: multi-source search → CLIP scoring → 2–3 candidates per scene → optional human review gate
- Agent 4 — Render + Publish: FFmpeg → social platform APIs (YouTube / Instagram / TikTok)
**Entry point:** `POST /api/pipeline` (Sprint 18) fires an Inngest event. All agents are Inngest functions chained by events.
**Human-in-the-loop:** Optional review gates at script approval and asset selection. Gates use `step.waitForEvent()` with configurable timeout (default 24h); auto-approve on timeout for fully autonomous mode.
**Sprints 13–19 as foundation:**

| Sprint 13–19 | Role in Sprint 20+ |
|--------------|--------------------|
| Chunked storyboard | Parallel Agent 2 calls per script chunk |
| Parallel acquisition | Agent 3 batched multi-source search |
| Background render | Inngest wraps the same render function |
| API-first pipeline | External entry point for all agents |
| Webhook | Inter-agent event notification |
| Google OAuth | Identity for per-user social platform tokens |
| Per-user R2 | Per-creator content isolation at scale |

**See:** docs/ARCHITECTURE.md § 3 for full target architecture diagram.

---

## D040 — Pure async function discipline (agent-ready pipeline)
**Date:** 2026-06-04
**Decision:** Every pipeline step function must be a pure async function — it takes all its inputs as explicit parameters and returns its output as a return value. It must not read from HTTP request context, global state, or any object that is tied to the FastAPI request lifecycle.
**Rationale:**
- Sprints 13–19 call pipeline functions from contexts other than HTTP route handlers: background tasks, parallel `asyncio.gather` batches, chunked storyboard merges.
- Sprint 20+ will call the same functions from Inngest workflow steps, which are completely outside the HTTP layer.
- A function coupled to `Request`, `Depends()`, or `BackgroundTasks` cannot be called from any of these contexts without modification.
- Writing pure functions now costs nothing. Refactoring tightly coupled functions later costs a sprint.
**Rule:** Routes are thin wrappers. The pattern is: route reads request → calls pure domain function → writes response. No business logic in route files.
**Enforcement:** Enforced in code review. Any function whose signature includes `Request`, `BackgroundTasks`, or any FastAPI `Depends()` object (other than `Settings`) is a violation.
**Exception:** `Settings` may be injected via `Depends(get_settings)` in route handlers only. Domain functions receive config values as plain Python types, not the `Settings` object itself, unless the full settings object is genuinely needed.
**See:** CONVENTIONS.md § Async function discipline for code examples.

---

## D037 — Stdlib HMAC cookie for single-operator auth (no new dependency)
**Date:** 2026-05-28
**Decision:** Use stdlib `hmac` + `hashlib` for session cookie signing. Cookie value is a constant HMAC-SHA256 digest of the string `"authenticated"` keyed on `SESSION_SECRET_KEY`. No session ID, no server-side session store.
**Rationale:**
- POC scope: one operator, one password. No user management required.
- Avoids adding `itsdangerous` or any other signing library.
- `hmac.compare_digest` prevents timing attacks on cookie verification.
- Session invalidation is enforced by deleting the cookie (logout), not by expiry or server-side state.
**Trade-offs:** Changing `SESSION_SECRET_KEY` invalidates all active sessions. Acceptable for single-operator POC; would need server-side session store for multi-user.
**Implemented by:** S5-S5

---

## D036 — VO-first pipeline: alignment before storyboard
**Date:** 2026-05-27
**Decision:** Reorder pipeline to run voiceover upload and Deepgram alignment before storyboard generation.
**Rationale:**
- Smoke test revealed 20s VO vs 16s storyboard mismatch — guessed scene durations are unreliable
- Real word timestamps from Deepgram make scene timing deterministic
- Eliminates the entire class of pacing bugs permanently
- Proportional redistribution (E5-S2) becomes a fallback only, not the primary timing source
**Impact:** Pipeline UX changes — users upload VO before seeing storyboard. This is the correct product flow.
**Implemented by:** E5-S5

---

## D035 — Poppins Bold as subtitle font (replaces Montserrat ExtraBold)
**Date:** 2026-05-27
**Decision:** Use Poppins Bold for `VoiceCaption` ASS subtitle style.
**Rationale:**
- TikTok Sans not available outside TikTok ecosystem
- Poppins Bold is the closest widely-available match: rounded, bold, high legibility on video
- Available via Google Fonts; will be bundled in repo under `assets/fonts/` and COPYed in Dockerfile if apt package unavailable
- Matches SampleDis reference visual target approved by product owner
**Supersedes:** D033 (Montserrat ExtraBold)
**Implemented by:** E4-S6 (iteration 2)

---

## D034 — Deepgram Nova-2 over WhisperX for word-level timestamps
**Date:** 2026-05-27
**Decision:** Use Deepgram Nova-2 API for word-level timestamp extraction instead of WhisperX.
**Rationale:**
- WhisperX requires `torch` + `torchaudio` (~1.5 GB Docker increase, 30–90s CPU inference per run)
- Deepgram returns word timestamps in <1s via HTTP, zero Docker image impact
- Cost: ~$0.0043/min — negligible for short-form VO (30–90s clips)
- Built-in fallback to proportional timing if API call fails
- Internal `WordTimestamp` schema abstracts the provider — swappable to OpenAI Whisper API if needed
**Fallback provider:** OpenAI Whisper API (`verbose_json` + `timestamp_granularities[]=word`)
**Implementation:** Plain `httpx` POST to `https://api.deepgram.com/v1/listen`, no SDK. `DEEPGRAM_API_KEY` added to config.
**Supersedes:** Previous plan in E5-S4 (WhisperX forced alignment).

---

## D038 — ElevenLabs for TTS voiceover generation
**Date:** 2026-05-30
**Decision:** Use ElevenLabs API for text-to-speech voiceover generation when the operator provides a script but no audio file.
**Rationale:**
- Best-in-class voice quality for short-form video narration
- Simple REST API — no SDK required; plain `httpx` POST (zero new dependencies)
- Voice ID is configurable per-project via `ELEVENLABS_VOICE_ID` ENV var — operator can switch voices without code changes
- Supports PCM output format, which enables clean byte-level chunk concatenation (see D039)
- Cost is acceptable for POC: ~$0.30/1K chars; a 60s voiceover script ≈ 500–700 chars ≈ $0.15–$0.21/run
**New ENV vars:** `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
**Implemented by:** S10-S1

---

## D039 — Chunked parallel TTS for voice consistency on long scripts
**Date:** 2026-05-30
**Decision:** Split scripts into sentence-boundary-aligned chunks of ~1000 chars, send all chunks to ElevenLabs in parallel via `asyncio.gather`, concatenate raw PCM responses in order, then encode to MP3 once via ffmpeg.
**Rationale:**
- ElevenLabs voice quality degrades on long inputs (prosody drift, pacing inconsistency)
- Shorter chunks produce more consistent, natural-sounding narration per segment
- Parallelisation keeps total latency comparable to a single long request
- PCM (not MP3) requested from ElevenLabs because PCM chunks can be byte-concatenated without header collisions or audible pops at boundaries; a single MP3 encode at the end is cleaner than MP3-concat
- `previous_text` and `next_text` context params sent on each chunk request to help ElevenLabs maintain prosody continuity across boundaries
**Chunk split rule:** sentence boundary (`.`, `!`, `?`) nearest to 1000-char mark; never split mid-sentence
**Merge:** raw PCM bytes concatenated in request order → `ffmpeg -f s16le -ar 44100 -ac 1 -i pipe:0 output.mp3`
**Implemented by:** S10-S1

---

## D033 — Montserrat ExtraBold font for voiceover captions
**Date:** 2026-05-27
**Decision:** Add `fonts-montserrat` apt package to the Dockerfile so libass can render the `VoiceCaption` ASS style using `Montserrat ExtraBold`.
**Rationale:** Montserrat ExtraBold is the target caption font for mobile-first Shorts style (72pt, high-contrast, thick outline). It is not present in `python:3.11-slim` by default. The `fonts-montserrat` Debian package provides the full Montserrat family including ExtraBold. If the package is ever unavailable or the ASS style name does not resolve, libass will fall back to Arial Bold or the system default — captions remain legible but lose the brand typeface.
**Fallback:** Change `Fontname` in `_CAPTIONS_ASS_HEADER` (src/captions.py) from `Montserrat ExtraBold` to `Arial Bold` if Railway build fails to resolve the font.
**No requirements.txt change** — this is a system font, not a Python package.

---

## D032 — CLIP semantic reranking: sentence-transformers + Pillow
**Date:** 2026-05-25
**Decision:** Add `sentence-transformers` (with `clip-ViT-B-32` model) and `Pillow` to rerank Pexels results by visual-semantic match before the existing size/resolution selection logic runs.
**Rationale:** Pexels returns results in keyword-match order, not semantic relevance order. The first result for "apartment building exterior" may be a generic skyline rather than the intended close-up. CLIP scores each thumbnail against the scene's visual description text, putting the most semantically appropriate clip at the top of the list. This is used _before_ the existing `_pick_best_video_file` / `_pick_first_qualifying_photo` filter, so resolution requirements are still enforced — CLIP only changes the ordering within the result set.
**Why sentence-transformers over raw transformers:** sentence-transformers provides a unified `.encode()` API for both text and PIL Images via the same model object, requires no custom preprocessing pipeline, and its CLIP wrapper is battle-tested. Raw `transformers` would require separate tokenizer + processor setup.
**Model:** `clip-ViT-B-32` (~340MB download, ~600MB RAM on CPU). Downloaded at first startup and cached by the HuggingFace hub. Pre-downloading during Docker build is possible but deferred for POC.
**Feature flag:** `CLIP_RERANK_ENABLED=False` default — off in all existing deployments. Enable per-environment when validating.
**Latency:** ~40ms/image on Railway CPU. For per_page=5, total reranking adds ~200ms per scene acquisition (within the <500ms target).
**Dependencies added:** `sentence-transformers>=3.0.0`, `Pillow>=10.0.0`

---

## D031 — Scene-boundary caption timing as interim solution
**Date:** 2026-05-24
**Decision:** Voiceover-line captions (E4-S5) use scene boundaries for timing — each `voiceover_line` is shown for the full duration of its scene. Word-level timing is deferred to E5-S4 (WhisperX forced alignment).
**Rationale:** Word-level timing requires the rendered voiceover audio and a forced-aligner pass (WhisperX, E5-S4). Scene-boundary timing requires only the storyboard, which is already available at ffmpeg-script build time. For POC validation, scene-boundary captions are sufficient to confirm readability and placement. The WhisperX upgrade path (D030) replaces them with ms-precise word boundaries once the audio is in R2.
**On_screen_text vs captions distinction:** Two separate ASS tracks with different purposes — `on_screen_text` (center screen, 72pt Bold, keyword callouts) vs voiceover captions (bottom, 42pt Regular, full sentence). They are burned in as separate ffmpeg passes so their styles never conflict.

---

## D030 — WhisperX forced alignment as upgrade path for scene timing
**Date:** 2026-05-24
**Decision:** WhisperX (faster-whisper + phoneme aligner) chosen as the ms-precise scene timing upgrade path, implemented as a separate optional pipeline step (`POST /runs/{run_id}/align`) that writes `alignment.json` to R2. The ffmpeg-script step reads `alignment.json` if present and falls back to proportional redistribution (E5-S2) if not.
**Rationale:** Proportional redistribution (E5-S2) is a good-enough approximation for average pacing but breaks on scenes with long pauses, fast delivery, or repeated words. WhisperX forced alignment produces word-level timestamps from the actual recording, giving true ms-precise scene cut points that match what the operator recorded — not what a model predicted.
**Why WhisperX over alternatives:**
- Whisper alone: word-level timestamps are approximate (beam search, not forced alignment). WhisperX adds CTC phoneme alignment on top for frame-accurate word boundaries.
- AssemblyAI / Deepgram: paid APIs, incompatible with free-tier-only POC constraint (see CLAUDE.md hard constraints).
- Montreal Forced Aligner: requires separate language model install, complex setup on Railway.
**Trade-offs:** ~2min Docker build time increase (torch CPU + faster-whisper); alignment step adds ~1-3min processing per 60s VO on Railway CPU. Both are acceptable given this is an optional enhancement step.
**Backward compatibility:** Proportional redistribution (E5-S2) remains as fallback. Absence of `alignment.json` produces no error — pipeline degrades gracefully.
**Implementation deferred** until E4-S2 (captions) and E4-S3 (zoompan) are validated on real renders. Query decomposition (E5-S3) should also be confirmed sufficient or insufficient before adding alignment complexity.
**Dependency added (when implemented):** `whisperx` (pulls `faster-whisper`, `torch` CPU build) — must have DECISIONS.md entry before adding to requirements.txt.

---

## D029 — concat demuxer replaced with filter_complex trim+setpts
**Date:** 2026-05-24
**Decision:** FFmpeg script generation switches from concat demuxer to filter_complex with trim+setpts per scene.
**Rationale:** concat demuxer causes non-monotonic DTS on mixed-framerate sources (e.g. Pexels videos at 24fps mixed with Replicate images padded to 25fps). Non-monotonic DTS causes progressive audio drift and occasional "DTS out of order" errors that silently corrupt the output. filter_complex with `setpts=PTS-STARTPTS` resets timestamps correctly after every trim, eliminating carryover from source container timestamps.
**Implementation:** ffmpeg_builder.py — replace per-scene file list + `ffmpeg -f concat` with a single filter_complex graph: `[0:v]trim=...,setpts=PTS-STARTPTS[v0]; [1:v]trim=...,setpts=PTS-STARTPTS[v1]; ... [v0][v1]...concat=n=N:v=1:a=0[outv]`.
**No new dependencies.**

---

## D028 — zoompan parameters: fps=25, d=duration_s×25, scale+pad required
**Date:** 2026-05-24
**Decision:** zoompan filter uses fps=25, d=duration_s*25, s=1080x1920. All image inputs must be pre-scaled and padded to 9:16 before zoompan.
**Rationale:** zoompan `d` parameter is frame count, not seconds — using a hardcoded value (e.g. d=125 = 5s) causes incorrect duration on non-5s scenes. At fps=25, d=duration_s*25 is always correct. scale+pad normalization is required because zoompan `s` parameter only sets output size, not input size; a non-9:16 source will stretch rather than fill-and-crop without a preceding scale+pad filter.
**Parameters:** still_with_motion: z=1.0→1.05 (gentle zoom in). animated: z varies by motion_effect (zoom_in/zoom_out/pan_left/pan_right).
**No new dependencies.**

---

## D027 — ASS subtitles over FFmpeg drawtext
**Date:** 2026-05-24
**Decision:** Captions burned into video using ASS subtitle format via `vf ass=` filter, not FFmpeg drawtext.
**Rationale:** ASS supports full typographic control (font family, size, bold, color, outline, shadow, alignment, margin), animation (fade in/out, karaoke), and word-level timing in a single file. drawtext requires one filter invocation per text event and has limited styling: no outline blur, no per-event positioning, no animation. Escaping special characters in drawtext filter strings is error-prone and fragile. ASS is the industry standard for styled subtitle burn-in.
**Font:** Montserrat Bold or Roboto Bold, 72pt, white, MarginV=120 (bottom third). Text uppercased per YouTube Shorts style.
**Dockerfile change required:** `apt-get install -y fonts-open-sans` (or Montserrat via curl) to embed font in Railway container.
**No new Python dependencies.**

---

## D026 — Query decomposition strategy: concrete nouns only, two-tier primary/fallback
**Date:** 2026-05-24
**Decision:** Storyboard prompt updated to enforce query decomposition for Pexels search: primary_query uses 3-4 concrete nouns only (no adjectives); fallback_query uses 1-2 words (core subject only). Few-shot examples included in prompt.
**Rationale:** Pexels is keyword-matched, not semantic. Adjectives reduce recall without improving precision — "rundown suburban neighborhood" matches fewer clips than "suburban street house". Concrete nouns represent what a cameraman would frame, which is how stock footage is tagged. Two-tier structure ensures a broad fallback when primary specificity returns zero results.
**Flux/Replicate prompts** updated separately to use cinematic direction terms (shallow depth of field, golden hour lighting, cinematic) which do improve AI generation quality but are irrelevant for keyword search.
**Scope:** docs/PROMPTS.md storyboard system prompt only. No code changes to acquisition pipeline — queries flow through unchanged.

---

## D025 — R2 bucket versioning enabled at infrastructure level (not in code)
**Date:** 2026-05-24
**Decision:** Enable object versioning on the `content-factory-dev` (and `content-factory-prod`) R2 bucket via the Cloudflare dashboard. No code changes required.
**Rationale:** R2 native versioning provides full artifact history (every storyboard, manifest, script, and video version is recoverable) with zero application code. Building step-level versioning in the pipeline would add complexity and storage management burden without meaningful benefit over what R2 provides natively.
**Action required:** Operator enables versioning on both R2 buckets in Cloudflare dashboard → R2 → bucket → Settings → Object versioning → Enable. Takes ~30 seconds. One-time setup.
**Deferred indefinitely:** In-code artifact versioning strategy.
**No new dependencies. No new ENV vars.**

---

## D023 — Custom Dockerfile for FFmpeg on Railway
**Date:** 2026-05-23
**Decision:** Replace the default Railway Nixpacks buildpack with a custom `Dockerfile` based on `python:3.11-slim` that installs FFmpeg via `apt-get`.
**Rationale:** Railway's default Python buildpack does not include FFmpeg. The render pipeline (`ffmpeg_script.sh`) requires FFmpeg to be present at runtime. Confirmed by exit code 127 (`ffmpeg: command not found`) in `run_log.txt` during smoke testing.
**Implementation:** `Dockerfile` in repo root; `railway.toml` and `railway.prod.toml` updated to `builder = "DOCKERFILE"`.
**No new Python dependencies** — FFmpeg is a system package only.

---

## D022 — Human touchpoint rule applied at epic granularity
**Date:** 2026-05-22
**Decision:** Every epic must include a UI story that delivers a human-testable artifact at the end of the epic's first functional stories. Applied immediately: E6-S1 added after E2-S1 to cover the pipeline through asset manifest generation.
**Rationale:** D019 (Human Touchpoint Rule) established that no sprint should pass without something a human can touch. D022 refines this to the epic level — each epic's core backend work must be followed by a UI story before proceeding to the next epic. Prevents accumulating multiple epics of backend-only work with no operator-facing validation.
**Trade-off:** Slight delay to next backend epic (E3-S1) while UI story is completed. Accepted — the touchpoint catches integration issues early and keeps non-technical stakeholders engaged.
**Applied to:** E6-S1 (end-to-end pipeline UI covering POST /runs, POST /runs/{run_id}/storyboard, POST /runs/{run_id}/manifest).

---

## D001 — Modular pipeline architecture
**Date:** 2026-05-21
**Decision:** Each pipeline step is a standalone module exposed as an API endpoint. Steps are triggered manually (POC).
**Rationale:** Easier to develop, test, and retry individual steps. Manual handoff acceptable for POC. Orchestration can be added later.
**Trade-off:** More manual operator intervention vs. fully automated pipeline. Accepted for POC.

---

## D002 — Railway for hosting (DEV + PROD)
**Date:** 2026-05-21
**Decision:** Railway hosts both DEV and PROD as isolated services with separate ENV vars and Drive roots.
**Rationale:** Simple Python service deploy, no infrastructure management, free tier sufficient for POC.
**Trade-off:** Railway free tier has usage limits. Acceptable for POC volume.

---

## D003 — Storage layer
**Date:** 2026-05-21 (revised 2026-05-22 — see D020, D021)
**Decision:** Storage layer migrated from Google Drive to Cloudflare R2. See D021 for final rationale.
**History:** Originally Google Drive with service account auth → revised to OAuth refresh token (D020) → replaced with Cloudflare R2 (D021) due to OAuth being incompatible with autonomous operation.

---

## D004 — FastAPI over Flask
**Date:** 2026-05-21
**Decision:** FastAPI chosen as the web framework.
**Rationale:** Native async support for concurrent API calls (Pexels, Replicate, Drive), Pydantic validation built-in, auto-generated OpenAPI docs useful during development.
**Trade-off:** Slightly more setup complexity than Flask. Acceptable given async requirements.
**Dependency added:** `fastapi`, `uvicorn[standard]`

---

## D005 — Pydantic-settings for ENV validation
**Date:** 2026-05-21
**Decision:** Use `pydantic-settings` to declare and validate all required ENV vars at startup.
**Rationale:** Fail-fast on missing config, type coercion, clean settings object passed through the app.
**Dependency added:** `pydantic-settings`

---

## D006 — Pexels API for stock footage/images (free tier)
**Date:** 2026-05-21
**Decision:** Pexels as primary asset source. Free tier, no watermark.
**Rationale:** Free, adequate quality for POC, no per-request cost.
**Trade-off:** Rate limits on free tier. Handled with retry/backoff.
**Dependency added:** `requests` (HTTP client for Pexels)

---

## D007 — Replicate + Flux for AI image generation fallback
**Date:** 2026-05-21
**Decision:** Replicate API with Flux model as fallback when Pexels returns no result.
**Rationale:** Free tier available, Flux produces high-quality images suitable for documentary style.
**Trade-off:** Generation latency (async polling required). Acceptable as fallback path.
**Dependency added:** `replicate`

---

## D008 — Freesound API for SFX (free tier)
**Date:** 2026-05-21
**Decision:** Freesound API for SFX acquisition.
**Rationale:** Free, large library, API access with attribution.
**Trade-off:** Attribution required. Logged in output metadata.

---

## D009 — FFmpeg for video assembly (Railway-native)
**Date:** 2026-05-21
**Decision:** FFmpeg runs directly on Railway. Assets downloaded to `/tmp` for assembly, output uploaded to Drive.
**Rationale:** No external video service needed. FFmpeg available on Railway Linux containers.
**Trade-off:** Disk/memory usage on Railway during render. Monitor for large productions.

---

## D010 — Music: shared library, manual upload, POC selects first track
**Date:** 2026-05-21
**Decision:** Operator maintains a `/music-library` folder at Drive root. POC pipeline copies the first available track to the run folder. Smart selection logic deferred.
**Rationale:** Unblocks pipeline POC without building a music matching system.
**Trade-off:** Same track may repeat across runs. Acceptable for POC.

---

## D011 — Voiceover: manual operator upload for POC
**Date:** 2026-05-21
**Decision:** Operator records and uploads `.mp3` voiceover to run's `/voiceover` folder via the operator UI before triggering FFmpeg assembly. TTS (ElevenLabs) deferred.
**Rationale:** Unblocks pipeline without building TTS integration. Operator retains control over voice quality.
**Trade-off:** Manual step in pipeline. Deferred epic: ElevenLabs TTS integration.

---

## D012 — Run ID format: `{YYYY-MM-DD}_{operator-slug}`
**Date:** 2026-05-21
**Decision:** Run IDs are `{YYYY-MM-DD}_{slug}` where date is auto-prepended by the pipeline and slug is operator-provided via UI.
**Rationale:** Human-readable, sortable chronologically, unique by design.
**Constraint:** Slug must be lowercase, hyphens only (no spaces or special chars). Validated in UI.

---

## D013 — Step checkpointing via run_log.json
**Date:** 2026-05-21
**Decision:** `run_log.json` in the run folder tracks each step's status (`pending`/`complete`/`failed`). On restart, pipeline resumes from first incomplete/failed step.
**Rationale:** Enables reliable retry without re-running completed steps. Critical for expensive steps (AI generation, FFmpeg render).

---

## D014 — No UI framework; plain HTML/JS
**Date:** 2026-05-21
**Decision:** Operator UI is plain HTML/JS, no frontend framework.
**Rationale:** Minimal operator UI; framework overhead not justified. Served statically from FastAPI.
**Constraint:** No React, Vue, or similar. Vanilla JS only.

---

## D015 — Google service account JSON stored as base64 ENV var *(superseded by D021 — R2 migration)*
**Date:** 2026-05-21 (superseded 2026-05-22 by D021)
**Decision:** ~~`GOOGLE_SERVICE_ACCOUNT_JSON` ENV var holds the base64-encoded contents of the service account JSON file. Decoded at startup.~~
**Status:** Superseded. Storage migrated to Cloudflare R2 (D021). `GOOGLE_SERVICE_ACCOUNT_JSON` is no longer used or required. See D021 for current storage auth approach.

---

## D017 — Model selection policy (task-based routing)
**Date:** 2026-05-21
**Decision:** Claude API calls are routed to different models based on task type. No hardcoded model strings in modules — all routing goes through `src/utils/model_router.py` (E8-S4).

| Task type | Model | Rationale |
|-----------|-------|-----------|
| `VALIDATE` — schema checks, field validation | `claude-haiku-4-5-20251001` | Structured, low-complexity; cost matters at scale |
| `TRANSFORM` — storyboard → asset manifest | `claude-haiku-4-5-20251001` | Pure structured transformation, no reasoning required |
| `SUMMARIZE` — run_log.json → run_log.txt | `claude-haiku-4-5-20251001` | Template-like output, no creativity required |
| `GENERATE` — script → storyboard (prompt v0.4) | `claude-sonnet-4-6` | Creative + structured; quality matters for output |
| `REASON` — sprint review, architecture decisions | `claude-opus-4-7` | Highest complexity; used outside the pipeline |

**Rationale:** Haiku is sufficient for deterministic transformation tasks. Sonnet handles the core creative/structured generation. Opus reserved for high-stakes reasoning outside the production pipeline.
**Constraint:** Model strings must never be hardcoded in individual modules. Always use `ModelRouter` with task type constants.
**Override:** Each task type's model is overridable via `MODEL_<TASK_TYPE>` ENV var for testing and cost tuning.

---

## D021 — Migrate storage from Google Drive to Cloudflare R2
**Date:** 2026-05-22
**Decision:** Replace Google Drive (with OAuth refresh token auth) with Cloudflare R2 as the pipeline storage layer.
**Rationale:**
- Service accounts have no storage quota on personal Google Drive (HTTP 403 — D020)
- OAuth refresh token requires a human-in-the-loop consent flow, which is incompatible with autonomous Claude Code operation and adds ongoing maintenance burden (token expiry, re-auth)
- Cloudflare R2 uses static API token auth: 3 ENV vars, no expiry, no consent flow, no quota issues on personal accounts
- R2 is S3-compatible — boto3 works out of the box with a custom endpoint URL
- Free tier: 10 GB storage, 1M Class A operations/month — sufficient for POC
**Endpoint format:** `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`
**No real folders:** R2 is a flat key-value store. Run "folders" are key prefixes (e.g. `runs/2026-05-22_test-affordability/`). No folder creation needed.
**Updates:** D003 and D020 revised to reflect final decision.
**Dependency added:** `boto3` (replaces all google-* libraries)

---

## D020 — OAuth refresh token (superseded by D021)
**Date:** 2026-05-22 (superseded 2026-05-22 by D021 — R2 migration)
**Decision:** Authenticate with Google Drive using a stored OAuth 2.0 refresh token (`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_REFRESH_TOKEN`) instead of a service account JSON key.
**Rationale:** Service accounts have no personal Drive storage quota — uploads fail with HTTP 403 `storageQuotaExceeded` on personal Google accounts. Shared Drives (which solve the quota issue) require Google Workspace, which the operator does not have.
**Alternatives rejected:**
- Shared Drive — requires Google Workspace (Enterprise). Not available on personal accounts.
- OAuth delegation — requires Workspace admin and domain-wide delegation. Not available.
- Raw REST calls — same quota limitation applies; no benefit over SDK.
**How:** One-time local flow via `scripts/get_drive_token.py` (uses `google-auth-oauthlib`). Refresh token is long-lived unless revoked. Publish the OAuth consent screen to Production mode to remove the 7-day Testing-mode expiry.
**Dependency added:** `google-auth-oauthlib>=1.2.0` (local script only; production code uses `google.oauth2.credentials.Credentials` from the existing `google-auth` package).
**Updates:** D003 revised — service account JSON auth replaced by OAuth refresh token approach.

---

## D019 — Human Touchpoint Rule adopted into APEX-DEV methodology
**Date:** 2026-05-22
**Decision:** Every sprint must deliver at least one artifact a non-technical stakeholder can interact with. If a sprint is purely infrastructure, a minimal UI shim or smoke-test endpoint must be added before the sprint is finalized.
**Rationale:** Avoid multi-sprint infrastructure builds with zero stakeholder visibility. Catching UX and integration assumptions early is cheaper than discovering them after the pipeline is complete.
**Applied retroactively:** E6-S0 (Minimal run creation UI, 2 points) added to Sprint 1 to satisfy this rule — Sprint 1 was otherwise pure backend infrastructure.
**Enforcement:** Added to `sprint-review.md` step 6 (sprint planning) as a required check. Also documented in `CLAUDE.md` under Hard Constraints.

---

## D018 — Google Drive SDK choice *(superseded by D021 — R2 migration)*
**Date:** 2026-05-22 (superseded 2026-05-22 by D021)
**Decision:** ~~Use `google-api-python-client` + `google-auth` + `google-auth-httplib2` for all Google Drive operations.~~
**Status:** Superseded. Storage migrated to Cloudflare R2 (D021). All Google Drive SDK dependencies removed. Current storage client is `boto3` (S3-compatible, targeting R2 endpoint). See D021.

---

## D016 — Client-side Claude API calls in script-generator.html
**Date:** 2026-05-21
**Decision:** `tools/script-generator.html` calls the Claude API directly from the browser using the `anthropic-dangerous-client-side-api-key-allowed` header. Acceptable for local `/tools` use only.
**Rationale:** Standalone operator tool, opened locally, no server required. Browser-direct is the simplest and correct architecture for this use case.
**Constraint:** If Step 2a (script generation) is ever integrated into the Railway operator UI, the Claude API call must move server-side to avoid exposing the API key in a shared web context.
**Status:** Deferred — out of scope for current epics. Integration is not planned.
