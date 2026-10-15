# Backlog — Active Stories

_Contains the sprint outlines for P-HARD1 → P-AUTH … P17 and open unassigned stories. Closed sprints (P-UX3, P-AN1 and older) are in BACKLOG.md; recent handovers are in DONE.md._
_Updated at each sprint boundary: move the completed sprint's block to BACKLOG.md._

---

## Platform Update outlines — Sprints P-UX3–P17

Detailed at each sprint boundary. Spec section numbers refer to the Pipeline & Platform Update specification (2026-10-03).

**EPIC 44 — Storyboard control (P13)** — done 2026-10-03: stories and handovers moved to BACKLOG.md. Open for P13b: whether split / merge and asset strategy need anything extra in the CapCut timeline file (new scene fields: `asset_strategy`; manifest: `asset_slot`, status `awaiting_upload`).

**EPIC 49 — CapCut export (P13b, D100)** — done 2026-10-04: stories P13b-S1..S4 in the EPIC 49 section below.

**EPIC 45 — AI images per scene (P14, D096, D104) — DONE 2026-10-05, stories P14-S1..S4 (handover in DONE.md); re-scoped at `/start-story` 2026-10-04.** Manual per-scene generation from the storyboard edit-image dialog (prompt field + Generate); no style generates images automatically. `ImageProvider` interface with kie.ai (default) and OpenAI clients, selected by tenant settings. Provider, model and API key live at tenant level (`tenant_settings`, migration 0003, Fernet-encrypted with `SETTINGS_ENCRYPTION_KEY`; Railway keys are the fallback) and are edited at `/settings`. Optional project-level `ai_image_style` prepended to every prompt. Per-run spend cap (`IMAGE_RUN_SPEND_CAP_USD`, default 2.00) with a cost readout. Files that mattered: `cf_platform/interfaces/routes/studio_ai.py`, `cf_platform/core/{image_provider,tenant_settings,secret_box,ai_images}.py`, `src/models.py` (strategy vocabulary), `cf_platform/workers/{acquisition_worker,timeline,storyboard_edit}.py` (operator-supplied scenes), `src/static/studio-v2.html` (pencil modal, `acquirePlan`), `ENV.md`. Not built (candidate follow-up): a "Suggest prompt" button that asks the Visual Director / Claude for a scene prompt, and the provider side-by-side test (skipped by the operator).

**EPIC 51 — Uploaded voiceover (P14b)** — done 2026-10-07: stories moved to BACKLOG.md. **EPIC 52 — UI/UX redesign (P-UX3)** — done 2026-10-11 (the build was folded in): stories below.

**EPIC 55 — Animation mode (Sprint P-AN1, new 2026-10-11, immediately after P-UX3 closes, ahead of EPIC 53)** — AI-image videos from a Visual Director storyboard with a master style and a continuity bible; stories P-AN1-S1..S6 in the EPIC 55 section below.

**EPIC 56 — Pipeline flow and polish (Sprint P-UX4, DONE 2026-10-11, commit `a7da166`, handover in DONE.md; smoke deferred to INT1-S5; new 2026-10-11, from the UI/UX review `docs/UX_REVIEW_2026-10-11.md` C1–C22, C28, C29, C33, C34).** Minimal New Run modal (title, language, format, style Realistic/Animated, "Add master visual prompt" sub-modal, one note "change later in Run Settings"); each step starts its own work and ends with **Next**; Script step reordered (Generate from idea first, collapsible, hidden in Paste); Voiceover step owns pace/tone and can always generate (an uploaded voiceover is a replaceable asset, not a run type that blocks generation, amends D106); Storyboard step note, lock warning and card layout; Video step captions with one source of truth shared with Run Settings; library files named after the run; shell polish (burger, chevron padding, sidebar icon, persistent sidebar state, no divider, storyboard width). Stories UX4-S1..S7, ~21 pts; detail at the sprint boundary. Plan: `docs/UX_REVIEW_2026-10-11_PLAN.md`.

**EPIC 57 — Visual source model and project-level settings (Sprint P-PROJ1, DONE 2026-10-11, handover in DONE.md; v0.18 default switch pending its side-by-side test; smoke deferred to INT1-S5).** Split `visual_mode` into look (realistic / animated) and image source (stock / AI-generated), both locked once a storyboard exists (explicit "reset storyboard" to unlock); Channel identity in Project Settings feeding metadata generation; Project assets (recurring characters/places saved at project level, reused by the storyboard worker). Plus the Realistic storyboard prompt v0.18 (Visual Director method on the stock contract, Sonnet 5.5, side-by-side test before switching; C35). Review items C18, C19, C23, C24, C35. Stories PROJ1-S1..S5, ~18–21 pts. Amends D108.

