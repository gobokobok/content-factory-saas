> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-06-13 the active work is the **Platform v2 track (Sprints P0–P7)**, defined at the end of this file and in **docs/v2_platform_plan.md** (decisions D047–D057).
> - **Sprint P1 complete** (16/16 pts). **Sprint P2 complete** (16/16 pts). **Sprint P3 complete** (10/10 pts). **Sprint P4 complete** (13/13 pts). **Sprint P5 complete** (24/24 pts — all 6 stories done including P5-S6 Blueprint IR rearchitect; DEV smoke test pending deploy). **Current sprint:** P6 — Orchestrator + Legacy Bridge. **Next:** P6-S1.
> - Sprints **S14–S17** (video-UX polish) are **PAUSED** — they resume later behind the legacy adapter.
> - The legacy Script→Video pipeline (Sprints 1–13) keeps running in DEV/PROD, untouched (D047).
> - Full history: **SPRINT_ARCHIVE.md** (Sprints 1–19 + Platform P0–P4).

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P7)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D057 · **Stories:** BACKLOG_ACTIVE.md (current + next sprint), BACKLOG.md (full archive).
Legacy Script→Video stays untouched and operable (D047).

| Sprint | Theme | Pts | Status | Human touchpoint |
|--------|-------|-----|--------|-----------------|
| P0 | Boundary design & contracts | 13 | done | Approve spec + schemas |
| P1 | Platform skeleton & core | 16 | done | `POST /platform/echo` → artifact in R2 |
| P2 | Lineage & observability store | 16 | done | Per-worker cost/latency/version; resume after restart |
| P3 | Telegram trigger + Discovery worker | 10 | done | `/ideas <niche>` → signals in Telegram |
| P4 | Niche→Ideas block | 13 | done | Telegram niche → ranked ideas w/ scores |
| **P5** | **Idea→Script block** | **24** | **active** | Telegram idea → fact-checked script |
| P6 | Orchestrator + legacy bridge | 19 | planned | `/produce <niche>` → finished video |
| P7 | Analytics & attribution | 11 | planned | Retention-by-prompt-version report |

**MVP (P0–P6) = 111 pts; with P7 = 122 pts.**

---

# Sprint P5 — Idea→Script Block

**Goal:** P5-S1–S5 built the cyclic loop (shipped); P5-S6 rearchitects as Blueprint IR + single-pass + patch repair (target $0.05–$0.10/run).
**Status:** active
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

**Goal:** Parent graph chains niche→ideas → idea→script → legacy render via the adapter; optional HITL gates; one command → video.
**Status:** planned
**Points:** 13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P6-S1 | Legacy adapter (interface + in-process impl) | 3 | done |
| P6-S2 | Legacy-as-node + parent graph (+ PipelineState) | 5 | done |
| P6-S3 | Human-in-the-loop gates | 3 | planned |
| P6-S4 | End-to-end /produce → video | 2 | planned |
| P6-S5 | Target duration parameter (run-level → script writer) | 3 | done |
| P6-S6 | Niche-aware prompts (replace hardcoded channel) | 3 | done |

**Execution order:** (P6-S1 ∥ P6-S5 ∥ P6-S6) → P6-S2 → (P6-S3 ∥ P6-S4). P6-S3 needs P2-S4. P6-S2 must add `PipelineState.target_duration_seconds` and pass it to `IdeaToScriptState`.

## Sprint P6 Definition of Done
- [ ] Only the adapter imports `src/`; legacy unchanged and still operable
- [ ] One run threads lineage across blocks + legacy node
- [ ] **Human touchpoint:** operator runs `/produce <niche>` and downloads the finished video

---

# Sprint P7 — Analytics & Attribution

**Goal:** Close the loop — which prompt/worker version produced higher-retention videos.
**Status:** planned
**Points:** 11

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P7-S1 | Publish linkage capture | 3 | planned |
| P7-S2 | YouTube analytics ingestion worker | 5 | planned |
| P7-S3 | Attribution query + report | 3 | planned |

**Execution order:** P7-S1 → P7-S2 → P7-S3.

## Sprint P7 Definition of Done
- [ ] `published_videos` + `video_metrics` populated; lineage join works
- [ ] **Human touchpoint:** operator reads a report ranking prompt versions by retention
