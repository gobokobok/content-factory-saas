> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> Roadmap as of the **2026-10-21 grooming** (review: `docs/PRODUCT_REVIEW_2026-10-21.md`): **P-BILL-1 close-out (beta opens) → P-PLAT → P-BILL-2 → P-SCALE1 → P-LANG → P17 + P-API → P-MOTION → P15 → P16.** Steps 5–7 are the operator's call; see the review, section 5.
> - Sprints P0–P10, P-UX1–P-UX4, P11 (S1), P12–P14b, P-AN1, P-PROJ1, P-INT1, P-HARD1, P-HARD2, P-LITE, P-AUTH and P-CORE are closed. Story tables and Definitions of Done: **SPRINT_ARCHIVE.md**.
> - Studio features are Super screens of `/create` (D121). Telegram is dormant (D093). Sprints S14–S17 (video-UX polish) stay paused; the legacy pipeline UI is off unless `LEGACY_ROUTES_ENABLED` (D116).
> - **Current sprint:** P-BILL-1 (planned 2026-10-15, built, not merged).

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
| P-BILL-1 | Usage ledger, credits, charging, hard limits, owner top-up (EPIC 59, D114, D123) | ~13 | **BILL-S1..S5 built 2026-10-15 on branch `claude/p-bill-1` (PR open, not merged; smoke pending, after AUTH-S10 and P-CORE-S11); close-out adds BILL-F1, BILL-F2, LEGAL-S1 (2026-10-21)** | **Friends beta opens:** a friend is charged credits for their video and cannot overspend |
| P-PROJ1 | Visual source model and project settings (EPIC 57) | ~18 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Channel identity and a saved project character reused by a new animated run |
| P-INT1 | Integrations v2 (EPIC 58) | ~16 | **done** 2026-10-11 (smoke deferred to INT1-S5) | Add a second provider with an own key, make it default, generate on it |
| P-PLAT | Platform settings and measurement: image model + price that follows it (PLAT-S1), instant voice samples (PLAT-S2), scale measurement (SCALE-S1), real-motion model spike (MOTION-S1) (EPICS 61, 62, 64) | ~13 | planned (after P-BILL-1; groomed 2026-10-21) | The owner picks the image model and every price follows; Listen on a voice plays at once |
| P-BILL-2 | Online payments, payment method, receipts, consumer terms, data export and account deletion (EPIC 59; was ~8, expanded 2026-10-21) | ~16 (~20 with subscription plans) | planned | Buy credits online, then export and delete your data |
| P-SCALE1 | Durable job queue, render workers, web tier, provider backpressure (EPIC 62) | ~16 | planned; gate for `SIGNUP_OPEN` | The load test passes at the agreed number of users |
| P-LANG | Multi-language: Russian (EPIC 53) | tbd | planned (after P-SCALE1; order revised 2026-10-11 and 2026-10-21) | Create a Russian run and render a video with Russian voice, captions and on-screen text |
| P15 | Research | ~18 | planned | Run trend + competitor research in a project, tick results into the shortlist |
| P16 | Publishing via n8n | ~10 | planned | Set a channel and time on a run; it appears on YouTube with status shown in Studio |
| P17 | Server-side Auto Advance | ~10 | planned | Pick a shortlist idea, close the tab, come back to a scheduled video |
| P-API | Platform API for automation: keys, create, status, download, webhooks, n8n example (EPIC 63) | ~16 (~13 without webhooks) | planned (after P17 and SCALE-S2) | n8n makes a finished video and downloads it |
| P-MOTION | Real-motion animation: image-to-video clips per scene (EPIC 64) | ~21 + spike | planned (spike in P-PLAT) | A run with the Motion toggle on renders clips instead of camera moves on stills |
| EPIC 65 | Style paths: evaluation harness, style packs, Documentary / Movie / Manga | tbd | unplaced (analysis only) | — |

**Parked (D099):** P11-S2 motion presets · P11-S3 sub-scene asset timeline · Format tracks (old P12) · Analytics & attribution (old P13).

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Open items carried from closed sprints