**EPIC 58 — Integrations v2 (Sprint P-INT1, DONE 2026-10-11, handover in DONE.md; D112).** Integrations grouped into blocks (Thinking models, Audio models, Image generation, Stock acquisition, Destination); a provider interface per block; several providers per block, each with its own key and model, one default. Project keys are the default and usage is charged to the user's balance; a user's own key becomes their default automatically, with a checkbox to keep the project default. Review items C25–C27. ~13–16 pts. See D109. **INT1-S5 — DEV smoke sweep (DONE 2026-10-13 by the operator, except step 12: OpenAI as default and metadata on it, left open until the rework below; was: smoke for P-UX4, closes the deferral, 2 pts, added at the P-UX4 close, operator decision 2026-10-11).** **INT2-S1 (candidate, operator 2026-10-13) — rework the Integrations page and approach:** the five-block page and the default/model-per-provider model were judged to need a rethink; running on the platform's models is fine for now. Bring the P-AUTH design (user keys vs platform keys, D109 point 5) into it before rebuilding, and clear the open OpenAI smoke item there. Run the P-UX4 smoke list on DEV, after P-INT1 is built: create a run from the minimal modal (Animated + master prompt) and walk five steps with Next only; upload a voiceover, switch Script to Generate, generate a voice over it (confirm prompt, storyboard discarded); toggle captions on the Video step and see Run settings follow; check video and voiceover file names in the library; (D113) set Cast to One character throughout with a typed description, generate the storyboard and confirm one character entry used by every scene with a person, then regenerate and confirm it stays; look at a narrow (phone) screen without the drawer. **Added at the P-PROJ1 / P-INT1 close:** (P-PROJ1) in Run settings change Look and Image source on a run with a storyboard — the dialog names what is discarded, and Cancel changes nothing; set a Channel identity and save a character in Project settings, then make a new Animated run whose script mentions that character and confirm its bible entry has the saved description and a "Project asset" tag; promote a bible entry with "Save to project"; generate metadata and check it follows the channel identity; optionally run the v0.17 vs v0.18 side-by-side on one real script (`STORYBOARD_STOCK_PROMPT_VERSION=v0.18`) and decide the default. (P-INT1) Settings → Integrations shows five blocks; add an OpenAI key, make OpenAI the Thinking-models default and generate metadata (Run details → Made with shows the model); set it back to Claude; confirm the OPENAI_LLM_MODEL id is valid on the account.

**EPIC 59 — The friends beta: accounts, the Creator flow, credits and payments (D114).** Order: `/audit` → P-AUTH → P-LITE → P-BILL-1 (**beta opens**) → P-BILL-2. Review items C30–C32, reshaped by the operator on 2026-10-13. Detail at each sprint boundary; outline and defaults below.

**P-AUTH — Google sign-in, accounts, tiers, isolation (~24; S1..S9 DONE 2026-10-14, deployed to DEV, smoke PARTIAL → AUTH-S10; handover in DONE.md; S0 is the operator's).** AUTH-S0 (1 pt, first; P-HARD2's smoke was cleared by the operator at the 2026-10-14 review) set the `PROD_URL` GitHub variable and see the post-deploy check pass on PROD; the restore drill stays F1's own item. AUTH-S1 Google OAuth sign-in and account creation; a session per user (replaces the single operator password; the legacy login stays for the owner until switched). AUTH-S2 the user ↔ tenant model: one personal tenant and one hidden default project per user, created at first sign-in. AUTH-S3 thread the user through storage keys, repositories and routes instead of `PLATFORM_USER_ID` (~80 uses) — every run, artifact, library and setting is the user's own. AUTH-S4 **account type Basic / Super (D118, replaces regular / premium / owner)** as an account field and a server-side capability check; the operator's **View as Basic** toggle that changes what the server allows for that session and never charges. AUTH-S6 (was LITE-S6, D118) server-side gating of everything Basic does not have — every Studio route and page answers Basic with 403; Basic lands on `/create`. AUTH-S7 Super's left menu in the new design: My videos, plus Projects, Libraries, Integrations, Defaults and "Open in Studio" on a run, linking to the old pages until P-CORE (D118). AUTH-S5 isolation tests: user A cannot read or write user B's run, project, artifact or library. **Added by the 2026-10-14 audit:** AUTH-S8 server caps and per-tenant spend bounds; AUTH-S9 the D115 moderation gate and terms acceptance; S1, S3 and S6 expanded as in SPRINT.md. Sign-in stays allow-listed until S3 and S6 are merged.

**P-CORE-S11 — DEV smoke of P-CORE (1 pt, Sprint P-BILL-1, with AUTH-S10).** The ten steps in DONE.md [P-CORE] as the owner on DEV; clears that entry's DEFERRED. AC: all pass, or each failure becomes a fix story tagged `fix(P-CORE-Sn)`.

