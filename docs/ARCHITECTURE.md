# Architecture — Content Factory

> ## ⚑ v2 Platform direction (active as of 2026-06-12)
> The authoritative design for the current direction is **docs/v2_platform_plan.md** (decisions D047–D057). A `platform/` layer is being built **alongside** the legacy `src/` pipeline, which stays untouched and is reached only through `platform/adapters/legacy_video.py` (`platform → adapter → src`, one-way; D047).
>
> **Orchestration engine:** **LangGraph** + Postgres checkpointer (D052 — **supersedes Inngest/D042** referenced in §3 below).
>
> **LangGraph abstraction model (D056/D057):**
> - **Worker = Node** (atomic, stateless, pure state-transformer) · **Stage = StateGraph** · **Platform = Graph-of-graphs**
> - A worker emits **exactly one artifact** per execution (written by the observability wrapper, not the worker body).
> - **Artifacts are the durable truth** (R2, indexed in Postgres); **state is a message bus** carrying only artifact references + control signals — never bodies, never a free-form mutation channel.
> - IO adapters (source adapters, legacy adapter) emit **trace events**, not artifacts.
>
> Sections §1–§3 below describe the legacy system and the pre-v2 target and are retained for history.

---

## Document status
This document tracks three layers:
1. **Current state** — what is deployed and working today
2. **Sprint 13–19 evolution** — planned changes that build the foundation
3. **Target architecture (Sprint 20+)** — the multi-agent autonomous content factory

---

## 1. Current state (Sprints 1–12, deployed)

### System overview

Content Factory is a FastAPI service on Railway. The operator triggers each pipeline step via a browser UI. State is persisted to Cloudflare R2 after every step. A single `run_log.json` file is the checkpoint record.

```
Operator (browser)
       │
       ▼
FastAPI (Railway DEV / PROD)
       │
       ├─ POST /runs                      → creates run prefix in R2
       ├─ POST /runs/{id}/alignment       → Deepgram word timestamps → alignment.json
       ├─ POST /runs/{id}/storyboard      → Claude API (Sonnet) → storyboard.json
       ├─ POST /runs/{id}/manifest        → storyboard → asset_manifest.json
       ├─ POST /runs/{id}/assets          → Pexels → Replicate fallback → assets in R2
       ├─ POST /runs/{id}/ffmpeg-script   → asset_manifest → ffmpeg_script.sh
       ├─ POST /runs/{id}/render          → FFmpeg subprocess → output/final.mp4
       ├─ POST /runs/{id}/metadata        → Claude Haiku → metadata.json
       └─ GET  /runs/{id}/artifact/{step} → presigned R2 URL for download
              │
              ▼
       Cloudflare R2 (per-run prefix)
       runs/{run_id}/
         alignment.json
         storyboard.json
         asset_manifest.json
         ffmpeg_script.sh
         run_log.json
         voiceover/
         images/
         video/
         output/final.mp4
         metadata.json
```

### Current pipeline data flow

```
[VO upload]
     │
     ▼  Deepgram Nova-2
alignment.json  (word-level timestamps)
     │
     ▼  Claude Sonnet — prompt v0.8 (receives timestamps)
storyboard.json  (scenes with real start_ms/end_ms)
     │
     ▼  deterministic transform
asset_manifest.json  (one entry per scene: queries, ai_prompt, status)
     │
     ▼  Pexels API → Replicate/Flux fallback (sequential, per-scene)
assets/  (images + video clips in R2)
     │
     ▼  ffmpeg_builder.py (pure function)
ffmpeg_script.sh
     │
     ▼  FFmpeg subprocess on Railway (sync HTTP, 60s timeout risk)
output/final.mp4
     │
     ▼  Claude Haiku
metadata.json  (titles, descriptions, hashtags)
```

### Component map

