> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI images per scene → P14b Uploaded voiceover → P-UX3 UI/UX redesign → UI build → Multi-language: Russian → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprints P12 and P13 complete** (2026-10-03). **Sprint P-UX3 complete** (2026-10-11). **Sprint P13b complete** (2026-10-04). **Sprint P14 complete** (2026-10-05). **Sprint P14b complete** (2026-10-07). **Roadmap change 2026-10-05 (operator, at the P14 review):** two sprints go ahead of P15 — **P14b Uploaded voiceover**, then **P-UX3 UI/UX redesign (discovery and design)**, then the build sprint(s) for the new UI, then **Multi-language: Russian** (EPIC 53), then P15 Research. **Current sprint:** P-HARD1 (planned 2026-10-13). P-UX3, P-AN1, P-UX4, P-PROJ1 and P-INT1 are closed.

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
| P-HARD1 | Audit and hardening: first `/audit`, loud voice failure, word-matching regression suite, bulk-job guard, cost-log backfill | ~11 | **planned** (review 2026-10-13) | Read `docs/SECURITY.md`; a failed voice says so and offers Retry |
| P-AUTH | Google sign-in, accounts, tiers with View-as, per-user isolation (EPIC 59, D114); `/audit` first | ~16 | planned | A friend signs in with Google and lands in their own, empty space; the owner flips View-as between tiers |
| P-LITE | The Creator flow for regular users (EPIC 59, D114) | ~16 | planned | A signed-in friend writes a bedtime story, picks a voice and characters, sees the cost, and gets an animated video |
| P-BILL-1 | Usage ledger, credits, charging, hard limits, owner top-up (EPIC 59, D114) | ~13 | planned | **Friends beta opens:** a friend is charged credits for their video and cannot overspend |
| P-PROJ1 | Visual source model and project settings (EPIC 57) | ~18 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Channel identity and a saved project character reused by a new animated run |
| P-INT1 | Integrations v2 (EPIC 58) | ~16 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Add a second provider with an own key, make it default, generate on it |
| P-BILL-2 | Online payments and legal pages (EPIC 59) | ~8 | planned | Buy credits online |
| P-LANG | Multi-language: Russian (EPIC 53) | tbd | planned (after P-BILL-2; order revised 2026-10-11) | Create a Russian run and render a video with Russian voice, captions and on-screen text |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Smoke tests not fully cleared: 0** — P-INT1's OpenAI default / metadata path was marked done by the operator at the 2026-10-13 review; INT2-S1 (Integrations rework) is not in P-HARD1 (dropped by the operator 2026-10-13) and stays a candidate. INT1-S5 (the P-UX4 / P-PROJ1 / P-INT1 sweep) was run by the operator on DEV 2026-10-13. (P14b, P-UX3 and P-AN1 smoke passed on real runs; their unverified items are listed in DONE.md, not deferred. P-UX3: re-render a run with zooms to confirm D107.)
- **PROD is six sprints behind DEV.** PROD runs v0.24.0 (`edc92ba`); P12, P13, P13b, P14, P14b and P-UX3 (including migrations `0002_projects_shortlist.sql`, `0003_tenant_settings.sql` and `0004_tenant_defaults.sql`, and the new `SETTINGS_ENCRYPTION_KEY`) are on DEV only. Operator action: `/release`, with `/prod-check` first.
- **Security audit never run** — there is no `docs/SECURITY.md`. P12 added the tenant / project model and 2026-07-26 changed login handling. Operator action: `/audit`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **API keys in DEV logs (found 2026-10-05, P14 smoke) — code fixed in P14b-S5 (2026-10-07), operator actions open:** (1) rotate the Pixabay key on DEV and revoke the old one — the key is still in Railway's DEV log history; do the same on PROD at release; (2) check the DEV log for `key=` (should now read `key=REDACTED`) and re-check PROD at the next `/prod-check`, before `/release`. Fold into `/audit` if that is run first.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

---

# Sprint P-HARD1 — Audit and hardening (before P-AUTH)

**Goal:** Close the rework the 2026-10-13 review found (a silent voice failure on PROD, word matching fixed three times on data nobody saw, cost blind for two sprints) and run the first security audit before accounts exist.
**Status:** built 2026-10-13 in one pass on branch `sprint/p-hard1` (not pushed — a DEV → PROD copy was running in another session). Tests 3000 passing. Smoke test pending the merge and DEV deploy.
**Points:** ~11

| ID | Title | Points | Status |
|----|-------|--------|--------|
| HARD1-S1 | `/audit` — first `docs/SECURITY.md` (tenant keys, `SETTINGS_ENCRYPTION_KEY`, log redaction, upload paths, the open moderation stance for strangers' text) | 3 | done (branch) |
| HARD1-S2 | Voice: a failed TTS call fails the job loudly with Retry, never "complete" with no audio (PROD 2026-10-10, run `6fe35dab`) | 2 | done (branch) |
| HARD1-S3 | Word-matching regression suite from real DEV pastes — transcript editor and script view (numbers, currency, percent, years said as two pairs) | 3 | done (branch) |
| HARD1-S4 | Guard split / merge while a bulk image job runs (carried from P-AN1) | 2 | done (branch) |
| HARD1-S5 | Cost log: write range entries for sprint-at-a-time builds; backfill P-UX4, P-PROJ1, P-INT1 from commit times | 1 | done (branch) |

**Execution order:** S1 first (findings may reshape S2–S4); S2, S3, S4 independent; S5 last.
**Human touchpoint:** the operator reads `docs/SECURITY.md`, regenerates a voice with the TTS provider failing (it says so and offers Retry), and pastes a script with spelled-out numbers into the script view.
**Not in this sprint:** INT2-S1 (Integrations rework; dropped 2026-10-13, remains a candidate), P-AUTH, P-LITE, P-BILL-1 follow per D114. v0.17 vs v0.18 storyboard prompt side-by-side is the operator's call and is not scheduled. PROD release stays the operator's call (not a blocker).

## Scope changes

_None._