**AUTH-S10 — Finish the P-AUTH smoke (1 pt, Sprint P-BILL-1, first story).** As a second Google account (in `ALLOWED_EMAILS` and the consent screen's test users): terms → `/create` empty; make a short video; `/studio`, `/settings`, `/library` bounce to `/create`; the owner's run id at `/runs/<id>/settings` is 404; owner View as Basic hides the menu and bounces `/studio`; `CAP_RUNS_PER_DAY=1` refuses a second video; a `MODERATION_BLOCKLIST` phrase is refused and appears in `/platform/admin/prompt-log`; after logout the old cookie fails. AC: all pass, or each failure becomes a fix story. Clears the P-AUTH PARTIAL in DONE.md.

**P-CORE — the full Studio in the new design, for Super (~28 pts, D118; DONE 2026-10-14, on DEV; smoke PARTIAL → P-CORE-S11; handover in DONE.md).** The new design (`/create`) gains every Studio feature as Super-only screens and controls, so `studio-v2.html` and the shell pages retire. Stories: **CORE-S1** Super shell — hash routes, left menu, Projects list and New project (2). **CORE-S2** Project page — overview, ideas (shortlist), runs, settings, project assets (4). **CORE-S3** Libraries — videos, audio, footage, AI, music (2). **CORE-S4** Integrations (blocks, keys, models) and Defaults (3). **CORE-S5** New video for Super (project, realistic or animated) and the Script step's three sources: paste, generate with length, from a voiceover (3). **CORE-S6** Voice step — pace and style, voiceover upload, transcript editing and language check (3). **CORE-S7** Realistic look — stock acquisition, asset type, search words, re-acquire, script view, sound effects when `SFX_ENABLED` (4). **CORE-S8** Cast, run language, look change, save to project assets (2). **CORE-S9** Metadata step, CapCut export and upload, Auto-advance (3). **CORE-S10** Retire the old pages: redirects, tests, docs (2). Order: S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10. **Human touchpoint:** the owner runs a whole realistic video, from an idea in a project to a rendered file and metadata, without leaving `/create`.

**P-LITE — the Creator flow for Basic users (D118) (~16; S1..S5 DONE 2026-10-14, smoke PASSED, handover in DONE.md; started 2026-10-14, built before P-AUTH at `/create` from the reviewed mockup — D117; the detail is in SPRINT.md; S6 gating and the D115 moderation checks move to P-AUTH; estimates other than images move to P-BILL-1).** Original outline: LITE-S1 minimal New run: aspect ratio, style (Animation; Realistic greyed), master visual prompt, characters (name + description); stored on the run. LITE-S2 the director works around the given characters: they are given to the storyboard worker as assets and are the **only** characters it may use (extends D113 to several). LITE-S3 voice dropdown (male / female Gemini voice; a per-run `voice` setting; two voices chosen after listening). LITE-S4 the Creator pages: Script (paste only), Voice, Storyboard (scene review, split / merge, motion effect; Script tab hidden; no sound-effect control), Images (estimated cost first, Generate all or per scene, upload your own), Render (captions dropdown, default "none"), download; no Metadata, no Auto-advance, no Integrations / Defaults / Libraries (a "My videos" list), no voiceover upload or CapCut. LITE-S5 `SFX_ENABLED` (default false) honoured by the render and the CapCut export. LITE-S6 server-side gating of everything LITE hides, by tier. Estimates are computed (and shown) here; charging arrives in P-BILL-1.

**P-CORE** — see the sprint outline above (stories written 2026-10-14).

**P-BILL-1 — ledger, credits, charging, limits (~13) — the beta opens. Planned 2026-10-15 (D123); BILL-S1..S5 BUILT 2026-10-15 on branch `claude/p-bill-1` (commit `eaafe87`, PR open, smoke pending; handover in DONE.md).**

## [BILL-S1] Usage ledger
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 · **Status:** built 2026-10-15 (smoke pending) · **Points:** 3
### Goal
Every paid action — LLM call, TTS, transcription, image, render — is one priced entry with its raw (provider) cost, per tenant and run.
### Acceptance Criteria
- [x] Migration `0006_billing.sql`: `usage_entries` (tenant, run, kind, provider/model, units, raw cost USD, credits, status, timestamps); idempotent like 0001–0005
- [x] `cf_platform/core/billing.py`: `UsageEntry`, a store protocol with in-memory and Postgres implementations (the `limits.py` pattern)
- [x] `kind` is one of llm / tts / transcription / image / render; raw cost comes from the existing `EST_*` and image-model price settings; new price settings (`RENDER_USD_PER_MINUTE`, `EST_TRANSCRIPTION_USD_PER_MINUTE`) are ENV with defaults and in `ENV.md`
- [x] Every site that calls `limits.spend_gate` records an entry; the owner's actions are recorded as `exempt` with no credits; View-as-Basic records nothing
- [x] Tests: entry written per kind, owner exempt, view-as writes nothing, in-memory store behaves as the Postgres SQL is written to
### Definition of Done
- [x] All AC checked · suite green except the two sandbox baseline failures · DONE.md updated (smoke pending)

## [BILL-S2] Credits and charging
**Points:** 4
### Goal
One credit unit and a markup; each non-owner tenant has a balance; each paid action holds its price before the provider call, settles on completion and is refunded on failure.
### Acceptance Criteria
- [x] `CREDIT_VALUE_USD` (default 0.01) and `CREDIT_MARKUP` (default 2.0); price in credits = ceil(raw × markup / value), minimum 1 for any non-zero cost; `BILLING_ENABLED` (default false) switches charging on — off means metering only
- [x] `credit_accounts` and `credit_transactions` tables; the balance changes only through one atomic conditional statement; every change is a transaction row (topup, hold, settle, refund, adjustment)
- [x] `billing.reserve(...)` before the provider call (after the daily USD bound), `settle` on success (excess returned when the actual cost is known), `refund` on failure; wired to storyboard, voice, scene images (single and bulk), write-prompt, idea-to-script, render, transcription
- [x] Built as `GET /platform/billing/me` → `prices` (storyboard, voice, render, scene prompt, transcription) plus `estimated_credits` / `credits_per_image` on the images plan, instead of a separate estimate route
- [x] Tests: hold-settle-refund arithmetic, failure refunds in each background path, bulk images refund failed scenes only, billing off changes nothing
### Definition of Done
- [x] All AC checked · suite green except the baseline · DONE.md updated (smoke pending)

## [BILL-S3] Hard limits
**Points:** 2
### Goal
An action that would exceed the balance is refused, naming what it costs and what is left.
### Acceptance Criteria
- [x] 402 with `{detail, cost_credits, balance_credits}` — the message reads "This costs N credits; you have M."; nothing is started and nothing is charged
- [x] Concurrent holds cannot overdraw (conditional update; a two-at-once test)
- [x] A refused hold leaves the daily USD reservation unchanged; a refused daily bound refunds the hold
- [x] Tests: refusal body, no overdraw under concurrency, owner never refused
### Definition of Done
- [x] All AC checked · suite green except the baseline · DONE.md updated (smoke pending)

## [BILL-S4] Owner top-up and admin view
**Points:** 2
### Goal
The owner adds credits to an account and sees every user's balance and usage.
### Acceptance Criteria
- [x] Owner-only routes: `GET /platform/admin/billing/users` (user, balance, spent, last action), `POST /platform/admin/billing/topup` (tenant, credits, note — positive or negative adjustment, never below zero), `GET /platform/admin/billing/usage` (filter by tenant, kind, date)
- [x] An Owner screen in the new design (built as `#settings/credits`, under Settings, owner-only): users table, top-up dialog, usage list, "Give back stuck holds"
- [x] `SIGNUP_CREDITS` (default 0) is granted once at first sign-in
- [x] Not Basic- or non-owner-Super-callable (deny-by-default snapshot updated on purpose)
- [x] Tests: top-up, adjustment floor, owner-only, signup grant once
### Definition of Done
- [x] All AC checked · suite green except the baseline · DONE.md updated (smoke pending)

## [BILL-S5] The Creator sees balance, price and history
**Points:** 2
### Goal
A friend sees how many credits they have, what the next action costs, and what they were charged for.
### Acceptance Criteria
- [x] `GET /platform/billing/me` (Basic-allowed, own tenant only): balance, credit value, markup hidden, recent history
- [x] Creator page: balance in the header, price next to Voice / Storyboard / Create assets / Render, a Credits screen with history, the 402 message shown as the page's error line
- [x] Hidden entirely while `BILLING_ENABLED` is false
- [x] Every call `creator.js` makes is open to Basic (existing test extended)
- [x] Tests: me route isolation (A cannot see B), page strings pinned
### Definition of Done
- [x] All AC checked · suite green except the baseline · DONE.md updated (smoke pending)

### P-BILL-1 follow-ups (from the review of PR #1, 2026-10-15 — not built; deliberately out of the review-fix commit)

## [BILL-F1] Release the daily USD reservation when a hold is refunded or settled down
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 follow-ups · **Status:** backlog · **Points:** 2
### Problem
`billing.reserve()` reserves the action's raw cost against the tenant's daily USD bound (`limits.spend_gate`, D120) next to the credit hold. `refund()` gives the credits back but **not** the day's reservation, and `settle()` below the estimate does not return the difference. A tenant whose actions fail (or settle low) can reach `CAP_DAILY_SPEND_USD` while having spent nothing, and is refused with "usage limit reached".
### Acceptance Criteria
- [ ] `limits` gains `release_spend(tenant, usd)` on the usage store (atomic, never below zero), called by `billing.refund` and by `settle` for the amount returned
- [ ] The release is part of the same transaction as the credit where both are in Postgres (or an idempotent second step keyed by entry id so a retry cannot release twice)
- [ ] Tests: a refunded action restores the day's room; a settle at half the estimate returns half; a double refund releases once
- [ ] Decide whether `CAP_DAILY_SPEND_USD` stays as a second ceiling next to credits (D123 follow-up already noted in DONE.md)

## [BILL-F2] Refund when the action succeeded at the provider but its result could not be used
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 follow-ups · **Status:** backlog · **Points:** 3
### Problem
Several paths settle as soon as the provider call returns and then do more work that can fail: the script route (`transition_run`, `read_artifact` after `settle`), metadata (`write_artifact` after `settle`), the single-image route (the storyboard / manifest update inside `generate_scene_image` is covered, the presigned URL is not), the director's `apply_scene_prompt` 409 ("scene was merged meanwhile"). The user is charged and gets nothing.
### Acceptance Criteria
- [ ] List each paid path and the last step that can still lose the result; move `settle` after that step, or refund when it fails
- [ ] Where the provider's cost is real and the result is lost (a merged scene), decide per path whether the user is charged (policy) and record it in D123
- [ ] Tests: one per path, injecting a failure after the provider call and asserting the balance

**Defaults chosen at the review (D123, change if you disagree):** 1 credit = $0.01 of price; markup ×2 on raw cost; new accounts start at 0 credits (owner top-up only until P-BILL-2); an LLM call is priced at its flat estimate, not its token count; user-supplied provider keys are never charged; the owner and View-as are never charged.

**P-BILL-2 — online payments (~8).** Provider chosen then (Stripe Checkout vs a merchant of record such as Lemon Squeezy / Paddle); prepaid credit packs; receipts; the legal pages (terms, privacy, refunds) belong here at the latest.

**Open (defaults are in D114):** the credit unit and markup; the script length cap; the two voices; whether Realistic stays greyed or hidden; a content policy / moderation stance for strangers' text and generated images (decide at `/audit`).

**EPIC 60 — Hardening after the 2026-10-13 review (Sprint P-HARD1, DONE 2026-10-13, handover in DONE.md; smoke PASSED 2026-10-13).** HARD1-S1 `/audit` and the first `docs/SECURITY.md` (also decides the moderation stance D114 left open). HARD1-S2 a failed TTS call must fail the voice job with a readable error and Retry — today `voice_production.py` sets `mp3_r2_key=""`, falls back to proportional timing and the job reads "complete" with no audio (PROD run `6fe35dab`, 2026-10-10). HARD1-S3 regression suite for `word_match.py` / `align_text_to_words` / `align_text` built from real pastes, including years said as two pairs. HARD1-S4 guard split / merge while a bulk image job runs. HARD1-S5 backfill `.apex/cost-log.jsonl` range entries for P-UX4, P-PROJ1, P-INT1 from commit times. INT2-S1 (Integrations rework) was considered and dropped from this sprint by the operator on 2026-10-13; it stays a candidate under EPIC 58. VERIFY items still unrun: the cap stop and "Regenerate those…" after a bible edit (P-AN1), the v0.17 vs v0.18 side-by-side (PROJ1-S6), a real render after the D107 zoom fix.

**EPIC 60 (continued) — Sprint P-HARD2 (DONE 2026-10-14, handover in DONE.md; smoke DEFERRED to AUTH-S0; findings in docs/SECURITY.md).** Open at P-AUTH: F2, F5, F6, F8, F13 (D115).

## [HARD2-S1] Backups and a restore drill — RUNBOOK section
**Epic:** EPIC 60 · **Sprint:** P-HARD2 · **Status:** done · **Completed:** 2026-10-14 · **Points:** 3 · **Finding:** F1
### Goal
The operator has one written, verifiable procedure for backing up and restoring PROD's Postgres and R2 data, before any stranger's data exists.
### Acceptance Criteria
- [x] `docs/RUNBOOK.md` gains a "Backups and restore" section: what holds state (Postgres, R2; Drive is legacy), what is backed up and how (Railway Postgres backups, R2 object versioning), retention, and who does what
- [x] Exact operator steps to enable Railway backups and to check R2 versioning in the Cloudflare dashboard, each with the expected result
- [x] A restore drill onto a scratch database: steps, how to confirm the data is intact (row counts, one run opens), and a table to record each drill's date and result
- [x] DEV and PROD are named separately; PROD stays on its working version (no release implied)
- [x] `docs/SECURITY.md` F1 status updated to "procedure written; drill pending operator" (it closes only when a drill is recorded); no code and no script (decided 2026-10-13)
- [x] Tests: none for code; link / anchor check if the docs have one
### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · status `done`
### Files to read
- `docs/SECURITY.md` F1, `DECISIONS.md` D025, `docs/RUNBOOK.md`, `ENV.md` (R2 and DB variables)
### Handover
Built in `b6a8b6a` (+ `0caa757` base-image pin); see DONE.md [P-HARD2]. Smoke deferred to AUTH-S0.

## [HARD2-S2] The audit's small fixes
**Epic:** EPIC 60 · **Sprint:** P-HARD2 · **Status:** done · **Completed:** 2026-10-14 · **Points:** 3 · **Findings:** F7, F9, F18, F14, F3, F10, F12
### Goal
Close the one-sitting findings so a stranger's request cannot hit a weak default or a legacy route.
### Acceptance Criteria
- [x] F7: `OPERATOR_PASSWORD` and `SESSION_SECRET_KEY` rejected when empty or shorter than a minimum (ENV-configurable); start-up refuses `ENVIRONMENT=prod` without `SETTINGS_ENCRYPTION_KEY`
- [x] F9: `run_id` in worker request models constrained to the uuid / legacy-id pattern; 422 otherwise
- [x] F18: session cookie `Secure` for every non-local environment
- [x] F14: login lockout keys on the real client IP behind the proxy (`--proxy-headers` / trusted forwarded IP)
- [x] F3 / F10: `/legacy` and the `src/routes/runs.py` router unmounted (or admin-gated, see open point)
- [x] F12: scene and music uploads abort early past the size limit, as the MP4 upload does
- [x] Tests: one failure case per fix; `docs/SECURITY.md` statuses updated; `ENV.md` for any new variable
### Open points to settle in the story
- Unmount `/legacy` outright or admin-gate it? CLAUDE.md names it as the legacy pipeline UI.
- F7 and PROD: PROD is on v0.24.0, so the prod-key check takes effect only at release (CLAUDE.md already says to set a new `SETTINGS_ENCRYPTION_KEY` then). Confirm DEV has the key set before pushing, or DEV will not start.
### Files to read
- `src/config.py`, `cf_platform/core/config.py`, `src/routes/auth.py`, `src/auth.py`, `src/main.py`, `src/routes/runs.py`, `cf_platform/interfaces/routes/workers.py`, `cf_platform/interfaces/routes/studio.py` (upload handlers), `entrypoint.sh`
### Handover
Built in `b6a8b6a` (+ `0caa757` base-image pin); see DONE.md [P-HARD2]. Smoke deferred to AUTH-S0.

## [HARD2-S3] Deploy safety
**Epic:** EPIC 60 · **Sprint:** P-HARD2 · **Status:** done · **Completed:** 2026-10-14 · **Points:** 2 · **Findings:** F11, F20
### Goal
A failed migration or a vulnerable dependency is visible instead of silent.
### Acceptance Criteria
- [x] F11: `/platform/health` reports migration status (applied version, any failure); a failed migration makes it non-OK; an advisory lock stops two instances migrating at once
- [x] A CD post-deploy check calls health and fails the workflow on a failed migration
- [x] F20: `pip-audit` runs in CI (failure policy stated in the story: block on high / known-exploited, warn otherwise); the container runs as a non-root user; the base image is pinned
- [x] Tests: migration-failure health response; `docs/TESTING.md` and RUNBOOK updated
### Files to read
- `cf_platform/core/migrations.py`, `src/main.py:73-85`, `/platform/health` route, `Dockerfile`, `.github/workflows/ci.yml` and the deploy workflow, `requirements.txt`
### Handover
Built in `b6a8b6a` (+ `0caa757` base-image pin); see DONE.md [P-HARD2]. Smoke deferred to AUTH-S0.

**EPIC 53 — Multi-language: Russian (new 2026-10-05, after P-AN1, before P15)** — see the section below.

**EPIC 46 — Research (P15, D094, D097, spec §2–5).** Project research page — a **Research** entry under the open project in the left panel (`docs/ux/IA.md` §3, D105; the entry is not shipped until this sprint), whose results are ticked into the project's **Ideas** tab. Trend research: existing Google Trends, Reddit and YouTube adapters (D050) plus Google News, over a chosen time window, producing ~10 topics each with a summary and the evidence for why it is trending. Competitor research: port from `content-researcher` (D097), project-level channel list, publications from the last 24/48 hours with likes per 1,000 views and outlier score, daily snapshot job. Results are ticked into the shortlist with their evidence. Research must take the project's language and region into account (Russian projects need Russian-language trend and competitor sources — the reason EPIC 53 comes first). Open: orchestrator-with-specialists vs. parallel agents with a synthesis step (spec §26 D); **X.com** — ENV.md records it as excluded under the free-tier constraint, so including it needs a decision on a paid source.

**EPIC 47 — Publishing via n8n (P16, D098, spec §18–21).** `channels` table (tenant level: name, platform, n8n channel key), project default channel, per-run destinations with publish time. Endpoints `due` / `claim` / `result`; API key for n8n. n8n workflow for YouTube (upload early with YouTube's own scheduled-publish time), exported JSON committed to the repo. Publication status in Studio's Metadata stage, replacing the disabled "Upload to channel" button; fills `published_videos`. Instagram as a second destination if time allows. Depends on the Google API audit started in P12.

**EPIC 48 — Server-side Auto Advance (P17, spec §22).** The Studio toggle hands the run to the server-side pipeline (`full_pipeline.py`, HITL gates from P6-S3) so it continues with the browser closed. First task: confirm that pipeline writes the same artifacts in the same places as the stage-by-stage Studio flow, so an auto-advanced run opens cleanly for review. Define which stages may run unattended, where it stops on error or missing input, and add OpenAI direct as the image fallback (D096). Optional: one-way Telegram notifications (D093). **From the 2026-10-03 prod check:** the PROD service sleeps after 6–10 idle minutes (Railway app sleeping) and pipeline work runs as in-process background tasks, so a run with the browser closed would be stopped mid-flight — settle this first (keep the service awake while a run is active, or move the work off the web process).

**EPIC 50 — Word-anchored overlays and a curated SFX library (unplanned, proposed 2026-10-04).** Select a word in a scene to say where the on-screen text appears and where an SFX plays, instead of the fixed rules (text 0.3 s into the scene, SFX at scene start or +0.7 s — D076). Plus a small SFX library of good-quality sounds. Stories E50-S1..S3 in the EPIC 50 section below; not placed in a sprint.

**Parked by D099:** P11-S2 motion presets (EPIC 39), P11-S3 sub-scene asset timeline (EPIC 38), Format tracks, Analytics & attribution.

---

## EPIC 53 — Multi-language: Russian (planned stub; detail at the sprint boundary)

Operator request 2026-10-05. A video can be made in Russian end to end: script, generated voice, uploaded voice (P14b), storyboard content, on-screen text, captions, metadata, and the rendered video. Scheduled after the UI build and before P15, because P15 research needs the project's language and region.

**Decisions (operator, 2026-10-05):**
- **Language is a per-run setting** (`language`, seeded in P14b-S1) with an optional project default. It is not locked per project: a project that already has English videos can make a Russian one. Russian content will mostly live in separate projects, but nothing blocks mixing.
- **AI image prompts stay in English** even in a Russian video. Only what viewers read or hear is in the video's language.

**Story outline (not yet detailed):**
- **Script and storyboard prompts** take a language parameter (docs/PROMPTS.md v0.4 is English-written); voiceover lines, on-screen text and captions come out in the run's language; `ai_prompt` and visual descriptions stay English.
- **Voice:** Gemini TTS voice choice per language; pace and duration estimate (`_estimate_duration`) calibrated for Russian.
- **Uploaded VO:** Deepgram language from the run; coverage check and the P14b transcript edit rule tested on Cyrillic.
- **Text handling:** `_normalize_deepgram_words` and word-index logic tested with Cyrillic (е / ё, punctuation, hyphens) — unverified as of 2026-10-05, first test to write.
- **Render:** fonts with Cyrillic glyphs for captions (Standard, Punch) and on-screen text; a Russian case in the golden render suite; CapCut export checked with the same fonts.
- **Metadata:** YouTube title, description and tags in the run's language.
- **Studio:** language shown at run creation and in the run header; Studio's own labels stay as they are.
- **Human touchpoint:** the operator creates a Russian run (generated voice, and one with an uploaded VO), and renders a video with Russian captions and on-screen text.

---

## EPIC 49 — CapCut export (P13b) — done 2026-10-04

Stories P13b-S1..S4 and their handovers moved to BACKLOG.md at the P14 review (2026-10-05). Handover summary: DONE.md.

---

## EPIC 50 — Word-anchored overlays and a curated SFX library (backlog)

**Why:** the on-screen text and the SFX of a scene follow fixed rules today: text appears 0.3 s after the scene starts, and an SFX plays at the scene start (or 0.7 s in when the scene has text — D076). The operator wants to point at the word where each should land. The same anchors then reach the CapCut draft for free, because the Timeline (D103) already carries the text window and the SFX offset. SFX positions in CapCut were never going to be hand-placed by script; this makes them right at the source. The library half is a separate problem: the Freesound auto-seed was rejected by the operator (D078), so good sounds need to be chosen by ear.

**Suggested order:** E50-S3 (library) can start any time and is independent. E50-S1 → E50-S2 follow. Needs a sprint slot; none proposed. Natural neighbours: before or after P14 (both touch the Storyboard stage).

---

## [E50-S1] Word anchors for on-screen text and SFX — model, timeline, render
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 5
**Depends on:** P13b (Timeline, D103)

### Goal
A scene can say *at which word* its on-screen text appears and *at which word* its SFX plays. Scenes without an anchor behave exactly as today.

### Acceptance Criteria
- [ ] `StoryboardScene` gains optional `on_screen_text_word` and `sfx_word`: indices into the **normalised** voiceover words (the list `start_word` / `end_word` index — `_normalize_deepgram_words`), each required to lie inside the scene's `start_word..end_word`
- [ ] `build_timeline` resolves an anchor to a time from that word's start (`TimelineText.start_ms`, `TimelineScene.sfx_delay_ms`); text still lasts to the scene end. No anchor → today's rule, so the existing golden render scripts stay byte-identical
- [ ] The FFmpeg overlay window and SFX `adelay` read the anchored values from the Timeline; the SFX auto-offset rule (D076) applies only to unanchored scenes
- [ ] The CapCut export needs no change: a test shows an anchored text clip and SFX clip land at the word's time in the draft plan
- [ ] `PATCH …/storyboard/scenes/{id}` accepts both anchors (and `null` to clear); 422 when the word is outside the scene
- [ ] Anchors survive and follow edits (D102): split / merge / Script-view boundary changes keep an anchor whose word is still in the scene, clear one whose word left it, and report what was cleared; a regenerated voiceover clears all anchors (word indices no longer mean the same words)
- [ ] The word-index fix from P13b-S1 is relied on, not repeated: a test with contractions puts the anchor on the intended word
- [ ] Tests: anchor resolution with and without alignment; golden scripts unchanged for unanchored scenes; one new golden for an anchored scene; the edit-survival rules

### Decision (2026-10-04)
On-screen text anchors to a word's **start** only and stays until the end of the scene. An end word (text disappearing early) is not part of this story; it could be added later as an optional `on_screen_text_end_word`.

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/timeline.py` — `assemble_timeline` (text window, SFX offset), `resolve_scene_timing`
- `src/ffmpeg_builder.py` — `_sfx_delay_within_scene_s`, `_audio_section`; `cf_platform/workers/render_worker.py` — `_collect_overlay_filters`
- `src/models.py` — `StoryboardScene`; `cf_platform/workers/storyboard_edit.py` — `replace_boundaries`
- `cf_platform/interfaces/routes/studio.py` — `ScenePatchRequest`, `studio_patch_scene`
- `tests/cf_platform/test_p13b_s1_golden_render.py`, `tools/capcut/draft_plan.py`
- `DECISIONS.md` — D076, D074, D075, D102, D103

---

## [E50-S2] Studio — click a word to set on-screen text or SFX there
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 3
**Depends on:** E50-S1

### Goal
In the Storyboard stage, the operator clicks a word of a scene and chooses *On-screen text here* or *SFX here*; the choice is shown on the word and can be changed or removed.

### Acceptance Criteria
- [ ] Clicking a word opens the small popover already used for split (D102 UI), now with three actions: Split here · On-screen text here · SFX here. Split stays where it is
- [ ] *On-screen text here* asks for the text (prefilled with the scene's current text) and the type, then PATCHes text + anchor; *SFX here* shows the SFX dropdown (with audition, see E50-S3) and PATCHes key + anchor
- [ ] Anchored words are marked in the scene's words (a small T / ♪ marker with a tooltip); clicking a marked word offers *Move*, *Edit*, *Remove*
- [ ] The scene row's existing text and SFX cells keep working; changing them there keeps the anchor, clearing them clears it
- [ ] An edit that clears an anchor (E50-S1) says so in the same message the split / merge / boundaries edits already show
- [ ] Demo mode mocks it; works at phone width
- [ ] Static-page tests pin the popover actions and the routes they call

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator anchors a text and an SFX in two scenes, renders with FFmpeg, and downloads for CapCut; both land on the chosen words

### Files to read
- `src/static/studio-v2.html` — Storyboard stage: word-click split (`confirmSplit`, `split-pop`), `buildSceneRow`, SFX cell
- `tests/cf_platform/test_p13_s3_storyboard_stage.py` (static-page test pattern)
- `docs/UI_GUIDELINES.md`

---

## [E50-S3] A curated SFX library of good sounds
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 5
**Depends on:** —

### Goal
The SFX dropdown offers a small set of sounds that sound right for punchy Shorts, each checked by ear and licensed for use, and the operator can hear one before choosing it.

### Acceptance Criteria
- [ ] A decision (`/decide`) on the source: operator-picked files from a licensed pack or site (CC0 / royalty-free, licence recorded per file) rather than an automated Freesound query — D078 showed ranking by downloads and ratings does not find good sounds. Free-tier rule (CLAUDE.md) checked for any paid pack
- [ ] The manifest (`cf_platform/core/sfx_library.py`) grows beyond the first 8 keys to the sounds the operator actually uses (target 15–25: hits, whooshes, risers, UI sounds, money, alerts), each with `display_name`, `prompt_hint` for the AI suggestion, **source and licence**
- [ ] Files are normalised to one loudness and trimmed (short, no tail noise, no silence at the start) by a script before upload, so every sound sits at the same level against the voiceover and music
- [ ] Upload goes through the existing manual path (`scripts/upload_sfx.py`, D078); `seed_sfx_library.py` and the Freesound search queries are removed from the manifest if unused
- [ ] Studio: an audition button (▶) beside the SFX dropdown plays the sound; presigned URL, no download
- [ ] The AI suggestion prompt keeps working from the manifest (D076); with a larger vocabulary, a check that the prompt stays within its size budget and that "silence" is still the common answer
- [ ] Tests: manifest entries all have licence + source; every key has a backing file in a seeded storage; audition route returns a URL only for present keys

### Open question
Where to find the sounds — the operator picks. Candidates to evaluate: Pixabay audio (free licence), a one-off paid pack, CapCut's own library downloaded by hand (check its licence terms before bundling in a product).

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator opens the dropdown on DEV, auditions each sound, and renders a run with two of them

### Files to read
- `cf_platform/core/sfx_library.py`, `scripts/upload_sfx.py`, `scripts/seed_sfx_library.py`
- `cf_platform/workers/render_worker.py` — `list_available_sfx`, `_copy_all_scene_sfx_to_run`
- `cf_platform/interfaces/routes/studio.py` — `studio_get_sfx_library`
- `DECISIONS.md` — D076, D078

---

## Unassigned backlog

Open stories that belong to no sprint in the current roadmap (D099).

---

## [E54-S1] Chunked voiceover generation for long scripts
**Epic:** E54 — Voice reliability (new 2026-10-10)
**Sprint:** unassigned — operator-requested 2026-10-10, not in the D099 roadmap
**Status:** backlog
**Priority:** high
**Points:** 5
**Depends on:** —
**Blocks:** nothing in flight. Long scripts (~1,400 words, ~9 min of audio) are a coin flip on PROD until this lands.

### Goal
Generate the voiceover for a long script as several shorter Gemini TTS calls and merge them, so one dropped connection costs one chunk and not the whole job — and so a TTS failure is visible to the operator instead of silent.

### Evidence (PROD, run `6fe35dab`, 2026-10-10)
- `build_voice_production_worker` sends the whole script in **one** call (`_call_gemini_tts_sync`): no chunking, no retry, no explicit timeout.
- 1,422 words ≈ 9 min of audio ≈ 5–6 min of Gemini time. Job 19:06 ended with `TTS failed … peer closed connection without sending complete message body (incomplete chunked read)`; the worker swallowed it, fell back to proportional timestamps with `mp3_r2_key=""`, and reported **complete** — Studio showed no voiceover and no error.
- The same script on retry (19:20) succeeded: 26,183,610 bytes (~9m06s), Deepgram aligned 1,401 of 1,422 words.

### Mechanism (operator's request)
1. Split the script into chunks of about **500 words**, cutting at the nearest sentence end (`.`) at or after the target.
2. One Gemini TTS call per chunk, run concurrently up to a cap; each chunk retried (max 2).
3. The same delivery instruction (pace + style, D083) on every chunk.
4. Merge the PCM in order **before** the WAV wrap; one `generated.wav` is stored as today.
5. Deepgram runs **once** on the merged audio, so `word_timestamps`, the storyboard and the CapCut export see one voiceover as they do now.
6. Scripts under the chunk size keep today's single call.

### Acceptance Criteria
- [ ] `split_script_for_tts(text, target_words)` — pure function; cuts at the first sentence end at or after the target; no `.` found → cuts at the next `?`/`!`/newline, else at a word boundary; does not cut at abbreviations (`U.S.`, `Dr.`) or decimals (`3.5%`); concatenating the chunks returns the original text
- [ ] Chunk size, concurrency cap and retry count come from ENV vars (`VOICE_TTS_CHUNK_WORDS`, `VOICE_TTS_CONCURRENCY`, `VOICE_TTS_RETRIES`) documented in `ENV.md`; no hardcoded values
- [ ] Each chunk is retried on connection errors and empty responses; chunk results are merged in script order regardless of completion order
- [ ] A chunk that still fails after retries fails the voice job with a clear message; `voice/status` reports `failed` with the reason and Studio shows it with a retry action — no silent proportional fallback when TTS was attempted and failed
- [ ] Scripts at or under one chunk produce the same call as today (no behaviour change)
- [ ] `total_duration_s` and `word_timestamps` come from Deepgram on the merged audio; merged duration equals the sum of chunk durations
- [ ] TraceEvent records chunk count and per-chunk retries (cost tracking unchanged)
- [ ] Tests: splitter (sentence boundary, no-period fallback, abbreviations, decimals, round-trip), retry then success, retry exhausted → failed job, merge order and length, single-chunk path unchanged

### Open points to settle in the story
- **Seams:** a short silence between chunks (e.g. 150–300 ms) vs. none. Gemini may drift slightly in tone between calls; listen to a 3-chunk sample before fixing the value.
- **Concurrency cap** vs. Gemini rate limits for the paid key; start low (2–3).
- **Deepgram coverage:** `smart_format` returned 1,401 of 1,422 words (numbers merged). Check whether the storyboard coverage check and captions tolerate that on long scripts, or whether the missing words are real.
- Optional later: the same chunking for the Test voice and for regenerated narration.

### Files to read
- `cf_platform/workers/voice_production.py` — `_call_gemini_tts_sync`, `_tts_generate`, `_pcm_to_wav`, `build_voice_production_worker`
- `cf_platform/interfaces/routes/workers.py` — voice background task and `voice/status`
- `cf_platform/interfaces/routes/studio_voice.py` — voice status as Studio reads it
- `docs/TESTING.md`, `CONVENTIONS.md#async-function-discipline`

### Handover
_(blank)_

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## [P8-S7] LLM-vision media scorer — emotion, mood, relevance
**Epic:** E35 — Footage Quality
**Sprint:** unassigned — deferred from P8 to P10, never picked up; not in the D099 roadmap
**Status:** backlog
**Priority:** low
**Points:** 3
**Depends on:** P8-S4

> **Groomed 2026-10-03:** priority med → low. Since this was written, P10-S3 (semantic enrichment + Entity Resolver) and P11-S1 (Visual Director) took over asset relevance, P13 puts the asset choice in the operator's hands, and P14 generates images outright. Revisit only if stock relevance is still a complaint after P14.

### Goal
Replace the metadata-only (resolution) ranking used in P8-S1 with a multimodal LLM evaluation that scores each candidate asset against the scene's `visual_description` on axes that can't be inferred from resolution alone: emotional tone, visual mood, subject relevance, and production quality. One Haiku vision call per candidate evaluated. Returns a numeric score (0.0–1.0); the acquisition loop picks the highest-scoring candidate that also passes the P8-S4 resolution + duration gate.

### Scorer axes (prompt → structured JSON)
| Axis | Weight | Description |
|------|--------|-------------|
| `relevance` | 0.4 | Does the image depict the described subject? |
| `emotional_tone` | 0.3 | Does the mood/feel match the scene intent? |
| `visual_quality` | 0.2 | Professional composition, lighting, not amateur/stock-cliché |
| `diversity` | 0.1 | Penalise if visually similar to already-selected scenes in this run |

### Module contract (`src/media_scorer.py`)
```python
async def score_candidate(
    image_url: str,
    scene_description: str,
    selected_scene_descriptions: list[str],
    anthropic_api_key: str,
    model: str = "claude-haiku-4-5",
) -> MediaScore

# MediaScore: relevance, emotional_tone, visual_quality, diversity, total, passed (total >= 0.60)
```

### Integration point
Plug into `acquire_scene` after resolution gate (P8-S4 hook point): for each resolution-passing candidate, call `score_candidate`; take the highest-scoring one. If none pass the `0.60` threshold, fall back to best-resolution candidate (never leave scene empty).

### Acceptance Criteria
- [ ] `src/media_scorer.py`: `score_candidate` — downloads image, sends to Claude vision, returns `MediaScore`
- [ ] Integrated into acquisition loop after P8-S4 resolution gate; highest-scoring candidate wins
- [ ] `MEDIA_SCORER_ENABLED: bool = False` in `src/config.py` + `ENV.md` (off by default — Haiku vision call adds ~$0.003/scene)
- [ ] `asset_manifest.json`: `qa_vision_score` + `qa_vision_axes` fields per scene when scorer enabled
- [ ] Scorer disabled → resolution-ranked winner selected (P8-S1 behaviour preserved)
- [ ] Tests: happy path (mocked Claude vision); low score → skip to next candidate; scorer disabled → skipped; diversity penalty applied

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
