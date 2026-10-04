> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI Created style → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprints P12 and P13 complete** (2026-10-03). **Sprint P13b complete** (2026-10-04). **Current sprint:** P14 — AI Created style, stories P14-S1..S4.

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P17)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D102 · **Stories:** BACKLOG_ACTIVE.md (last completed sprint + upcoming outlines), BACKLOG.md (full archive).
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
| P9 | Storyboard v2 + native engine rebuild | ~18 | done | `/run` → fully native pipeline; timestamp-first captions; film look; OST overlays |
| P10 | Production quality + Visual Intelligence Layer | ~15 | done | No food assets for "protein"; researcher portrait from Wikimedia; per-scene asset override in Studio |
| P-UX1 | Studio UX redesign | 14 | done | Run list → Settings → pipeline through to Metadata |
| P-UX2 | Render & narration controls | 15 | done | Caption style preset, per-scene motion dropdown, TTS pace + register |
| P11 | Visual Director + motion effects | 6 | closed | Visual Director agent (S1). S2/S3 parked (D099) |
| P12 | Projects & shortlist | 16 | done | Open Studio → project list → add a shortlist idea by hand → create a run from it |
| P13 | Storyboard control | 14 | done | Change a scene from image to video, split and merge scenes, then acquire |
| P13b | CapCut export (second render path) | 11 | done | Download a finalized storyboard, run one command on the laptop, open the full edit in CapCut |
| P14 | AI Created style | 13 | current | Pick AI Created, write a mood prompt, get a generated image on every scene |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Deferred smoke tests: 0.**
- **PROD is three sprints behind DEV.** PROD runs v0.24.0 (`edc92ba`); P12, P13 and P13b (including migration `0002_projects_shortlist.sql`) are on DEV only. Operator action: `/release`, with `/prod-check` first.
- **Security audit never run** — there is no `docs/SECURITY.md`. P12 added the tenant / project model and 2026-07-26 changed login handling. Operator action: `/audit`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

# Sprint P14 — AI Created style

**Goal:** A run can use AI-generated images instead of stock footage: the operator picks the AI Created style and a mood prompt and gets a generated image on every scene, or switches single scenes to AI image in any style (D096). Stock acquisition and both render paths keep working unchanged.
**Status:** current — planned 2026-10-04 at the Sprint P13b review. Built in one pass (`/start-story P14-S1..S4`).
**Points:** 13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P14-S1 | Provider side-by-side test, `ImageProvider` interface and kie.ai client | 4 | todo |
| P14-S2 | "AI Created" style, mood prompt in Settings, Visual Director prompt branch | 4 | todo |
| P14-S3 | Per-scene "AI image" strategy with an editable prompt, usable in any style | 3 | todo |
| P14-S4 | Per-run spend cap and cost display in Studio | 2 | todo |

**Execution order:** S1 → S2 → S3 → S4 (S3 and S4 can swap).

**Open questions — decide at the start of the sprint, before S1 is built** (they are recorded in BACKLOG_ACTIVE.md, EPIC 45, and each answer goes to DECISIONS.md):
1. Which OpenAI quality tier kie.ai's price corresponds to (D096: unverified) — settled by the S1 side-by-side test on five real scene prompts.
2. A consistent look across scenes: a style reference image, or the prompt alone.
3. How Studio reaches the Visual Director, which only `full_pipeline.py` runs today (P13 handover).
4. The spend cap: its default, whether it is per run or per project, and what happens when it is hit (stop, or ask).

**Why a spend cap is in the sprint:** this is the first paid path in the project (D096 narrows the free-tier rule). It was an open question in the outline; S4 settles it before the cap matters.

**Human touchpoint:** the operator picks AI Created, writes a mood prompt and gets a generated image on every scene; then switches one scene to "AI image" in a stock-style run and edits its prompt.

**Operator actions beside the sprint (not stories):** `/prod-check` then `/release` of P12 + P13 + P13b (timing not yet decided); provision the new image-provider ENV keys on DEV before S1 and on PROD at release; `/audit` before P16 at the latest.

## Scope changes

_None._