| Component | File | Responsibility |
|-----------|------|----------------|
| App entry | `src/main.py` | Router registration, startup validation, lifespan hooks |
| Config | `src/config.py` | pydantic-settings, all ENV vars |
| Schemas | `src/models.py` | All Pydantic models |
| Storage | `src/storage.py` | R2Client — upload, download, presigned URLs |
| Alignment | `src/alignment.py` | Deepgram API call, proportional fallback |
| Storyboard | `src/storyboard.py` | Claude API, response parsing, validation |
| Manifest | `src/manifest.py` | Storyboard → AssetManifest transform |
| Pexels | `src/pexels.py` | Stock footage/photo queries + CLIP reranking |
| Replicate | `src/replicate_client.py` | Flux image generation |
| Acquisition | `src/acquisition.py` | Per-scene fallback orchestrator |
| CLIP | `src/clip_reranker.py` | Semantic reranking of Pexels results |
| FFmpeg builder | `src/ffmpeg_builder.py` | Generate ffmpeg_script.sh |
| Captions | `src/captions.py` | ASS subtitle generation (word-synced) |
| Renderer | `src/renderer.py` | Download assets, run FFmpeg, upload output |
| Model router | `src/model_router.py` | Centralised Claude model selection + cost logging |
| Metadata | `src/metadata_generator.py` | Claude Haiku publishing metadata |
| Operator UI | `src/static/pipeline.html` | Single-page pipeline UI |

### Checkpointing

`run_log.json` is written after every step. On restart, the pipeline resumes from the first non-`complete` step.

```json
{
  "run_id": "2026-06-01_housing-affordability",
  "steps": {
    "alignment":        { "status": "complete" },
    "storyboard":       { "status": "complete" },
    "asset_manifest":   { "status": "complete" },
    "asset_acquisition":{ "status": "failed", "error": "Pexels rate limit" },
    "ffmpeg_script":    { "status": "pending" },
    "render":           { "status": "pending" },
    "metadata":         { "status": "pending" }
  },
  "cost_log": []
}
```

---

## 2. Sprint 13–19 evolution

These sprints build the foundation that the target architecture requires. Nothing built here gets discarded — it is all additive.

### Sprint 13 — Scale Foundation

| Change | Impact |
|--------|--------|
| Chunked storyboard generation | Removes ~50-scene ceiling; any script length supported |
| Parallel asset acquisition (`asyncio.gather`) | 300-scene acquisition: 15 min → 30 sec |
| Background render + polling endpoint | Render > 60s no longer times out on Railway |

After Sprint 13 the pipeline handles full-length videos (10–15 min) without operator intervention during each step.

### Sprint 14–16 — Creative Draft + Source Expansion + Assets UX

| Change | Impact |
|--------|--------|
| Editable storyboard cells + Asset Mode per scene | UI becomes a human review/override layer, not just a viewer |
| Per-scene `source_type` (realistic vs historic) | AI decides primary source; Wikimedia added for archival scenes |
| Pixabay as second stock source | Acquisition chain: Pexels → Pixabay → Replicate |
| Per-asset upload replacement | Human override at the asset level |
| Visual Style Prompt injected into every AI call | Operator controls generation style globally |

### Sprint 17 — Project Report + Token Tracking

Token cost logged per Claude call to `run_log.json`. Final `report.json` step aggregates cost, asset sources, render time, video stats.

### Sprint 18 — API-First Pipeline

```
POST /api/pipeline
  body: { script, project_name, settings, webhook_url? }
  returns: { run_id, status_url }   ← 202 immediately

GET /api/pipeline/{run_id}
  returns: { status, steps, download_url? }

Webhook fires: { run_id, download_url, status }
```

This is the external entry point for N8N, Make, Zapier, and the Sprint 20+ agent orchestrator. Every future agent calls this endpoint. Bearer-token auth (`API_KEY` ENV var).

### Sprint 19 — Multi-tenant + Google OAuth

Per-user R2 isolation (`runs/{user_id}/{run_id}/`). Required before social publishing (each user has their own YouTube/Instagram OAuth tokens).

---

## 3. Target architecture — Sprint 20+ (multi-agent autonomous factory)

### Vision

```
Input:  Topic / Niche
Output: Video published to YouTube, Instagram, TikTok
Human:  Optional review gates (can be fully autonomous)
```

### Agent graph

```
┌──────────────────────────────────────────────────────────────┐
│  Agent 0 — Trend Research                                    │
│  Tools: web_search, Reddit API, Google Trends, NewsAPI       │
│  Output: Top 3 viral ideas + supporting context              │
└─────────────────────────┬────────────────────────────────────┘
                          │
          ┌───────────────▼───────────────────────────────────┐
          │  Agent 1 — Script Writer                          │
          │  Loop: write × 3 → score virality → fact-check   │
          │  Tools: web_search (fact verification)            │
          │  Output: 1 polished, fact-checked script          │
          └───────────────┬───────────────────────────────────┘
                          │
          ┌───────────────▼───────────────────────────────────┐
          │  Agent 2 — Storyboard                             │
          │  Loop: generate → self-critique → refine          │
          │  until score > threshold                          │
          │  Output: storyboard.json                          │
          └───────────────┬───────────────────────────────────┘
                          │
          ┌───────────────▼───────────────────────────────────┐
          │  Agent 3 — Asset Acquisition                      │
          │  Per scene: multi-source search → score → return  │
          │  2–3 candidates (CLIP-ranked)                     │
          │  [Optional human/agent review gate]               │
          │  Output: asset_manifest.json                      │
          └───────────────┬───────────────────────────────────┘
                          │
          ┌───────────────▼───────────────────────────────────┐
          │  Agent 4 — Render + Publish                       │
          │  FFmpeg → final.mp4                               │
          │  → YouTube / Instagram / TikTok APIs              │
          └───────────────────────────────────────────────────┘
```

