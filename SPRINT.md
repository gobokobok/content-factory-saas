> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-06-20 the active work is the **Platform v2 track (Sprints P0–P15)**, defined in **docs/v2_platform_plan.md** (decisions D047–D063).
> - **Sprints P0–P8 complete.** P8-S1 through P8-S6 all done.
> - Sprints **S14–S17** (video-UX polish) are **PAUSED** — they resume later behind the legacy adapter.
> - The legacy Script→Video pipeline (Sprints 1–13) keeps running in DEV/PROD, untouched (D047).
> - Full history: **SPRINT_ARCHIVE.md** (Sprints 1–19 + Platform P0–P4).
> - **Next sprint:** P9 — Storyboard v2 + native engine rebuild.

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P15)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D063 · **Stories:** BACKLOG_ACTIVE.md (current + next two sprints), BACKLOG.md (full archive).
Legacy Script→Video stays untouched and operable (D047).

| Sprint | Theme | Pts | Status | Human touchpoint |
|--------|-------|-----|--------|-----------------|
| P0 | Boundary design & contracts | 13 | done | Approve spec + schemas |
| P1 | Platform skeleton & core | 16 | done | `POST /platform/echo` → artifact in R2 |
| P2 | Lineage & observability store | 16 | done | Per-worker cost/latency/version; resume after restart |
| P3 | Telegram trigger + Discovery worker | 10 | done | `/ideas <niche>` → signals in Telegram |
| P4 | Niche→Ideas block | 13 | done | Telegram niche → ranked ideas w/ scores |
| P5 | Idea→Script block | 24 | done | Telegram idea → fact-checked script |
| P6 | Orchestrator + legacy bridge | 24 | done | `/produce <niche>` → presigned video URL + confirmed VO sync |
| P7 | Idea selection + YouTube metadata | 8 | done | `/ideas` → 5 numbered ideas → `/pick <run_id> <n>` → 16:9 video + metadata |
| P8 | Footage quality | 14 | done | Footage breakdown in Telegram reply; colour grade applied |
| **P9** | **Storyboard v2 + native engine rebuild** | **~18** | **in-progress** | `/run` → fully native pipeline; person lower thirds; film look for historic scenes |
| P10 | Visual Intelligence Layer | ~12 | planned | Neuroscience run: no food assets for "protein"; researcher portrait from Wikimedia; diversity score in Telegram reply |
| P11 | Multi-asset timelines + motion effects | ~14 | planned | Sub-scene asset cuts; slow push; film grain; animated callouts |
| P12 | Format tracks | ~10 | planned | `documentary`/`educational`/`animated` via `--format` flag |
| P13 | Analytics & attribution | ~11 | planned | Retention-by-prompt-version report |
| P14 | n8n automation | ~10 | planned | Niche → scheduled YouTube upload with no operator action |
| P15 | Multi-tenant SaaS frontend | ~20 | planned | Multi-channel, multi-run operator UI |

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Sprint P5 — Idea→Script Block

**Goal:** P5-S1–S5 built the cyclic loop (shipped); P5-S6 rearchitects as Blueprint IR + single-pass + patch repair (target $0.05–$0.10/run).
**Status:** done
**Points:** 24

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P5-S1 | Script Writer worker (write ×N) | 3 | done |
| P5-S2 | Quality/virality scorer worker | 3 | done |
| P5-S3 | Fact-check tool integration (web search) | 3 | done |
| P5-S4 | Refine loop + convergence logic ⚠️ spike | 5 | done |
| P5-S5 | Assemble idea_to_script graph + interfaces (+ IdeaToScriptState) | 2 | done |
| P5-S6 | Rearchitect Idea→Script — Blueprint IR + single-pass + patch repair | 8 | done |

**Execution order:** P5-S1 → (P5-S2 ∥ P5-S3) → P5-S4 → P5-S5 → P5-S6.

## Sprint P5 Definition of Done
- [ ] Loop converges or stops at `max_iterations`; iteration is a typed state channel (D057)
- [ ] **Human touchpoint:** Telegram idea → fact-checked `script` artifact

---

# Sprint P6 — Orchestrator + Legacy Bridge

**Goal:** Parent graph chains niche→ideas → idea→script → voice → legacy render via the adapter; optional HITL gates; one command → video.
**Status:** done
**Points:** 24

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P6-S1 | Legacy adapter (interface + in-process impl) | 3 | done |
| P6-S2 | Legacy-as-node + parent graph (+ PipelineState) | 5 | done |
| P6-S3 | Human-in-the-loop gates | 3 | done |
| P6-S4 | End-to-end /produce → video | 2 | done |
| P6-S5 | Target duration parameter (run-level → script writer) | 3 | done |
| P6-S6 | Niche-aware prompts (replace hardcoded channel) | 3 | done |
| P6-S7 | Gemini TTS + /testvoice harness | 5 | done |

