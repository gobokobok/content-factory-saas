> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI images per scene → P14b Uploaded voiceover → P-UX3 UI/UX redesign → UI build → Multi-language: Russian → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprints P12 and P13 complete** (2026-10-03). **Sprint P13b complete** (2026-10-04). **Sprint P14 complete** (2026-10-05). **Sprint P14b complete** (2026-10-07). **Roadmap change 2026-10-05 (operator, at the P14 review):** two sprints go ahead of P15 — **P14b Uploaded voiceover**, then **P-UX3 UI/UX redesign (discovery and design)**, then the build sprint(s) for the new UI, then **Multi-language: Russian** (EPIC 53), then P15 Research. **Current sprint:** none active — next is P-UX3 (`/start-story P-UX3-S1..S4`).

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
| P14 | AI images per scene | 14 | done | Write a prompt in a scene's edit-image dialog, press Generate, get an AI image for that scene |
| P14b | Uploaded voiceover | ~13 | done | Upload an mp3, correct a misheard word, build the storyboard from it, render |
| P-UX3 | UI/UX redesign — discovery and design | ~11 | planned | Click through a prototype of project → idea → run and approve or redirect it |
| UI build | Build the redesigned UI | tbd | planned (sized in P-UX3-S4) | The new Studio, live on DEV |
| P-LANG | Multi-language: Russian (EPIC 53) | tbd | planned (after the UI build) | Create a Russian run and render a video with Russian voice, captions and on-screen text |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Deferred smoke tests: 0.** (P14b smoke passed on two real runs; its unverified items are listed in DONE.md, not deferred.)
- **PROD is five sprints behind DEV.** PROD runs v0.24.0 (`edc92ba`); P12, P13, P13b, P14 and P14b (including migrations `0002_projects_shortlist.sql` and `0003_tenant_settings.sql`, and the new `SETTINGS_ENCRYPTION_KEY`) are on DEV only. Operator action: `/release`, with `/prod-check` first.
- **Security audit never run** — there is no `docs/SECURITY.md`. P12 added the tenant / project model and 2026-07-26 changed login handling. Operator action: `/audit`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **API keys in DEV logs (found 2026-10-05, P14 smoke) — code fixed in P14b-S5 (2026-10-07), operator actions open:** (1) rotate the Pixabay key on DEV and revoke the old one — the key is still in Railway's DEV log history; do the same on PROD at release; (2) check the DEV log for `key=` (should now read `key=REDACTED`) and re-check PROD at the next `/prod-check`, before `/release`. Fold into `/audit` if that is run first.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

---

# Sprint P14b — Uploaded voiceover

**Goal:** A run can start from a voiceover the operator uploads instead of a script. Deepgram transcribes and aligns it; the transcript becomes the run's script; the storyboard is built from it, and render and CapCut export work unchanged.
**Status:** complete 2026-10-07 (planned 2026-10-05 at the Sprint P14 review, built in one pass, commit `dbec47d`). Smoke: two real Shorts on DEV, no issues; guards, re-upload confirm, `ru` and the log check not verified (see DONE.md).
**Points:** ~13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P14b-S1 | Run creation choice and language seed, VO upload, Deepgram transcript stored as the run's script | 3 | done |
| P14b-S2 | Transcript review stage with timing-safe word edits | 3 | done |
| P14b-S3 | Storyboard from the transcript; uploaded audio feeds timeline, render and CapCut export | 3 | done |
| P14b-S4 | Guards and end-to-end tests | 2 | done |
| P14b-S5 | Stop logging API keys (httpx INFO URLs), rotate the Pixabay key | 2 | done |

**Execution order:** S1 → S2 → S3 → S4; S5 is independent.

**Decisions (operator, 2026-10-05):** (1) the choice is made at run creation — "Script → generated voice" or "Upload voiceover"; the upload path skips the Script and Voice stages. Switching inside an existing run is out of scope. (2) The transcript is editable before the storyboard, under the **timing-safe edit rule**: replace a word (keeps its time slot); one word to several or several to one (share the combined slot); no deleting spoken words; no adding words that are not spoken (use on-screen text). Scene boundaries move only through the Storyboard controls. (3) **Language seed (2026-10-05):** a run carries `language` (default `en`, per-run, never locked by the project's earlier runs); P14b passes it to Deepgram and builds nothing Russian-specific — the Russian sprint (EPIC 53) follows the UI build; AI image prompts stay English in any language. (4) The keys-in-logs fix rides in this sprint so it does not wait for P15. (5) `/audit` stays ahead of P15, after the redesign settles the project and settings model.

**Human touchpoint:** the operator creates a run with "Upload voiceover", uploads an mp3, corrects a misheard word, builds the storyboard and renders a video.

**Operator actions beside the sprint (not stories):** `/prod-check` then `/release` of P12–P14 (timing not decided); at release set a new `SETTINGS_ENCRYPTION_KEY` on PROD; `/audit` before P15.

## Scope changes

_None._
