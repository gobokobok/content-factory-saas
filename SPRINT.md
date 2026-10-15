> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-10-03 the roadmap is **replaced by the Pipeline & Platform Update spec** (D092–D099): **P12 Projects & shortlist → P13 Storyboard control → P13b CapCut export (D100) → P14 AI images per scene → P14b Uploaded voiceover → P-UX3 UI/UX redesign → UI build → Multi-language: Russian → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance.**
> - **Sprints P0–P10, P-UX1, P-UX2 complete.** P11 closed with S1 done; P11-S2 and P11-S3 are parked (D099).
> - Studio is the only operator interface; Telegram is dormant (D093).
> - Sprints **S14–S17** (video-UX polish) remain paused. The legacy Script→Video pipeline stays operable at `/legacy` (D047, D066).
> - Full history — every closed sprint's story table and Definition of Done: **SPRINT_ARCHIVE.md**.
> - **Sprints P12 and P13 complete** (2026-10-03). **Sprint P-UX3 complete** (2026-10-11). **Sprint P13b complete** (2026-10-04). **Sprint P14 complete** (2026-10-05). **Sprint P14b complete** (2026-10-07). **Roadmap change 2026-10-05 (operator, at the P14 review):** two sprints go ahead of P15 — **P14b Uploaded voiceover**, then **P-UX3 UI/UX redesign (discovery and design)**, then the build sprint(s) for the new UI, then **Multi-language: Russian** (EPIC 53), then P15 Research. **Current sprint:** P-BILL-1 (planned 2026-10-15). P-UX3, P-AN1, P-UX4, P-PROJ1, P-INT1, P-HARD1, P-HARD2 and P-LITE are closed.

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
| P-CORE | The full Studio in the new design, for Super (D118) | ~28 | **built 2026-10-14 (branch `sprint/p-core`, not merged; DEV smoke pending)** — was: planned (after P-AUTH; order against P-BILL-1 set at the P-AUTH close) | Every Studio feature reachable in the new design; the old Studio pages retire |
| P-BILL-1 | Usage ledger, credits, charging, hard limits, owner top-up (EPIC 59, D114, D123) | ~13 | **BILL-S1..S5 built 2026-10-15 on branch `claude/p-bill-1` (PR open, not merged; smoke pending, after AUTH-S10 and P-CORE-S11)** | **Friends beta opens:** a friend is charged credits for their video and cannot overspend |
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
**Points:** ~13 (+2 for the two carried smokes)

| ID | Title | Points | Status |
|----|-------|--------|--------|
| AUTH-S10 | Finish the P-AUTH smoke as a second Google account (operator, needs live Google) | 1 | operator action — open |
| P-CORE-S11 | DEV smoke of P-CORE (operator, needs live providers) | 1 | operator action — open |
| BILL-S1 | Usage ledger: every paid action is a priced entry with its raw cost | 3 | built 2026-10-15 (smoke pending) |
| BILL-S2 | Credits: unit and markup, per-user balance, estimate before confirm, hold → settle, refund on failure | 4 | built 2026-10-15 (smoke pending) |
| BILL-S3 | Hard limits: an action over the balance is refused with its cost and what is left | 2 | built 2026-10-15 (smoke pending) |
| BILL-S4 | Owner top-up and an admin view of users, balances and usage | 2 | built 2026-10-15 (smoke pending) |
| BILL-S5 | The Creator sees balance, price and history | 2 | built 2026-10-15 (smoke pending) |