- **Smoke tests not fully cleared: 3 — 1 DEFERRED (P-BILL-1) and 2 PARTIAL (AUTH-S10 for P-AUTH, P-CORE-S11 for P-CORE); all three are stories of the current sprint.** (Corrected 2026-10-21; this line said 0 while the two PARTIALs were open.) Earlier: INT1-S5 (the P-UX4 / P-PROJ1 / P-INT1 sweep) was run by the operator on DEV 2026-10-13, and P-INT1's OpenAI default / metadata path was marked done by the operator at the 2026-10-13 review; INT2-S1 (Integrations rework) stays a candidate. P14b, P-UX3 and P-AN1 smoke passed on real runs; their unverified items are in DONE.md. P-UX3: re-render a run with zooms to confirm D107.
- **PROD is many sprints behind DEV (on purpose, operator).** PROD runs v0.24.0 (`edc92ba`); P12 … P-LITE, migrations `0002`–`0004`, `SETTINGS_ENCRYPTION_KEY` and the P-HARD1/P-HARD2 start-up validators (`OPERATOR_PASSWORD` ≥ 12 characters) are on DEV only. Operator action at release: `/prod-check`, then `/release`, setting a new `SETTINGS_ENCRYPTION_KEY` and a 12+ character `OPERATOR_PASSWORD` first.
- **Security audit run 2026-10-13** — `docs/SECURITY.md`, 23 findings. Open at P-AUTH: F2, F5, F6, F8, F13 (D115); F1 stays open until a restore drill is recorded in `docs/RUNBOOK.md`.
- **PROD sleeps when idle** (Railway app sleeping, 6–10 minutes without requests). Harmless while the browser polls; it will stop a server-side Auto Advance run with the tab closed. To be settled in P17.
- **API keys in DEV logs (found 2026-10-05, P14 smoke) — code fixed in P14b-S5 (2026-10-07), operator actions open:** (1) rotate the Pixabay key on DEV and revoke the old one — the key is still in Railway's DEV log history; do the same on PROD at release; (2) check the DEV log for `key=` (should now read `key=REDACTED`) and re-check PROD at the next `/prod-check`, before `/release`. Fold into `/audit` if that is run first.
- **Google API audit application** (P12 lead-time task) — in progress; operator will submit. Needed for P16.
- **Candidate, not a story yet:** captions take their words from the Deepgram transcript, so a misheard word ("pedals are wheel" for "pedals or wheel", PROD 2026-10-02) can reach the video. See docs/RUNBOOK.md.

---

---

# Current sprint

## Sprint P-BILL-1 — usage ledger, credits, charging, hard limits, owner top-up (EPIC 59, D114, D123)

**Goal:** a friend is charged credits for their video and cannot overspend; the owner tops accounts up and sees usage. **The friends beta opens when this sprint is smoked.**
**Status:** **BUILT 2026-10-15 on branch `claude/p-bill-1`** (commit `eaafe87`, 3393 tests passing in the cloud sandbox, after the PR #1 review fixes; PR open, not merged; handover in DONE.md). Planned 2026-10-15 at the review of P-AUTH and P-CORE; design defaults are D123. `BILLING_ENABLED` is off by default, so merging changes nothing on DEV until the operator turns it on. **Open before the beta opens:** AUTH-S10 and P-CORE-S11 (live smokes), the scoped `/audit`, then the P-BILL-1 smoke in DONE.md.
**Points:** ~13 (+2 for the two carried smokes, +9 for the 2026-10-21 close-out stories BILL-F1, BILL-F2, LEGAL-S1)

| ID | Title | Points | Status |
|----|-------|--------|--------|
| AUTH-S10 | Finish the P-AUTH smoke as a second Google account (operator, needs live Google) | 1 | operator action — open |
| P-CORE-S11 | DEV smoke of P-CORE (operator, needs live providers) | 1 | operator action — open |
| BILL-S1 | Usage ledger: every paid action is a priced entry with its raw cost | 3 | built 2026-10-15 (smoke pending) |
| BILL-S2 | Credits: unit and markup, per-user balance, estimate before confirm, hold → settle, refund on failure | 4 | built 2026-10-15 (smoke pending) |
| BILL-S3 | Hard limits: an action over the balance is refused with its cost and what is left | 2 | built 2026-10-15 (smoke pending) |
| BILL-S4 | Owner top-up and an admin view of users, balances and usage | 2 | built 2026-10-15 (smoke pending) |
| BILL-S5 | The Creator sees balance, price and history | 2 | built 2026-10-15 (smoke pending) |
| BILL-F1 | Release the daily USD reservation when a hold is refunded or settled down (raised to high 2026-10-21) | 2 | backlog — gate for `BILLING_ENABLED` |
| BILL-F2 | Refund when the provider call succeeded but its result was lost (raised to high 2026-10-21) | 3 | backlog — gate for `BILLING_ENABLED` |
| LEGAL-S1 | Legal minimum before the beta: privacy notice, terms rewrite, sub-processors, erasure procedure (added 2026-10-21) | 4 | backlog — gate for `BILLING_ENABLED` |

**Execution order:** S1 → S2 → S3 → S4 → S5 (S3 is the refusal path of S2's hold; kept separate for its tests). AUTH-S10 and P-CORE-S11 are the operator's, on DEV, before `BILLING_ENABLED` is turned on.
**Human touchpoint:** the owner tops up a friend's account; the friend sees the balance and the price of a video before making it, is charged for it, and is refused with a clear message when the balance is too low.
**Not in this sprint:** online payments and legal pages (P-BILL-2); settling LLM calls to actual token counts (candidate — today an LLM call is priced at `EST_LLM_CALL_USD`, D123); per-tenant key billing (user's own keys are never charged).

---

## Scope changes

- 2026-10-21 (grooming, operator request to review the product): BILL-F1 and BILL-F2 raised from follow-ups to gates for `BILLING_ENABLED` (a friend charged for a failed video, or locked out of a daily cap at zero spend, does not come back); LEGAL-S1 added as the pre-beta legal minimum (personal data is already held with no privacy notice or deletion path). Closed sprint sections P-AUTH and P-CORE moved to SPRINT_ARCHIVE.md (a review covers them: e9d6772, 2026-10-15).