**Execution order:** (P6-S1 ∥ P6-S5 ∥ P6-S6) → P6-S2 → (P6-S3 ∥ P6-S4) → P6-S7.

## Sprint P6 Definition of Done
- [x] Only the adapter imports `src/`; legacy unchanged and still operable
- [x] One run threads lineage across blocks + legacy node
- [x] **Human touchpoint (P6-S7):** `/testvoice <run_id>` → presigned MP3 URL in ~30s; `/pick <run_id> <n>` → finished video — VERIFIED 2026-06-20 (P8-S0 smoke test sweep)

---

# Sprint P7 — Idea Selection + YouTube Metadata

**Goal:** Operator sees 5 ranked ideas, picks one, and receives a finished 16:9 video with ready-to-paste YouTube metadata (title, description, tags) in a single Telegram flow.
**Status:** done
**Points:** 8

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P7-S1 | Idea selection flow | 3 | done |
| P7-S2 | YouTube metadata worker | 3 | done |
| P7-S3 | Produce with selected idea + metadata reply | 2 | done |

**Execution order:** P7-S1 → (P7-S2 ∥ P7-S3).

## Sprint P7 Definition of Done
- [x] `/ideas <niche>` reply shows 5 numbered ideas
- [x] `/pick <run_id> <n>` triggers the full pipeline for the chosen idea
- [x] Telegram reply includes presigned video URL + YouTube metadata block
- [x] **Human touchpoint:** operator receives a 16:9 video + copy-paste YouTube metadata — VERIFIED 2026-06-20 (P8-S0 smoke test sweep)

---

# Sprint P8 — Footage Quality

**Goal:** Replace the serial Pexels→Replicate fallback with a multi-source merge+rank pipeline (Pexels + Pixabay searched concurrently; Wikimedia Commons added in S2; winner selected by resolution/QA score). Replicate retired. Add real-person photo routing via Wikipedia, gate every clip through a quality check, surface per-source coverage in the Telegram reply, and apply a colour grade to the final render. All `src/` code is written as clean isolated modules for direct import by P9's native AcquisitionWorker.
**Status:** done
**Completed:** 2026-06-20
**Points:** 14

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P8-S1 | Pixabay source — videos + photos | 3 | done |
| P8-S2 | Wikimedia Commons source — historic + general + person photos | 3 | done |
| P8-S3 | Real person detection + Wikimedia person photo routing | 3 | done |
| P8-S4 | Footage QA — per-scene quality gate + retry | 3 | done |
| P8-S5 | Source telemetry + Telegram footage report | 2 | done |
| P8-S6 | Colour grading presets (FFmpeg) | 2 | done |

**Execution order:** (P8-S1 ∥ P8-S6) → P8-S2 → P8-S3 → P8-S4 → P8-S5

## Sprint P8 Definition of Done
- [x] Pexels + Pixabay searched concurrently, winner by resolution; `PIXABAY_API_KEY` in ENV; D063 logged; Replicate retired (P8-S1)
- [x] Wikimedia Commons added to merge pool; historic-first routing; attribution stored per asset (P8-S2)
- [x] Storyboard prompt v0.10: `person_name` + `person_title` fields; PERSON SCENE exceptions; HISTORICAL SCENE exceptions; Wikimedia person photo first; fallback to generic stock on miss (P8-S3)
- [x] Every acquired clip passes resolution + duration + optional CLIP quality gate; retry on `fallback_query`; `CLIP_RERANK_ENABLED` in ENV (P8-S4)
- [x] `asset_manifest.json` records `source`, `qa_passed`, `qa_clip_score`, `fallback_used` per scene (P8-S4)
- [x] `footage_summary.json` written to R2 after acquisition; surfaced in Telegram reply with QA warning (P8-S5)
- [x] Early acquisition check: RuntimeError raised before ffmpeg if any scene has `file_key=None` (P8 hotfix)
- [x] `smart_format=true` for Deepgram — numerals in captions match verbatim script text (D045 revision)
- [x] Script generator prompt enforces word-count RANGE (min + max), not ceiling only
- [x] `COLOR_GRADE_PRESET` in ENV; 5 presets apply correct FFmpeg filter chain; `BLUR_FILL_ENABLED` for landscape stills (P8-S6)
- [x] All `src/` modules (`pixabay_client.py`, `wikimedia_client.py`, `footage_qa.py`) are standalone and importable by P9
- [x] **Human touchpoint:** `/run <niche>` → video + footage coverage line in Telegram reply; colour grade applied; 2:47 video at --duration 167 confirmed 2026-06-20

