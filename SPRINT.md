> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI images per scene → P14b Uploaded voiceover → P-UX3 UI/UX redesign → UI build → Multi-language: Russian → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprints P12 and P13 complete** (2026-10-03). **Sprint P-UX3 complete** (2026-10-11). **Sprint P13b complete** (2026-10-04). **Sprint P14 complete** (2026-10-05). **Sprint P14b complete** (2026-10-07). **Roadmap change 2026-10-05 (operator, at the P14 review):** two sprints go ahead of P15 — **P14b Uploaded voiceover**, then **P-UX3 UI/UX redesign (discovery and design)**, then the build sprint(s) for the new UI, then **Multi-language: Russian** (EPIC 53), then P15 Research. **Current sprint:** P-UX3 — built and pushed to DEV 2026-10-08 (design, prototype and build in one pass, D105); smoke test pending.

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
| P-UX3 | UI/UX redesign — discovery, design, prototype and build | ~11 + build | done | The new UI on DEV: project → idea → run, Libraries, Integrations, Defaults |
| UI build | Build the redesigned UI | — | folded into P-UX3 (2026-10-08, operator request) | The new UI, live on DEV |
| P-AN1 | Animation mode: AI-image videos from a Visual Director storyboard (EPIC 55) | 26 | **done** 2026-10-11 | One sub-minute run in 9:16 and one in 16:9, script to rendered video, generated images in one master style |
| P-UX4 | Pipeline flow and polish (EPIC 56) | ~21 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Create a run from the minimal modal and walk all five steps with Next only |
| P-AUTH | Google sign-in and accounts (EPIC 59); `/audit` first | ~13 | planned | A friend signs in with Google and lands in their own space |
| P-BILL-1 | Usage ledger, credit limits, manual top-up (EPIC 59) | ~13 | planned | **Friends beta:** a friend makes a first video of up to one minute within a credit limit |
| P-PROJ1 | Visual source model and project settings (EPIC 57) | ~18 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Channel identity and a saved project character reused by a new animated run |
| P-INT1 | Integrations v2 (EPIC 58) | ~16 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Add a second provider with an own key, make it default, generate on it |
| P-BILL-2 | Online payments (EPIC 59) | ~8 | planned | Buy credits online |
| P-LANG | Multi-language: Russian (EPIC 53) | tbd | planned (after P-BILL-2; order revised 2026-10-11) | Create a Russian run and render a video with Russian voice, captions and on-screen text |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Smoke tests not fully cleared: 4 entries** — P-UX4 (partial), P-PROJ1 (partial), P-INT1 (deferred, nothing reported yet) and the D113 cast follow-up (deferred), all → INT1-S5 in P-INT1. (P14b, P-UX3 and P-AN1 smoke passed on real runs; their unverified items are listed in DONE.md, not deferred. P-UX3: re-render a run with zooms to confirm D107.)
- **PROD is six sprints behind DEV.** PROD runs v0.24.0 (`edc92ba`); P12, P13, P13b, P14, P14b and P-UX3 (including migrations `0002_projects_shortlist.sql`, `0003_tenant_settings.sql` and `0004_tenant_defaults.sql`, and the new `SETTINGS_ENCRYPTION_KEY`) are on DEV only. Operator action: `/release`, with `/prod-check` first.
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

---

# Sprint P-AN1 — Animation mode (EPIC 55)

**Goal:** A run can be made entirely from generated images in one consistent style: the operator picks Animation, gives a master style, reviews a storyboard with a continuity bible, generates all images in one action, and renders a sub-minute video in 9:16 and in 16:9.
**Status:** complete 2026-10-11 (built in one pass, commit `5bfa361`; smoke fix `19f0c2f`). Smoke: one 9:16 and one 16:9 run on DEV, script to rendered video, the second on Nano Banana 2.1; one defect found and fixed. Cap stop, restart recovery and regenerate-after-edit were not exercised on DEV (see DONE.md).
**Points:** 26

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P-AN1-S1 | Run settings: visual mode and master style | 3 | done |
| P-AN1-S2 | Animation storyboard: the Visual Director prompt, structured | 8 | done |
| P-AN1-S3 | Image prompt assembled in code | 3 | done |
| P-AN1-S4 | Studio: scene cards and an editable continuity bible | 5 | done |
| P-AN1-S5 | Generate all images for a run | 5 | done |
| P-AN1-S6 | Nano Banana as the image model, and the sprint smoke test | 2 | done |

**Execution order:** S1 → S2 → S3 → S5 → S4 → S6. S3 and the S6 provider work do not depend on S2's code.