### Orchestration engine

> **Superseded:** the orchestration engine is now **LangGraph + Postgres checkpointer** (D052), not Inngest. The paragraph below is retained for history.

The current `FastAPI BackgroundTasks` pattern (Sprint 13) is replaced by **Inngest** — a managed durable workflow engine (see D042). Each agent step becomes an Inngest function:

- Survives Railway restarts and deploys mid-run
- Built-in retry with exponential backoff
- `step.waitForEvent("asset-review-approved", timeout="24h")` for human-in-the-loop gates
- Event-driven chaining: each agent fires an event when done; the next agent picks it up

The FastAPI app registers Inngest function handlers at startup. The `/api/pipeline` endpoint (Sprint 18) fires the initial Inngest event instead of spawning a BackgroundTask — **one line change in the route handler**; all domain functions are unchanged.

### Human-in-the-loop gates

Every review gate is the same pattern:

```
Agent pauses → emits needs_review event
     │
     ▼
UI shows candidates (existing assets table / new review UI)
     │
     ▼  operator approves or overrides
POST /runs/{run_id}/review → fires Inngest resume event
     │
     ▼
Agent continues
```

Timeout: if no review arrives within configurable window (default 24h), gate auto-approves and pipeline continues.

### Asset candidate API (Agent 3 review)

```
GET  /runs/{run_id}/scenes/{scene_id}/candidates
     returns: [{ source, thumbnail_url, relevance_score, metadata } × 3]

POST /runs/{run_id}/scenes/{scene_id}/candidates/{candidate_id}/select
     → stores selected file_key in manifest, fires resume event
```

### Social publishing

Each platform requires per-user OAuth tokens stored alongside the user profile in R2 (`users/{user_id}/tokens/{platform}.json`). Sprint 19 (Google OAuth) is a hard prerequisite — it establishes the user identity and session that social tokens attach to.

| Platform | API | Notes |
|----------|-----|-------|
| YouTube | YouTube Data API v3 | OAuth 2.0, well-documented |
| Instagram | Instagram Graph API | Requires Facebook Business account |
| TikTok | Content Posting API | Requires app approval process |

### Why sprints 13–19 don't conflict with this vision

| Sprint 13–19 artifact | Role in Sprint 20+ |
|-----------------------|--------------------|
| Chunked storyboard (S13-S1) | Foundation for Agent 2's parallel chunk calls |
| Parallel acquisition (S13-S2) | Foundation for Agent 3's batched multi-source search |
| Background render (S13-S3) | Pattern that Inngest wraps directly |
| API-first pipeline (S18) | Entry point for all external agent calls |
| Webhook callback (S18-S4) | Inter-agent notification pattern |
| Google OAuth (S19) | Identity layer for social platform OAuth tokens |
| Per-user R2 isolation (S19) | Per-user content isolation at scale |

### Key constraint that enables this evolution

All pipeline step functions are written as **pure async functions** (see CONVENTIONS.md § Async function discipline, D040). They take explicit inputs and return explicit outputs with no coupling to the HTTP request context. This means:

- The same `generate_storyboard()` function is called by the FastAPI route today and by the Inngest agent in Sprint 20+.
- No rewrites needed when the orchestration layer changes.
- Functions can be called in parallel, in loops, and from external orchestrators without modification.

---

## Environment isolation

| Env | Deploy trigger | Railway service | R2 bucket |
|-----|---------------|-----------------|-----------|
| Local | `.env.local` | — | `content-factory-dev` |
| DEV | Push to `main` | `content-factory-dev` | `content-factory-dev` |
| PROD | Git tag `v*.*.*` | `content-factory-prod` | `content-factory-prod` |

DEV and PROD point to separate R2 buckets. No shared state between environments.