---

# Sprint P9 — Native Documentary Production Graph

**Goal:** Extract the storyboard→acquisition→render chain from `InProcessLegacyVideoAdapter` into three native LangGraph workers. P9 is a **migration sprint, not an innovation sprint** — every change must either (a) replace existing monolith functionality, or (b) add visible production quality at <10% runtime cost. Defer everything else to P10.
**Status:** in-progress
**Points:** ~18

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P9-S1 | Storyboard schema v2 | 3 | done |
| P9-S2 | Native StoryboardWorker (generate → review → patch internal) | 5 | done |
| P9-S3 | Native AcquisitionWorker | 4 | done |
| P9-S4 | Native RenderWorker (dumb executor — reads render_options) | 4 | done |
| P9-S5 | Retire InProcessLegacyVideoAdapter + wire native pipeline | 2 | done |
| P9-S6 | Portrait/landscape format parameter (`--format` flag) | 2 | done |
| P9-S7 | Caption word assignment by timestamp (drop script text-matching) | 1 | done |
| P9-S8 | Per-scene asset override — custom query re-acquire + operator upload | 4 | todo |
| P9-S9 | Timestamp-first storyboard — word indices + Python-derived duration and asset tier | 5 | done |
| P9-S10 | Asset quality, character sourcing, and OST consistency | 5 | todo |

**Execution order:** P9-S1 → P9-S2 → P9-S3 → P9-S4 → P9-S5 (fully linear). P9-S6 and P9-S7 are independent; can run in parallel after P9-S5.

## Sprint P9 Definition of Done
- [x] `StoryboardScene` schema v2: `segment_type` (3 values), three-tier queries, `on_screen_text_type` (3 values), `render_options` per scene; `historic` and `visual_prompts.ai_generate` removed
- [x] `StoryboardWorker` emits single `verified_storyboard` artifact; internal generate→review→patch cycle; no intermediate artifacts
- [x] `AcquisitionWorker` routes by `segment_type`; three-tier query cascade; P8 src/ modules imported directly; `asset_manifest` + `footage_summary` artifacts written
- [ ] `RenderWorker` reads `scene.render_options` only — no `segment_type` conditionals; persists `render_script.sh`; produces `final.mp4`
- [ ] Caption position awareness: when `render_options.lower_third` active and `subtitles != "none"`, captions shift up via `caption_y_override`
- [ ] Each worker has a standalone REST endpoint for future manual UI (alongside pipeline node wiring)
- [ ] Artifact chain: `verified_storyboard → asset_manifest → render_script.sh → final.mp4`
- [ ] `/run` / `/pick` / `/produce` commands trigger the native chain; `InProcessLegacyVideoAdapter` not in active call path
- [ ] **Human touchpoint:** `/run <niche>` → native render; person lower thirds; film look for historic; on_screen_text overlays for dates and stats

---

# Sprint P10 — Visual Intelligence Layer

**Goal:** Eliminate context-free asset acquisition. The storyboard now carries global topic context and per-scene semantic qualifiers. A dedicated Visual Director agent plans the visual treatment for the full run before any asset is fetched. The acquisition layer becomes a fulfillment layer — it reads a visual plan and executes it, rather than deriving intent from raw query strings.
**Status:** planned
**Points:** ~12

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P10-S1 | Semantic enrichment — global topic context + Entity Resolver + visual deduplication | 6 | todo |
| P10-S2 | Visual Director agent — post-storyboard visual treatment | 6 | todo |

**Execution order:** P10-S1 → P10-S2 (S2 depends on enriched storyboard schema from S1).

## Sprint P10 Definition of Done
- [ ] `verified_storyboard` contains `global_context` block on every run
- [ ] Every scene has `semantic_context` with `primary_concept`, `domain_qualifier`, `avoid`, `visual_tags`
- [ ] `Entity Resolver` deterministically routes Character + historic scenes to Wikimedia; stock/concept scenes to Pexels/Pixabay
- [ ] `visual_treatment` artifact written to R2; `AcquisitionWorker` reads it as primary source of search terms
- [ ] No 3+ consecutive scenes with the same `shot_type`; diversity validator enforced
- [ ] `footage_summary` includes `diversity_score`
- [ ] On a neuroscience-topic run: "protein" scene returns neurological visuals, not food; researcher portrait from Wikimedia
- [ ] **Human touchpoint:** `/run <niche>` → Telegram reply includes `diversity_score`; neuroscience run has no food assets for biological-protein scenes