**Human touchpoint:** the operator makes one sub-minute run in 9:16 and one in 16:9, each from script to rendered video with generated images in the master style.

**Decisions:** D108. One worker per run on `claude-sonnet-5-5`, review pass skipped; kie.ai `nano-banana-2-1` at 1K while testing.

## Scope changes

- **Post-push fix `19f0c2f` (P-AN1-S5, S6):** a model saved for the other image provider is refused and ignored; the bulk job stops after three identical failures; `gpt-image-1` priced at its measured cost. Found in the smoke test.

---

# Sprint P-UX4 — Pipeline flow and polish (EPIC 56)

**Goal:** A run is created from a minimal modal and walked through all five steps with Next only; each step starts its own work.
**Status:** complete 2026-10-11 (built in one pass, commit `a7da166`). Smoke test deferred by the operator until after P-INT1 → cleared by INT1-S5.
**Points:** ~21

| ID | Title | Points | Status |
|----|-------|--------|--------|
| UX4-S1 | Shell polish: burger removed, select chevron padding, sidebar-panel icon, panel state kept, divider removed, storyboard at content width | 3 | done |
| UX4-S2 | New Run modal: Title, Language, Format, Style + master visual prompt sub-modal | 3 | done |
| UX4-S3 | Script step: Generate from idea first and collapsed, hidden in Paste, ends with Next | 3 | done |
| UX4-S4 | Voiceover step: pace and tone here, generate always allowed (replaces an upload), Regenerate + Next | 5 | done |
| UX4-S5 | Storyboard step: starts its own generation, Run Settings note, style lock warning, Merge at bottom right | 2 | done |
| UX4-S6 | Video step: captions on top, one source of truth with Run Settings, Next to Metadata | 3 | done |
| UX4-S7 | Library videos and voiceovers named after the run title | 2 | done |

**Execution order:** S1 → S2 → S3 → S4 → S5 → S6; S7 independent.
**Human touchpoint:** create a run from the new modal and walk the five steps using only Next, including switching Script mode after uploading a voiceover and generating a new voice over it.
**Decisions:** D109 (point 2).

---

# Sprint P-PROJ1 — Visual source model and project-level settings (EPIC 57)

**Goal:** A run's look and image source are separate, locked once a storyboard exists; a project holds a channel identity and saved characters/places that an animated run's storyboard reuses; the Realistic prompt v0.18 exists behind a setting.
**Status:** closed 2026-10-13 (built in one pass 2026-10-11; follow-ups D113 cast rule and script-view fixes; smoke partial → INT1-S5; v0.18 default not switched).
**Points:** ~18

| ID | Title | Points | Status |
|----|-------|--------|--------|
| PROJ1-S1 | Look and image source as two settings; lock after the storyboard with an explicit reset | 5 | done |
| PROJ1-S2 | Channel identity in Project settings, fed to metadata | 3 | done |
| PROJ1-S3 | Project assets: add, edit, remove, promote a run's bible entry | 4 | done |
| PROJ1-S4 | The animation worker reuses project assets | 3 | done |
| PROJ1-S5 | Realistic storyboard prompt v0.18 behind `STORYBOARD_STOCK_PROMPT_VERSION` | 3 | done (test and switch pending) |

**Execution order:** S1 → S2 → S3 → S4 → S5.
**Human touchpoint:** set a channel identity and save a character in Project settings; a new animated run's storyboard reuses that character and the metadata reads in the channel's voice.
**Decisions:** D111.

---

# Sprint P-INT1 — Integrations v2 (EPIC 58)

**Goal:** Integrations are grouped into five blocks; a block holds several providers, each with its own key, one default and a model; at least one text step really switches provider.
**Status:** closed 2026-10-13 (built in one pass 2026-10-11; smoke is INT1-S5, which the operator runs).
**Points:** ~16 (+ INT1-S5, 2)

| ID | Title | Points | Status |
|----|-------|--------|--------|
| INT1-S1 | Integrations regrouped into the five blocks | 2 | done |
| INT1-S2 | Provider registry and an LLM adapter (Anthropic, OpenAI); metadata on it | 5 | done |
| INT1-S3 | Several providers per block, a default and a model per provider | 5 | done |
| INT1-S4 | What a run was made with, and the defaults in force | 2 | done |
| INT1-S5 | DEV smoke sweep (P-UX4, P-PROJ1, P-INT1) | 2 | **operator** |

**Execution order:** S2 → S3 → S1 → S4; S5 last.
**Human touchpoint:** add OpenAI as a second Thinking-models provider with its own key, make it default, generate metadata on it.
**Decisions:** D112.
