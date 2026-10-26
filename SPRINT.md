> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> Roadmap as of the **2026-10-21 grooming** (review: `docs/PRODUCT_REVIEW_2026-10-21.md`): **P-BILL-1 close-out (beta opens) → P-PLAT → P-BILL-2 → P-SCALE1 → P-LANG → P17 + P-API → P-MOTION → P15 → P16.** Steps 5–7 are the operator's call; see the review, section 5.
> - Sprints P0–P10, P-UX1–P-UX4, P11 (S1), P12–P14b, P-AN1, P-PROJ1, P-INT1, P-HARD1, P-HARD2, P-LITE, P-AUTH, P-CORE and P-BILL-1 are closed. Story tables and Definitions of Done: **SPRINT_ARCHIVE.md**.
> - Studio features are Super screens of `/create` (D121). Telegram is dormant (D093). Sprints S14–S17 (video-UX polish) stay paused; the legacy pipeline UI is off unless `LEGACY_ROUTES_ENABLED` (D116).
> - **Current sprint:** P-PLAT (planned 2026-10-26; first the beta gate: SWEEP-1, AUDIT-2). Last review: 2026-10-26 (P-BILL-1).

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
| P-HARD1 | Audit and hardening: first `/audit`, loud voice failure, word-matching regression suite, bulk-job guard, cost-log backfill | ~11 | **done** 2026-10-13 | Read `docs/SECURITY.md`; a failed voice says so and offers Retry |
| P-HARD2 | Backups and restore drill, the audit's small fixes, deploy safety (EPIC 60) | ~8 | **done** 2026-10-14 (smoke cleared 2026-10-14 review) | Read the RUNBOOK backup section; `/legacy` gone; a failed migration shows in health |
| P-AUTH | Google sign-in, accounts, Basic / Super with View as Basic, per-user isolation, server-side gating (EPIC 59, D114, D118); `/audit` first | ~24 | **done 2026-10-14, smoke partial → AUTH-S10** (S0 is the operator's) | A friend signs in with Google and lands in their own, empty space; the owner flips View-as between tiers |
| P-LITE | The Creator flow for regular users (EPIC 59, D114, D117); S1..S5 built before P-AUTH, S6 gating moves to P-AUTH | ~16 | **done** 2026-10-14 (smoke passed) | A signed-in friend writes a bedtime story, picks a voice and characters, sees the cost, and gets an animated video |
| P-CORE | The full Studio in the new design, for Super (D118, D121) | ~28 | **done 2026-10-14, on DEV; smoke partial → P-CORE-S11** | Every Studio feature reachable in the new design; the old Studio pages retired |
| P-BILL-1 | Usage ledger, credits, charging, hard limits, owner top-up (EPIC 59, D114, D123) | ~13 + 9 close-out | **closed 2026-10-26**: BILL-S1..S5 built 2026-10-15 (PR #1 merged the same day), BILL-F1, BILL-F2, LEGAL-S1, BILL-F3 built 2026-10-22..26; smoke deferred to P-PLAT SWEEP-1 | **Friends beta opens** when SWEEP-1 passes and `BILLING_ENABLED=true` |
| P-PROJ1 | Visual source model and project settings (EPIC 57) | ~18 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Channel identity and a saved project character reused by a new animated run |
| P-INT1 | Integrations v2 (EPIC 58) | ~16 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Add a second provider with an own key, make it default, generate on it |
| P-PLAT | Beta gate (SWEEP-1, AUDIT-2, LEGAL-S1 human step), then image model + price that follows it (PLAT-S1), instant voice samples (PLAT-S2), scale measurement (SCALE-S1), real-motion model spike (MOTION-S1), face-reference model spike (REF-S1) (EPICS 61, 62, 64, 66) | ~19 | **current** (planned 2026-10-26) | A friend is charged and refused correctly on real credits; the owner picks the image model and every price follows; Listen on a voice plays at once |
| P-BILL-2 | Online payments, payment method, receipts, consumer terms, data export and account deletion, plus BILL-F4 (EPIC 59; was ~8, expanded 2026-10-21) | ~18 (~22 with subscription plans) | planned | Buy credits online, then export and delete your data |
| P-SCALE1 | Durable job queue and render workers (SCALE-S2, S3), AUTH-F1 (EPIC 62) | ~11 | planned; first part of the `SIGNUP_OPEN` gate |
| P-SCALE2 | Web tier and data path, provider backpressure, chunked voiceover, token-accurate settling, security leftovers (SCALE-S4, S5, E54-S1, BILL-F3, SEC-S1) | ~17 | planned; the load test here closes the `SIGNUP_OPEN` gate, after a fresh `/audit` | The load test passes at the agreed number of users |
| P-LANG | Multi-language: Russian (EPIC 53) | tbd | planned (after P-SCALE1; order revised 2026-10-11 and 2026-10-21) | Create a Russian run and render a video with Russian voice, captions and on-screen text |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |
| P-API | Platform API for automation: keys, create, status, download, webhooks, n8n example (EPIC 63) | ~16 (~13 without webhooks) | planned (after P17 and SCALE-S2) | n8n makes a finished video and downloads it |
| P-MOTION | Real-motion animation: image-to-video clips per scene (EPIC 64) | ~21 + spike | planned (spike in P-PLAT) | A run with the Motion toggle on renders clips instead of camera moves on stills |
| P-REF | Character reference photos: upload and consent, portrait in the master style, reference-aware images, interface (EPIC 66) | ~12 | planned (after P-BILL-2; behind `CHARACTER_PHOTOS_ENABLED`) | A user attaches their photo to a character and every image keeps their features in the video's style |
| EPIC 65 | Style paths: evaluation harness, style packs, Documentary / Movie / Manga | tbd | unplaced (analysis only) | — |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Smoke tests not fully cleared: 3 DONE.md entries, one sweep — P-BILL-1 and its close-out (DEFERRED) and BETA-0 (PARTIAL); all in SWEEP-1, Sprint P-PLAT.** AUTH-S10 and P-CORE-S11 were marked done by the operator at the 2026-10-26 review. Earlier: INT1-S5 (the P-UX4 / P-PROJ1 / P-INT1 sweep) was run on DEV 2026-10-13; INT2-S1 (Integrations rework) stays a candidate. P14b, P-UX3 and P-AN1 smoke passed on real runs; their unverified items are in DONE.md. P-UX3: re-render a run with zooms to confirm D107.
- **PROD is not where the records said (prod check 2026-10-26).** v0.25.0 was released 2026-10-13 and PROD has built `main` from GitHub since 2026-10-17 (latest `987e697`, 2026-10-22), so it runs the billing and beta code, with `BILLING_ENABLED=true`, but not the close-out fixes of 2026-10-26. The earlier line, "PROD stays on v0.24.0 on purpose", no longer holds. Operator decision: PROD-ALIGN (proposed, BACKLOG_ACTIVE.md). PROD start-up logs `migrations: ok`; which of 0005–0007 are applied there was not checked.
- **Security audits: 2026-10-13 (23 findings) and 2026-10-22 (money paths; 2 HIGH fixed 2026-10-23).** Open: F1 until a restore drill is recorded in `docs/RUNBOOK.md`; F6 (`ACCEPT_LEGACY_COOKIE=false` still to set on DEV); the expired accepted risks listed in `docs/SECURITY.md`. A re-check (AUDIT-2) is due before `BILLING_ENABLED`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **API keys in DEV logs (found 2026-10-05, P14 smoke) — code fixed in P14b-S5 (2026-10-07), operator actions open:** (1) rotate the Pixabay key on DEV and revoke the old one — the key is still in Railway's DEV log history; do the same on PROD at release; (2) check the DEV log for `key=` (should now read `key=REDACTED`) and re-check PROD at the next `/prod-check`, before `/release`. Fold into `/audit` if that is run first.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

---

# Current sprint

## Sprint P-PLAT — platform settings, measurement, and the beta gate (EPICS 59, 61, 62, 64, 66)

**Goal:** open the friends beta (credits on, real friends charged and refused correctly), and give the owner one place to choose the image model so every price follows it; measure the platform before scaling it.
**Status:** planned 2026-10-26 at the P-BILL-1 review. Open smokes entering the sprint: 3 DONE.md entries (P-BILL-1 and its close-out DEFERRED, BETA-0 PARTIAL), all covered by SWEEP-1; AUTH-S10 and P-CORE-S11 were marked done by the operator on 2026-10-26. Count 3, so the sweep is mandatory and first (it is also the beta gate); below 5, so feature stories are allowed.
**Points:** ~19

| ID | Title | Points | Status |
|----|-------|--------|--------|
| SWEEP-1 | DEV smoke of P-BILL-1 and its close-out (the seven steps in DONE.md plus refund and day-cap recovery, privacy / terms re-accept, erase dry-run); read the DEV log for `billing: could not settle|refund` and `key=`; BILL-F3 operator inputs (`cost_report.py` with invoices, `EST_*`, `IMAGE_RESOLUTION=2K`, `nano-banana-2-1` 0.03, `ACCEPT_LEGACY_COOKIE=false`); billing is already on (see the PROD note under Open items) | 2 | backlog (operator + Claude) |
| LEGAL-S1 (human step) | Owner decides minimum age and seller / controller, has the privacy notice and terms reviewed | 1 | backlog (operator) |
| AUDIT-2 | `/audit` re-check of the 2026-10-23 and 2026-10-26 fixes before `BILLING_ENABLED` (SECURITY.md: "before `BILLING_ENABLED` is set") | 1 | backlog |
| PLAT-S1 | Image model as a platform setting; one price that follows it; regression tests for the three image fixes of BETA-0 (platform key fallback, default model, final job status before claim release) | 5 | backlog |
| PLAT-S2 | Voice samples that play at once | 3 | backlog |
| SCALE-S1 | Measure: step timings, provider limits, a load model | 3 | backlog |
| MOTION-S1 | Spike: choose the image-to-video model(s) | 2 | backlog |
| REF-S1 | Spike: which models keep a likeness in a style | 2 | backlog |

**Execution order:** SWEEP-1 and AUDIT-2 first (the beta gate); LEGAL-S1's human step in parallel (the owner's); PLAT-S1 and PLAT-S2 next; the measurement and the two spikes last.
**Human touchpoint:** a friend, with credits on, makes a video, is charged and is refused with a clear message at zero; the owner picks the image model in Settings and every price follows; Listen on a voice plays at once.
**Not in this sprint:** online payments, data export and account deletion (P-BILL-2); the durable queue and render workers (P-SCALE1); settling LLM calls at real token counts (candidate).
**Carried watch items:** word-matching and scene-cut timing (three fixes in BETA-0): add golden cases to the HARD1-S3 suite when the next one appears.

---

## Scope changes

_None yet._
