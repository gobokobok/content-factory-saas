> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI Created style → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprint P12 complete** (2026-10-03). **Next sprint:** P13 — Storyboard control (stories not yet written — groom first).

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P17)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D101 · **Stories:** BACKLOG_ACTIVE.md (last completed sprint + upcoming outlines), BACKLOG.md (full archive).
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
| P13 | Storyboard control | ~14 | planned | Change a scene from image to video, split and merge scenes, then acquire |
| P13b | CapCut export (second render path) | ~10 | planned | Download a finalized storyboard, run one command on the laptop, open the full edit in CapCut |
| P14 | AI Created style | ~13 | planned | Pick AI Created, write a mood prompt, get a generated image on every scene |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **P10-S2 smoke test — DEFERRED.** Swap one scene's asset from Studio (thumbnail fill + pencil modal) on a DEV run. Clears in P13, whose human touchpoint works in the same storyboard table. Deferred smoke tests: **1** (groomed 2026-10-03; seven others cleared by the operator by name).
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.

---

# Sprint P13 — Storyboard control

**Goal:** The storyboard becomes a human gate (D095): per-scene asset strategy is editable before anything is acquired, and scenes can be split and merged.
**Status:** planned — stories not yet written. Epic outline: BACKLOG_ACTIVE.md, EPIC 44.
**Points:** ~14

**Human touchpoint:** change a scene from image to video, split and merge scenes, then acquire — and swap one scene's asset afterwards (clears the P10-S2 deferral).
