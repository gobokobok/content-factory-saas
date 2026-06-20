> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-06-20 the active work is the **Platform v2 track (Sprints P0–P12)**, defined in **docs/v2_platform_plan.md** (decisions D047–D063).
> - **Sprints P1–P7 complete. Sprint P8 active** — P8-S1 done. Next: P8-S2 Wikimedia Commons source.
> - Sprints **S14–S17** (video-UX polish) are **PAUSED** — they resume later behind the legacy adapter.
> - The legacy Script→Video pipeline (Sprints 1–13) keeps running in DEV/PROD, untouched (D047).
> - Full history: **SPRINT_ARCHIVE.md** (Sprints 1–19 + Platform P0–P4).

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P12)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D062 · **Stories:** BACKLOG_ACTIVE.md (current + next two sprints), BACKLOG.md (full archive).
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
| **P8** | **Footage quality** | **~10** | **active** | Operator sees visibly higher-quality clips + footage breakdown in DEV run |
| P9 | Legacy engine rebuild | ~13 | planned | All workers native LangGraph; src/ adapter retired |
| P10 | Analytics & attribution | ~11 | planned | Retention-by-prompt-version report |
| P11 | n8n automation | ~10 | planned | Niche → scheduled YouTube upload with no operator action |
| P12 | Multi-tenant SaaS frontend | ~20 | planned | Multi-channel, multi-run operator UI |

**Core platform (P0–P6) = 116 pts done.**

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
**Status:** active
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
- [ ] **Human touchpoint (P6-S7):** `/testvoice <run_id>` → presigned MP3 URL in ~30s; then `/produce <niche>` → finished video — DEFERRED (requires DEV deploy with `GEMINI_API_KEY`)

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
**Status:** active
**Points:** 16

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P8-S1 | Pixabay source — videos + photos | 3 | done |
| P8-S2 | Wikimedia Commons source — historic + general + person photos | 3 | todo |
| P8-S3 | Real person detection + Wikimedia person photo routing | 3 | todo |
| P8-S4 | Footage QA — per-scene quality gate + retry | 3 | todo |
| P8-S5 | Source telemetry + Telegram footage report | 2 | todo |
| P8-S6 | Colour grading presets (FFmpeg) | 2 | todo |

**Execution order:** (P8-S1 ∥ P8-S6) → P8-S2 → P8-S3 → P8-S4 → P8-S5

## Sprint P8 Definition of Done
- [x] Pexels + Pixabay searched concurrently, winner by resolution; `PIXABAY_API_KEY` in ENV; D063 logged; Replicate retired (P8-S1 done)
- [ ] Wikimedia Commons added to merge pool (P8-S2)
- [ ] Wikimedia Commons covers historic footage (no API key) and general stock photos; D064 logged
- [ ] Storyboard prompt v0.5: `person_name` field emitted when scene depicts a named individual; Wikimedia person photo fetched first for those scenes
- [ ] Every acquired clip passes resolution + duration + optional CLIP quality gate; retry on `fallback_query` before advancing source; `CLIP_RERANK_ENABLED` in ENV
- [ ] `asset_manifest.json` records `source`, `qa_passed`, `qa_clip_score`, `fallback_used` per scene
- [ ] `footage_summary` in `run_log.json`; surfaced in Telegram reply with QA warning when needed
- [ ] `COLOR_GRADE_PRESET` in ENV; `vivid`/`warm`/`cinematic`/`muted`/`neutral` presets apply correct FFmpeg filter chain
- [ ] All `src/` modules (`pixabay_client.py`, `wikimedia_client.py`, `footage_qa.py`) are standalone and importable by P9
- [ ] **Human touchpoint:** operator runs `/run <niche>` on DEV, receives video + `Footage: N Pexels · N Pixabay · N Wikimedia · N Person · N AI` in the Telegram reply; colour grade visibly applied