**Execution order:** S1 → S2 → S3 → S4 → S5 (S3 is the refusal path of S2's hold; kept separate for its tests). AUTH-S10 and P-CORE-S11 are the operator's, on DEV, before `BILLING_ENABLED` is turned on.
**Human touchpoint:** the owner tops up a friend's account; the friend sees the balance and the price of a video before making it, is charged for it, and is refused with a clear message when the balance is too low.
**Not in this sprint:** online payments and legal pages (P-BILL-2); settling LLM calls to actual token counts (candidate — today an LLM call is priced at `EST_LLM_CALL_USD`, D123); per-tenant key billing (user's own keys are never charged).

---

## Sprint P-CORE — the full Studio in the new design, for Super (D118, D121)

**Goal:** the owner makes a whole realistic video — from an idea in a project to a rendered file and metadata — without leaving `/create`, and the old Studio can retire.
**Status:** **DONE 2026-10-14 — on DEV; smoke PARTIAL → P-CORE-S11 (Sprint P-BILL-1).** Closed together with the UX pass after the operator's first DEV use (mobile panels, AI assets and Images libraries, named voices, script lock, reordered settings).

| ID | Title | Points | Status |
|----|-------|--------|--------|
| CORE-S1 | Super shell: hash routes, left menu, Projects list, New project | 2 | done |
| CORE-S2 | Project page: overview, ideas, videos, settings, project assets | 4 | done |
| CORE-S3 | Libraries: videos, audio, footage, AI generations, music | 2 | done |
| CORE-S4 | Integrations and Defaults | 3 | done |
| CORE-S5 | New video for Super (project, realistic / animated); Script step sources: paste, generate, from a voiceover | 3 | done |
| CORE-S6 | Voice: pace and style, upload, transcript editing, language check | 3 | done |
| CORE-S7 | Realistic look: stock acquisition, asset type, search words, re-acquire, script view, SFX | 4 | done |
| CORE-S8 | Cast, run language, look change, save to project assets | 2 | done |
| CORE-S9 | Metadata step, CapCut export and upload, Auto-advance | 3 | done |
| CORE-S10 | Retire the old pages: redirects, deleted files, tests, docs | 2 | done |

**Human touchpoint:** as the owner on DEV, open `/create`, start a video in a project from an idea, make it realistic, and take it to metadata.

## Sprint P-AUTH — Google sign-in, accounts, Basic / Super, isolation (EPIC 59, D114, D118)

**Goal:** a stranger can sign in with Google and use only their own space; the owner can see the product as a Basic user.
**Status:** **DONE 2026-10-14 — merged to `main`, deployed to DEV (`c5a7dbe`); owner sign-in verified, friend-account smoke → AUTH-S10.** Planned 2026-10-14 (review of P-HARD1 .. P-LITE). **Audit run 2026-10-14** (`docs/SECURITY.md`: 3 critical, 5 high); its build constraints are folded into S1, S3, S6, S8 and S9. **Rule:** Google sign-in stays allow-listed until S3 and S6 are merged — until then a second account is a full operator.
**Points:** ~24 (estimates are the review's and the audit's; refine at `/start-story`)

| ID | Title | Points | Status |
|----|-------|--------|--------|
| AUTH-S0 | Set `PROD_URL`; see the post-deploy check pass on PROD (operator action, F11) | 1 | operator action — open (needs the `PROD_URL` variable) |
| AUTH-S1 | Google OAuth sign-in and account creation; signed sessions in a table (7–30 days, revoked on logout, rotated at login); server-side `state` + PKCE, fixed `redirect_uri` from config, `next` allow-list, users keyed by `sub`, Origin check on mutating routes; legacy login kept for the owner (F6) | 4 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S2 | User ↔ tenant model: one personal tenant and one hidden default project per user | 2 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S3 | Thread the user through repositories and routes (replace `PLATFORM_USER_ID`, 87 uses): `tenant_id` on every repo method, `require_run` / `require_project` on every run-scoped route, library and `/platform/runs` filtered by tenant, legacy `DELETE /runs/{id}` and settings moved behind `require_run`, `run_id` path pattern, F5 fallback fix (F2, F5) | 6 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S4 | Account type Basic / Super (D118) as a field and a server-side check; View-as-Basic toggle | 2 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S5 | Isolation tests: user A cannot read or write user B's run, project, artifact, library | 2 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S6 | Server-side gating of everything Basic does not have (was LITE-S6): `require_super` on every non-Creator route; `/platform/version`, `echo`, `produce` Super-only; Telegram unmounted; in-memory repo fallback fails closed outside local | 2 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S7 | Super's left menu in the new design, linking to the old pages until P-CORE | 1 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S8 | Server caps and cost bounds: script words, prompt / style / character lengths, runs per day, per-tenant daily spend row checked before every paid call (LLM, TTS, image, `write-prompt`, render), per-user render concurrency, per-tenant storage quota (F8, F4) | 3 | done 2026-10-14 (smoke partial → AUTH-S10) |
| AUTH-S9 | Moderation gate (D115) in front of storyboard, voice, `write-prompt` and image generate, plus a terms-acceptance row at first sign-in; prompt log per tenant (F13) | 3 | done 2026-10-14 (smoke partial → AUTH-S10) |

**Execution order:** S0 → S1 → S2 → S3 → S4 → S6 → S5 → S8 → S9 → S7. S8 and S9 are required before sign-in is opened beyond the allow-list. Check the DEV Railway variables each story touches before coding (`/start-story` v0.8 step 6.5).
**Human touchpoint:** a friend signs in with Google and lands in their own, empty space; the owner flips View-as between Basic and Super.
**Not in this sprint:** P-CORE, P-BILL-1 (charging; the credit ledger replaces S8's interim daily spend row), INT2-S1, the restore drill (F1), F16 key rotation, F19 `ffprobe`, a CSP header (candidate).

## Scope changes

_None._
