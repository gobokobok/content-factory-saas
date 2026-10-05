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
| P14 | AI Created style | 14 | done | Write a prompt in a scene's edit-image dialog, press Generate, get an AI image for that scene |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Deferred smoke tests: 0.**
- **PROD is four sprints behind DEV.** PROD runs v0.24.0 (`edc92ba`); P12, P13, P13b and P14 (including migrations `0002_projects_shortlist.sql` and `0003_tenant_settings.sql`, and the new `SETTINGS_ENCRYPTION_KEY`) are on DEV only. Operator action: `/release`, with `/prod-check` first.
- **Security audit never run** — there is no `docs/SECURITY.md`. P12 added the tenant / project model and 2026-07-26 changed login handling. Operator action: `/audit`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **Open decision (found 2026-10-05, P14 smoke): API keys appear in DEV logs.** `httpx` INFO logging prints the full Pixabay key inside request URLs (`pixabay.com/api/?key=…`), so it sits in Railway's DEV log history. Operator has chosen to carry on and decide later. To settle: (1) rotate the Pixabay key; (2) stop it recurring by redacting `key=` values in logs or raising `httpx` to WARNING — a task chip was raised ("Stop logging the Pixabay API key in INFO logs"). Check PROD logs for the same before `/release`. Fold into `/audit` if that is run first.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

# Sprint P14 — AI Created style

**Goal:** The operator can generate an AI image for any scene from the storyboard: open the scene's edit-image dialog, write a prompt, press Generate (D104). Nothing is generated automatically. Stock acquisition and both render paths keep working unchanged.
**Status:** complete 2026-10-05 (smoke test passed on DEV; spend-cap step covered by automated tests only) — planned 2026-10-04 at the Sprint P13b review; **re-scoped 2026-10-04 at `/start-story`** (operator: manual per-scene generation, optional project-level style, provider keys at tenant level, side-by-side test skipped). Built in one pass.
**Points:** 14

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P14-S1 | `ImageProvider` interface, kie.ai + OpenAI clients, tenant-level provider settings with encrypted API keys (migration 0003, `/settings`) | 6 | done |
| P14-S2 | Settings: provider / model / key page, optional project `ai_image_style` | 3 | done |
| P14-S3 | Per-scene Generate in the storyboard edit-image dialog (prompt field + button), `ai_image` strategy usable in any style | 3 | done |
| P14-S4 | Per-run spend cap, cost display in Studio | 2 | done |

**Execution order:** S1 → S2 → S3 → S4.

**Decisions (all in D104):** (1) the side-by-side provider test is skipped, kie.ai is the default and the model is a setting; (2) look across scenes = optional `ai_image_style` on the project, prepended to every prompt, no reference image; (3) Studio does not call the Visual Director — the prompt field is prefilled from the scene's voiceover and edited by hand; (4) spend cap per run, `IMAGE_RUN_SPEND_CAP_USD` default 2.00, at the cap Generate is refused; (5) provider, model and key are tenant settings (encrypted with `SETTINGS_ENCRYPTION_KEY`), Railway ENV keys are the fallback; (6) new dependency `cryptography` (Fernet).

**Done on DEV:** `SETTINGS_ENCRYPTION_KEY` set, OpenAI key saved in Settings. **At release:** set a different `SETTINGS_ENCRYPTION_KEY` on PROD and save the key there (migration `0003` applies on deploy).

**Human touchpoint:** the operator saves a kie.ai key in Settings, opens a scene's edit-image dialog in a stock run, writes a prompt, presses Generate and sees the image replace the scene's asset, with the run's spend shown against the cap.

**Operator actions beside the sprint (not stories):** `/prod-check` then `/release` of P12 + P13 + P13b (timing not yet decided); set `SETTINGS_ENCRYPTION_KEY` (and the operator's image key in Settings) on PROD at release; `/audit` before P16 at the latest.

## Scope changes

_None._
