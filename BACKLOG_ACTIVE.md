# Backlog — Active Stories

_Contains the sprint outlines for P-BILL-1 … P17, the stories added at the 2026-10-21 grooming (legal and payments, platform settings, scale, the API, real motion, style paths) and open unassigned stories. Closed sprints and finished story blocks (P-UX3, P-AN1, P-HARD2 and older) are in BACKLOG.md; recent handovers are in DONE.md._
_Groomed 2026-10-21; the review is `docs/PRODUCT_REVIEW_2026-10-21.md`._
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

**EPIC 58 — Integrations v2 (Sprint P-INT1, DONE 2026-10-11, handover in DONE.md; D112).** Integrations grouped into blocks (Thinking models, Audio models, Image generation, Stock acquisition, Destination); a provider interface per block; several providers per block, each with its own key and model, one default. Project keys are the default and usage is charged to the user's balance; a user's own key becomes their default automatically, with a checkbox to keep the project default. Review items C25–C27. ~13–16 pts. See D109. **INT1-S5 — DEV smoke sweep (DONE 2026-10-13 by the operator, except step 12: OpenAI as default and metadata on it, left open until the rework below; was: smoke for P-UX4, closes the deferral, 2 pts, added at the P-UX4 close, operator decision 2026-10-11).** **INT2-S1 (candidate, operator 2026-10-13; groomed 2026-10-21: PLAT-S1 takes the image-model part and MOTION-S2 adds a video block, so settle INT2-S1's shape before the video block is built; the own-key exemption of D123 point 4 also waits here) — rework the Integrations page and approach:** the five-block page and the default/model-per-provider model were judged to need a rethink; running on the platform's models is fine for now. Bring the P-AUTH design (user keys vs platform keys, D109 point 5) into it before rebuilding, and clear the open OpenAI smoke item there. Run the P-UX4 smoke list on DEV, after P-INT1 is built: create a run from the minimal modal (Animated + master prompt) and walk five steps with Next only; upload a voiceover, switch Script to Generate, generate a voice over it (confirm prompt, storyboard discarded); toggle captions on the Video step and see Run settings follow; check video and voiceover file names in the library; (D113) set Cast to One character throughout with a typed description, generate the storyboard and confirm one character entry used by every scene with a person, then regenerate and confirm it stays; look at a narrow (phone) screen without the drawer. **Added at the P-PROJ1 / P-INT1 close:** (P-PROJ1) in Run settings change Look and Image source on a run with a storyboard — the dialog names what is discarded, and Cancel changes nothing; set a Channel identity and save a character in Project settings, then make a new Animated run whose script mentions that character and confirm its bible entry has the saved description and a "Project asset" tag; promote a bible entry with "Save to project"; generate metadata and check it follows the channel identity; optionally run the v0.17 vs v0.18 side-by-side on one real script (`STORYBOARD_STOCK_PROMPT_VERSION=v0.18`) and decide the default. (P-INT1) Settings → Integrations shows five blocks; add an OpenAI key, make OpenAI the Thinking-models default and generate metadata (Run details → Made with shows the model); set it back to Claude; confirm the OPENAI_LLM_MODEL id is valid on the account.

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

## [SWEEP-1] DEV smoke of P-BILL-1 and its close-out; open the beta
**Epic:** EPIC 59 · **Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 2
### Goal
Everything built in P-BILL-1 and its close-out has run once on DEV with real providers, and `BILLING_ENABLED=true` is set only after it did.
### Acceptance Criteria
- [ ] The seven smoke steps in DONE.md (P-BILL-1) pass as owner and as a second Google account, billing off, then on
- [ ] Close-out smoke (DONE.md, P-BILL-1 close-out): a refused or failed action restores the day's cap; `/privacy` and `/terms` signed out; an existing account re-accepts; `scripts/erase_tenant.py` dry run on a test account
- [ ] DEV log read: no `billing: could not settle|refund`, no `key=` other than `REDACTED`, migrations 0006 and 0007 `ok`
- [ ] BILL-F3 operator inputs: `scripts/cost_report.py` with the invoices, `EST_*` set, `nano-banana-2-1` at 0.03 and `IMAGE_RESOLUTION=2K` on DEV (PROD already has 2K)
- [ ] The markup against one real video's raw cost, and the Credits screens on a phone
### Files to read
`DONE.md` (P-BILL-1, close-out, BETA-0), `docs/RUNBOOK.md` (Calibrating prices, Erasing an account), `docs/SECURITY.md` (audit 2026-10-22)

## [AUDIT-2] Re-check the 2026-10-23 and 2026-10-26 fixes before billing opens
**Epic:** EPIC 59 · **Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 1
Run `/audit` scoped to the HIGH-1 and HIGH-2 fixes, BILL-F3's zero-price refusal, the invite list (D124) and the render gate; update `docs/SECURITY.md`.

## [BILL-F1] Release the daily USD reservation when a hold is refunded or settled down
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 close-out (gate for `BILLING_ENABLED`, raised 2026-10-21) · **Status:** built 2026-10-22 (smoke pending) · **Priority:** high · **Points:** 2
### Problem
`billing.reserve()` reserves the action's raw cost against the tenant's daily USD bound (`limits.spend_gate`, D120) next to the credit hold. `refund()` gives the credits back but **not** the day's reservation, and `settle()` below the estimate does not return the difference. A tenant whose actions fail (or settle low) can reach `CAP_DAILY_SPEND_USD` while having spent nothing, and is refused with "usage limit reached".
### Acceptance Criteria
- [x] `limits` gains `release_spend(tenant, usd)` on the usage store (atomic, never below zero), called by `billing.refund` and by `settle` for the amount returned
- [x] The release is part of the same transaction as the credit where both are in Postgres (or an idempotent second step keyed by entry id so a retry cannot release twice)
- [x] Tests: a refunded action restores the day's room; a settle at half the estimate returns half; a double refund releases once
- [x] Decide whether `CAP_DAILY_SPEND_USD` stays as a second ceiling next to credits (D123 follow-up already noted in DONE.md)

## [BILL-F2] Refund when the action succeeded at the provider but its result could not be used
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 close-out (gate for `BILLING_ENABLED`, raised 2026-10-21) · **Status:** built 2026-10-22 (smoke pending) · **Priority:** high · **Points:** 3
### Problem
Several paths settle as soon as the provider call returns and then do more work that can fail: the script route (`transition_run`, `read_artifact` after `settle`), metadata (`write_artifact` after `settle`), the single-image route (the storyboard / manifest update inside `generate_scene_image` is covered, the presigned URL is not), the director's `apply_scene_prompt` 409 ("scene was merged meanwhile"). The user is charged and gets nothing.
### Acceptance Criteria
- [x] List each paid path and the last step that can still lose the result; move `settle` after that step, or refund when it fails
- [x] Where the provider's cost is real and the result is lost (a merged scene), decide per path whether the user is charged (policy) and record it in D123
- [x] Tests: one per path, injecting a failure after the provider call and asserting the balance

**Defaults chosen at the review (D123, change if you disagree):** 1 credit = $0.01 of price; markup ×2 on raw cost; new accounts start at 0 credits (owner top-up only until P-BILL-2); an LLM call is priced at its flat estimate, not its token count; user-supplied provider keys are never charged; the owner and View-as are never charged.

**P-BILL-2 — online payments and the full legal set (~16, ~20 with BILL2-S3; was ~8, expanded 2026-10-21).** Stories BILL2-S1..S7 and the pre-beta LEGAL-S1 are in the section "Stories added at the 2026-10-21 grooming" below. Provider chosen then (Stripe Checkout vs a merchant of record such as Lemon Squeezy / Paddle); prepaid credit packs; payment method and receipts; consumer terms; data export and account deletion.

**Open (defaults are in D114):** the credit unit and markup; the script length cap; the two voices; whether Realistic stays greyed or hidden; a content policy / moderation stance for strangers' text and generated images (decide at `/audit`).

**EPIC 60 — Hardening after the 2026-10-13 review (Sprint P-HARD1, DONE 2026-10-13, handover in DONE.md; smoke PASSED 2026-10-13).** HARD1-S1 `/audit` and the first `docs/SECURITY.md` (also decides the moderation stance D114 left open). HARD1-S2 a failed TTS call must fail the voice job with a readable error and Retry — today `voice_production.py` sets `mp3_r2_key=""`, falls back to proportional timing and the job reads "complete" with no audio (PROD run `6fe35dab`, 2026-10-10). HARD1-S3 regression suite for `word_match.py` / `align_text_to_words` / `align_text` built from real pastes, including years said as two pairs. HARD1-S4 guard split / merge while a bulk image job runs. HARD1-S5 backfill `.apex/cost-log.jsonl` range entries for P-UX4, P-PROJ1, P-INT1 from commit times. INT2-S1 (Integrations rework) was considered and dropped from this sprint by the operator on 2026-10-13; it stays a candidate under EPIC 58. VERIFY items still unrun: the cap stop and "Regenerate those…" after a bible edit (P-AN1), the v0.17 vs v0.18 side-by-side (PROJ1-S6), a real render after the D107 zoom fix.

**EPIC 60 (continued) — Sprint P-HARD2 (DONE 2026-10-14, handover in DONE.md; smoke DEFERRED to AUTH-S0; findings in docs/SECURITY.md).** Open at P-AUTH: F2, F5, F6, F8, F13 (D115).

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

> **Groomed 2026-10-21:** priority medium → low for E50-S1..S3. Sound effects are off by default (`SFX_ENABLED`, P-LITE-S5, D114) and Basic never sees them; nobody has asked for them in the beta. Revisit when real users ask.

**Suggested order:** E50-S3 (library) can start any time and is independent. E50-S1 → E50-S2 follow. Needs a sprint slot; none proposed. Natural neighbours: before or after P14 (both touch the Storyboard stage).

---

## [E50-S1] Word anchors for on-screen text and SFX — model, timeline, render
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** low
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
**Priority:** low
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
**Priority:** low
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

## Stories added at the 2026-10-21 grooming (product review: `docs/PRODUCT_REVIEW_2026-10-21.md`)

Points are the grooming's estimates; refine at `/start-story`. Order and gates are in the review, section 5. "Open" lines are decisions for the operator.

### Candidates promoted from DONE.md that had no story (P-BILL-1 and P-AUTH handovers)

- **BILL-F3 (3 pts, medium)** — settle LLM and voice calls at actual usage (tokens, characters) instead of the flat `EST_LLM_CALL_USD` / `EST_TTS_CALL_USD`. Needs one month of real ledger rows to know whether it matters; do after the beta has data.
- **BILL-F4 (2 pts, medium)** — gate the acquisition worker and every other paid call outside `spend_gate` / `billing.reserve` (SECURITY.md) before a second Super account exists.
- **SEC-S1 (3 pts, high before public sign-up)** — the audit leftovers named in SECURITY.md: F16 key rotation, F19 `ffprobe` validation of uploaded media, a Content-Security-Policy header. Run a fresh `/audit` first (payments, the API and photo uploads will exist by then). Sprint P-SCALE2.
- **AUTH-F1 (1 pt, low)** — purge expired sessions and unused OAuth states. SCALE-S2's janitor can carry it; keep as its own line so it is not lost.

---

## EPIC 59 (continued) — Legal and payments

## [BILL-F3] Check the prices against measured cost before the beta opens
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 close-out (gate for `BILLING_ENABLED`, drafted from the 2026-10-22 audit, MEDIUM-1) · **Status:** built 2026-10-26 (code; the operator inputs below are open) · **Priority:** high · **Points:** 2
### Problem
The daily USD bound and the credit price rest on flat estimates: `EST_LLM_CALL_USD`, `EST_TTS_CALL_USD`, `EST_RENDER_USD`, `EST_IDEAS_USD` settle at the estimate, not at the provider's usage. `CREDIT_MARKUP` is 1.0 and the image price table says `nano-banana-2-1: 0.02` while published videos run at 2K and cost 0.03 (CLAUDE.md operator actions). A long script or a 1200-word storyboard can cost more than the estimate, so real spend per tenant per day can pass `CAP_DAILY_SPEND_USD` and credits under-charge. A price of 0 makes an action free and skips `spend_gate` (`limits.py`, `usd <= 0`).
### Acceptance Criteria
- [x] `scripts/cost_report.py`: counts per kind from `usage_entries` beside the configured prices, and the implied cost per action from invoices passed with `--bill`. **Changed from the draft:** `worker_executions` / `trace_events` hold no LLM, TTS or render cost (never filled), so invoices are the source; capturing real usage is the existing token-settling candidate
- [ ] **Operator:** run the report against DEV traffic with the invoices, set `EST_*`, set `nano-banana-2-1` to 0.03 with `IMAGE_RESOLUTION=2K`, (`CREDIT_MARKUP` decided 2026-10-26: stays 1.0 for the beta, recorded in D123)
- [x] A non-owner action priced at 0 is refused at start-up validation or at `reserve` (a zero price must be a decision, not a typo); test
- [x] Image-model strings for non-owner tenants must be a key of `IMAGE_MODEL_COSTS_USD` (audit MEDIUM-2); test
### Not in scope
Settling LLM calls at real token counts (existing candidate story).
### Files to read
`cf_platform/core/billing.py` (`price_credits`, `reserve`), `cf_platform/core/limits.py`, `cf_platform/core/tenant_settings.py`, `ENV.md`, `docs/SECURITY.md` (audit 2026-10-22)

## [LEGAL-S1] Legal minimum before the beta opens
**Epic:** EPIC 59 · **Sprint:** P-BILL-1 close-out (gate for `BILLING_ENABLED`) · **Status:** built 2026-10-22 (smoke pending) · **Priority:** high · **Points:** 4
### Goal
Before friends' data is held with billing on, the product says what it keeps, why, who else sees it and how to have it deleted — and the owner can actually delete it.
### Acceptance Criteria
- [x] `/privacy` page, served like `/terms`: who the controller is and how to reach them (the owner supplies name, address, e-mail), the data held (Google name, e-mail and `sub`; scripts, voices, images, videos; prompts in `prompt_log`; the usage ledger; session rows), purpose and legal basis for each, retention for each, the rights (access, correction, erasure, objection, complaint to the supervisory authority) and how to use them
- [x] Sub-processor list on the same page: Anthropic, Google (sign-in and Gemini), OpenAI (optional moderation, images), kie.ai, Deepgram, Cloudflare (R2), Railway, the stock sites (search words only — confirm no personal data goes), the payment provider later. Each with its purpose and where the data goes; the owner confirms the transfer mechanism for each US provider
- [x] Terms rewritten: what the service is, minimum age (open), acceptable use (D115), who owns what the user makes, AI-generated content notice, credits are not money until P-BILL-2 says otherwise, liability, termination, governing law. `TERMS_VERSION` bumped so existing accounts re-accept at next sign-in (AUTH-S9 mechanism)
- [x] Links to terms and privacy on the sign-in page and in the `/create` footer
- [x] Retention decided and written: `prompt_log` N days (then deleted by a job), deleted videos, expired sessions (AUTH-F1), and whether the director's storyboard is kept next to the user's final one for improving the product (STYLE-S1) — if kept, say so in the notice
- [x] RUNBOOK "Erasing an account" procedure plus `scripts/erase_tenant.py` (dry-run by default, prints what it would remove): users, sessions, projects, runs, library files in R2, `prompt_log`; the credit ledger is anonymised, not deleted, if it must be kept for accounting
- [x] Tests: both pages render; a bumped terms version re-prompts a signed-in user; the erase script removes one tenant's rows and files in the in-memory store and leaves another tenant's untouched
- [ ] **Human step:** the owner (or a lawyer) reviews the final text; this story does not claim legal sufficiency
### Open
Minimum age (13 / 16 / 18 — a bedtime-story feature makes minors plausible). Who is the seller and controller (company or sole trader) — also needed by BILL2-S1.
### Files to read
`src/static/terms.html`, `src/main.py` (terms gate), `cf_platform/core/accounts.py`, `cf_platform/core/moderation.py` (`prompt_log`), `docs/SECURITY.md`, `docs/RUNBOOK.md`

---

**P-BILL-2 — online payments and the full legal set (~16, ~20 with BILL2-S3; was ~8, expanded 2026-10-21).** BILL2-S1..S7 below; S3 only if the operator chooses subscriptions. Human touchpoint: a friend buys a credit pack, sees the receipt, adds or removes a payment method, exports their data and deletes their account.

## [BILL2-S1] Payment provider decision and credit-pack checkout
**Epic:** EPIC 59 · **Sprint:** P-BILL-2 · **Status:** backlog · **Priority:** high · **Points:** 4
### Goal
A user buys a pack of credits by card and the balance rises, exactly once.
### Acceptance Criteria
- [ ] `/decide`: Stripe Checkout versus a merchant of record (Paddle, Lemon Squeezy or similar). The deciding facts: who the seller is, EU VAT handling, invoices, chargebacks, fees. Recorded with the options and what was rejected
- [ ] Credit packs (sizes and prices in config, not code); a "Buy credits" button on the Credits screen opens the provider's hosted page — card data never touches the server
- [ ] Webhook: signature verified, idempotent on the provider's event id, writes one `topup` credit transaction carrying the payment reference; a replayed event changes nothing
- [ ] Test mode only until the owner says otherwise: provider test keys and test cards; live keys are never entered by an agent
- [ ] Tests: signature failure, replay, partial failure between payment and credit, refund/chargeback event reduces the balance and never below zero
### Open
Subscriptions as well as packs (review, decision 1)?

## [BILL2-S2] Payment method, portal and receipts
**Points:** 3 · **Priority:** high
### Goal
A user can add, change or remove their payment method and see every receipt, without us storing a card.
### Acceptance Criteria
- [ ] "Payment method" opens the provider's hosted customer portal (add / remove / default); a customer id is stored per tenant, nothing else
- [ ] Receipts and invoices listed on the Credits screen with links to the provider's documents
- [ ] A failed or declined payment shows a plain message and leaves the balance unchanged
- [ ] Tests: portal link needs a signed-in user and is scoped to their own customer id (A cannot open B's)

## [BILL2-S3] Subscription plans (only if chosen)
**Points:** 4 · **Priority:** conditional on the operator's answer
### Goal
A monthly plan that grants credits each period.
### Acceptance Criteria
- [ ] Plans in config; a monthly credit grant on each successful renewal; unused credits carry over or expire (decided with the plan); upgrade, downgrade, cancel at period end; failed-payment retry and the user's message
- [ ] Tests: grant once per period, cancel stops the grant but keeps the balance

## [BILL2-S4] Consumer terms for selling credits
**Points:** 2 · **Priority:** high
### Goal
The sale itself is lawful for EU consumers.
### Acceptance Criteria
- [ ] Checkout shows the price with VAT where the provider does not; the order is confirmed with the withdrawal notice for digital content, and the user agrees to start immediately and acknowledges the effect on the 14-day right (wording checked by a human)
- [ ] Refund policy page; unused-credit expiry stated if any; terms mention payments, links to them at checkout
- [ ] **Human step:** legal review of the wording

## [BILL2-S5] Self-service data export
**Points:** 3 · **Priority:** medium
### Goal
A user downloads what the product holds about them.
### Acceptance Criteria
- [ ] "Export my data" on the account screen builds a zip in the background: profile, projects, runs (scripts, storyboards, metadata), links or files for their videos and voice, ledger and history; a signed link by e-mail or on the page, expires in 24 h
- [ ] Rate-limited to one a day; owner sees it in the admin view
- [ ] Tests: the export holds only the caller's rows

## [BILL2-S6] Self-service account deletion
**Points:** 3 · **Priority:** high
### Goal
A user deletes their account and its data, and the product proves it.
### Acceptance Criteria
- [ ] "Delete my account" with a re-confirmation and a short grace period (7 days, cancellable); then the LEGAL-S1 erase runs; sessions revoked; the ledger anonymised
- [ ] Remaining credit balance is stated before confirmation and the refund rule (BILL2-S4) applies
- [ ] The owner gets a line in the admin view; the user gets a confirmation
- [ ] Tests: after deletion no row or file with the tenant id remains except the anonymised ledger; another tenant is untouched

## [BILL2-S7] Storage statement and AI-content disclosure
**Points:** 1 · **Priority:** medium
### Goal
Say honestly what browser storage is used, and mark generated content where rules ask for it.
### Acceptance Criteria
- [ ] Privacy notice states the one session cookie and the `localStorage` keys the pages use; if only strictly necessary items remain, no consent banner is shown. Re-check this each time a page adds a key
- [ ] The Metadata step reminds the user to use the platform's "altered or synthetic content" setting when publishing, and the video's description template offers a disclosure line. Check the exact EU AI Act transparency obligations that apply to this kind of output (faceless narration, illustrative images) and their dates; record the result in the notice
- [ ] **Human step:** confirm the above with a lawyer

---

## EPIC 61 — Platform settings and beta polish

## [PLAT-S1] Image model as a platform setting; one price that follows model and resolution
**Epic:** EPIC 61 · **Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 5
### Goal
The owner chooses the image model for the platform (Nano Banana through kie.ai, or OpenAI) in one obvious place, and every price in the product — estimates, credits, caps, ledger — follows that choice.
### What exists
The owner already picks a provider and model in Integrations, and Basic accounts use it (`resolve_image_config`, source "platform"). Prices come from `IMAGE_MODEL_COSTS_USD`, keyed by model only; the resolution is one Railway variable (`IMAGE_RESOLUTION`) the price ignores. CLAUDE.md records the consequence: published videos need 2K and a 0.03 entry.
### Acceptance Criteria
- [ ] Settings → Platform (owner only): "Image generation" with provider, model and resolution (1K / 2K / 4K) saved as the platform default; the screen says which accounts it affects (all Basic; Super unless overridden)
- [ ] Price table keyed by provider, model **and resolution** (extend `IMAGE_MODEL_COSTS_USD`, old model-only keys stay as fallback); an unknown combination uses `IMAGE_COST_USD` and is marked "estimated" in the owner view
- [ ] One function gives the price; everything reads it: the images plan (`estimated_credits`, `credits_per_image`), the confirm text, `GET /platform/billing/me` prices, the ledger's raw cost, `IMAGE_RUN_SPEND_CAP_USD`, the daily USD reservation, the Super cost readout. A test greps for any other reader of `IMAGE_COST_USD` / `IMAGE_MODEL_COSTS_USD`
- [ ] A change applies to the next estimate without a restart; ledger rows already written are never repriced
- [ ] When a run already holds images from another model, the images screen warns that the look may differ
- [ ] Basic sees no model names; the credit price reflects the current choice
- [ ] `IMAGE_RESOLUTION` stays as the fallback when nothing is saved; the CLAUDE.md operator blocker is removed
- [ ] The saved model id is checked against the known list for its provider (the open medium finding from the P-AUTH audit: allow-list the image `model` string)
- [ ] Tests: price per combination, switching mid-session, past ledger rows unchanged, `billing/me` reflects the switch, Basic cannot read or write the setting
### Open
Does Super choose per project / run (then PLAT-S1b), or is it one platform choice? Which OpenAI model: `gpt-image-1` direct, or `gpt-image-2` through kie.ai? Does the image look differ enough between models to need a per-run lock?
### Files to read
`cf_platform/core/tenant_settings.py`, `image_provider.py`, `ai_images.py` (`model_cost_usd`), `cf_platform/interfaces/routes/studio_ai.py` (`_model_cost`, the plan), `routes/billing.py`, `limits.py`, `src/static/ui/core.js` (Integrations), `ENV.md`

## [PLAT-S2] Voice samples that play at once
**Epic:** EPIC 61 · **Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 3
### Goal
Pressing Listen on a voice plays within a second, every time, for everyone.
### What exists
`GET /platform/creator/voice-samples/{voice}` stores a recording in R2 after the first request and serves the stored one afterwards. A click that still takes 5–10 s means one of two things: the first request per voice is what is heard, or the stored-file check is failing and the sample is re-made each time (that check sits inside `except Exception: pass`).
### Acceptance Criteria
- [ ] Measure first on DEV: time the route for a stored versus a new sample, and log why the stored check misses if it does; fix the cause
- [ ] `scripts/make_voice_samples.py` makes a 5-second sample for every listed voice from a fixed, written line, as mp3 (about a tenth of the wav's size), uploads it to `voice-samples/<language>/<voice>.mp3`, and skips what exists unless `--force`
- [ ] The Voice step gets the sample address with the voice list (`sample_url` on each voice in `creator/config`); the route never calls Gemini in the request path. Decide: a public bucket prefix behind Cloudflare's cache for these non-personal files, or presigned URLs; user files stay presigned either way
- [ ] The first sample is fetched when the Voice step opens, so the first click is instant
- [ ] A listed voice without a stored sample is an owner-visible error at start-up or in the admin view, not a delay for the user
- [ ] Per language when P-LANG lands (the key already carries the language)
- [ ] Tests: config lists a sample address for every voice, the route does not generate, the script is idempotent, every listed voice has a key in a seeded storage
### Human touchpoint
The operator presses Listen on every voice on DEV on a phone; each starts in under a second.

---

## EPIC 62 — Scale and speed (new 2026-10-21)

**Target (to confirm in SCALE-S1):** 100 registered users, about one in five working at the same time, then 1000. Gate: `SIGNUP_OPEN` stays unset until the load test passes at the agreed number.
**Principle:** measure before changing anything (SCALE-S1); then move work out of the web process (S2, S3), then the data path (S4), then provider limits (S5).

## [SCALE-S1] Measure: step timings, provider limits, a load model
**Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 3
### Goal
Know where the minutes of one video go and what breaks first, with numbers.
### Acceptance Criteria
- [ ] Wall time per step (script, voice, storyboard, each image batch, acquisition, render, metadata) as p50 and p95 from the trace and lineage data already stored, plus the time spent waiting for a render slot
- [ ] `docs/PERF.md` gains a 2026-10 section: where the time of one 60-second video goes on DEV; Railway CPU and memory during a render
- [ ] Each provider's published rate and concurrency limits and our current tier: Anthropic, Gemini TTS, kie.ai, Deepgram, R2, Railway plan. Where it is not published, ask the provider and record the answer
- [ ] A load model: at 100 and at 1000 users, videos per hour, renders per hour, image calls, tokens, dollars per hour
- [ ] `scripts/loadtest.py` drives N simulated users through voice, storyboard, images and render with fake providers (the preview harness is the base) and reports the first thing that breaks and at what N
- [ ] Output: a ranked list that confirms or reorders S2–S5. No optimisation in this story
### Files to read
`docs/PERF.md`, `cf_platform/core/trace_repo.py`, `cf_platform/core/limits.py`, `scripts/preview_core.py`

## [SCALE-S2] A durable job queue
**Sprint:** P-SCALE1 · **Status:** backlog · **Priority:** high · **Points:** 5 · **Depends on:** SCALE-S1
### Goal
A restart, a deploy or a crashed worker does not lose work or strand a hold.
### Acceptance Criteria
- [ ] `jobs` table in Postgres (migration): kind, tenant, run, state, attempts, lease and heartbeat, payload, result; workers claim with `FOR UPDATE SKIP LOCKED`; no new dependency (if a queue library is wanted, a D-entry first)
- [ ] Kinds moved over one at a time: render first, then voice, storyboard, images, transcription, metadata; the web process enqueues and reads the row for status (less polling of R2)
- [ ] A job whose lease expires is retried or failed with a readable reason, and its hold is closed by the janitor — this replaces the manual "Give back stuck holds"; the janitor also purges expired sessions (AUTH-F1)
- [ ] In-process execution stays as the local and test mode behind a flag
- [ ] Tests: crash mid-job, lease expiry, two workers racing, hold closed once, restart recovery
### Files to read
`cf_platform/interfaces/routes/workers.py`, `studio_ai.py`, `studio_voice.py`, `cf_platform/core/billing.py` (`_in_flight`, `refund_stale_holds`), `cf_platform/core/limits.py`

## [SCALE-S3] Render workers off the web process
**Sprint:** P-SCALE1 · **Status:** backlog · **Priority:** high · **Points:** 5 · **Depends on:** SCALE-S2
### Goal
Renders run on their own Railway service(s), so ten people rendering do not slow everyone's page.
### Acceptance Criteria
- [ ] The same image started with `WORKER_MODE=render` claims render jobs; `RENDER_MAX_CONCURRENT` becomes per worker; more replicas mean more renders; the per-tenant limit stays
- [ ] The user sees their place in the queue ("3rd in line"); a long wait is stated, not silent
- [ ] Temp-disk cleanup after each job; output upload verified before the job is marked done
- [ ] Encode-time experiments with measured results (libx264 preset, scene threads, the zoom cost D107 recorded); keep only what leaves the golden renders unchanged or update them on purpose
- [ ] RUNBOOK: how to add a worker and how to read its logs
- [ ] Tests: job claimed by a worker, queue position, golden renders unchanged

## [SCALE-S4] Web tier and data path
**Sprint:** P-SCALE1 · **Status:** backlog · **Priority:** medium · **Points:** 3
### Goal
More than one web instance is safe, and nothing reads a whole folder listing per request.
### Acceptance Criteria
- [ ] No process-local state that must be shared: the render gate, `billing._in_flight`, any in-memory usage store move to the database
- [ ] Database pool size and statement times reviewed (the billing store once hung on a pool of four under many refusals — pinned by a test, check the others)
- [ ] The library and run progress read from an indexed table rather than listing R2 run folders on each request ("nothing is indexed" in P-UX3); PERF.md notes the 1000-prefix truncation
- [ ] Static assets cacheable with a version in the address (today `/ui/*` is `no-cache`); polling intervals lengthened or replaced by one status stream
- [ ] Generated assets are stored under a tenant prefix (promoted from the P-AUTH handover), which also makes erasing an account (LEGAL-S1, BILL2-S6) a prefix delete
- [ ] Idle sleep off on the services that need to stay awake (shared with P17)
- [ ] Tests: two app instances against one database

## [SCALE-S5] Provider capacity and backpressure
**Sprint:** P-SCALE1 · **Status:** backlog · **Priority:** medium · **Points:** 3
### Goal
A busy provider makes users wait politely instead of fail, and one user cannot take everyone's slots.
### Acceptance Criteria
- [ ] Shared per-provider concurrency limits (Gemini, kie.ai, Anthropic, Deepgram) across all users and instances
- [ ] A 429 or overload is retried with the provider's wait time and shown as "busy, retrying", not as a failure
- [ ] Fair scheduling: a tenant's share of image and voice slots is capped when others wait
- [ ] Second key or fallback provider for TTS and images where one exists; an owner alert when the day's platform spend passes a threshold
- [ ] Speed levers measured in S1 applied here, including chunked voiceover (E54-S1) so a long script's voice is made in parallel
- [ ] Tests: 429 handling, fairness under two tenants
**Beyond 100:** a design for 1000 users (read replica, job partitioning, R2 lifecycle, regions) is written after the 100-user test, not before.

---

## EPIC 63 — Platform API for automation (Super; new 2026-10-21)

**Prerequisites:** SCALE-S2 (durable jobs) and P17 (the pipeline runs on the server with the browser closed). Today Auto-advance runs in the browser tab, so the API cannot be built on it. P16 (n8n pulls finished videos to publish) is the other direction and pairs with this epic.

## [API-S1] API keys for Super accounts
**Points:** 3 · **Priority:** high
### Goal
A Super account creates a key, an automation calls the platform with it, and the owner can revoke it.
### Acceptance Criteria
- [ ] Migration: `api_keys` (id, tenant, name, hash of a 32-byte random token shown once, display prefix, scopes, created, last used, expires, revoked)
- [ ] Settings → API (Super): create (shown once), list, revoke; `Authorization: Bearer cf_…`; a Basic account cannot create or use one; View-as never applies
- [ ] The middleware turns a key into the owner-account's principal (same tenant, same caps, same credits); per-key rate limit; keys never appear in logs (extend the redaction)
- [ ] Deny-by-default snapshot updated on purpose; API routes live under `/api/v1` only
- [ ] Tests: revoked key refused, wrong tenant, Basic refused, key not in logs
- [ ] Scoped `/audit` of this surface before it goes live

## [API-S2] Create a video: `POST /api/v1/videos`
**Points:** 5 · **Priority:** high · **Depends on:** API-S1, SCALE-S2, P17
### Goal
One call starts a whole video and returns at once.
### Acceptance Criteria
- [ ] Body: `script`, or `idea` and `length_s` (open); `aspect_ratio`; `language`; `type` — `realistic` | `animated`, an open list that grows (style packs, EPIC 65); `master_style`; `voice`; `captions` — `none` or a style id; `bg_music` — a library track id or `none`; `characters` — ids of the account's AI assets; `metadata` — true to also write title, description and tags; `max_credits`; `idempotency_key`; `callback_url` (API-S5)
- [ ] Answers 202 with `{id, status, estimated_credits}`; 402 when the estimate exceeds the balance or `max_credits`; 422 naming the bad field and the valid values; the same `idempotency_key` returns the same video
- [ ] The whole pipeline runs on the server: voice, storyboard, images or stock acquisition, render (and metadata); billed through `billing.reserve` for the full estimate, refunded on failure; moderation, caps and the render queue apply as for the UI
- [ ] A failure ends as `failed` with a readable reason and a refund — never a silent hang
- [ ] Tests: each field validated, idempotency, 402, a failing step refunds, tenant isolation

## [API-S3] Status and download
**Points:** 2 · **Priority:** high
### Goal
The caller sees progress and fetches the file.
### Acceptance Criteria
- [ ] `GET /api/v1/videos/{id}`: `queued | running (step) | succeeded | failed | canceled`, progress, credits charged, and on success `video_url` plus title / description / tags when requested
- [ ] `GET /api/v1/videos/{id}/download` redirects to a short-lived presigned URL an n8n HTTP node can follow; `GET /api/v1/videos` lists the caller's own; a cancel call stops a queued or running video and refunds
- [ ] Tests: another tenant's id is 404, expired link, cancel refund

## [API-S4] Reference lists and the OpenAPI document
**Points:** 1 · **Priority:** medium
### Goal
A workflow can discover valid values.
### Acceptance Criteria
- [ ] `GET /api/v1/voices | characters | music | caption-styles | styles`; an OpenAPI document for `/api/v1` only, with examples, served at `/api/v1/openapi.json`

## [API-S5] Webhooks (if chosen)
**Points:** 3 · **Priority:** low until decided
### Goal
The platform tells the caller when a video is done.
### Acceptance Criteria
- [ ] `callback_url` must be https and not a private address (SSRF guard); signed with HMAC-SHA256 and a timestamp; retried with back-off; a delivery log the owner can read; polling stays the baseline

## [API-S6] Documentation and an n8n example
**Points:** 2 · **Priority:** medium
### Goal
Someone new can build the n8n flow in an hour.
### Acceptance Criteria
- [ ] `docs/API.md`: keys, errors, limits, credit behaviour, examples in curl; an exported n8n workflow (create, wait, download) committed beside the P16 publish workflow when that exists

---

## EPIC 64 — Real-motion animation (image-to-video; Super first, Basic later; new 2026-10-21)

**What it is:** for each scene, the Visual Director defines the first frame (and optionally the last frame) and a motion prompt; an image-to-video model, reached through kie.ai, turns them into a clip; the render uses the clips. Off by default; a run-level toggle plus a per-scene switch, because a clip costs many times a still. **What exists:** the director's `motion_note` per scene, the `asset_strategy` / `asset_tier` fields, the `ImageProvider` pattern, and a renderer that already places video clips. The scene `clip_type: "animated"` value is a legacy name; check what still reads it before reusing it.

## [MOTION-S1] Spike: choose the image-to-video model(s)
**Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 2
### Goal
Know which models to build on, what a clip costs, and how a 2–4 second scene maps to a clip.
### Acceptance Criteria
- [ ] List the image-to-video models kie.ai offers today (verify at the time; do not rely on this document) with: price per second, clip lengths, resolution, 9:16 and 16:9 support, first-frame only or first and last frame, typical wait time
- [ ] Make at least six clips from existing DEV scene images, two with first and last frame; judge consistency with the animated style and with the character
- [ ] Decide how a clip fits a scene shorter or longer than itself (trim, slow down within a limit, hold the last frame, loop) and what happens to the clip's own sound (dropped)
- [ ] Output `docs/MOTION_SPIKE.md` and a `/decide`: the models, the default, the credit price per second at the current markup, and the cost of a 60-second video fully animated versus a third animated. No product code

## [MOTION-S2] `VideoProvider` interface and the kie.ai client
**Points:** 3 · **Priority:** medium · **Depends on:** MOTION-S1
### Acceptance Criteria
- [ ] A `VideoProvider` beside `ImageProvider`: start a clip from first frame, optional last frame, prompt, duration and aspect; poll; timeout; readable errors; a fake for tests
- [ ] A price table per model per second, like the image table; a sixth Integrations block "Video generation" with the platform default set the way PLAT-S1 sets images
- [ ] Tests: start, poll, timeout, error mapping

## [MOTION-S3] The director writes the motion prompt and picks the frames
**Points:** 4 · **Priority:** medium
### Acceptance Criteria
- [ ] The animation storyboard worker (prompt `an-v0.2`) and the scene prompt writer produce, per scene, a `motion_prompt` (camera and subject action, short) from the existing `motion_note`; scenes unfit for motion (charts, text-heavy) are flagged
- [ ] Scene fields `motion_mode` (`still` | `ai_video`), `motion_prompt`, `last_frame_mode` (none | next scene's first frame | a generated end image); first frame is the scene's own generated image
- [ ] The prompt sent to the model is assembled in code (master style, bible lines, motion prompt) and can be previewed, as the image prompt is; the user can edit it; the moderation gate covers it
- [ ] Tests: assembly, flags, migration of old storyboards (field absent means `still`)

## [MOTION-S4] Generate the clips: job, billing, caps
**Points:** 5 · **Priority:** medium · **Depends on:** MOTION-S2, MOTION-S3, SCALE-S2 (or the same restart-safe pattern the image job uses)
### Acceptance Criteria
- [ ] "Animate N scenes" shows the estimate in credits first; per-run cap `VIDEO_RUN_SPEND_CAP_USD`; concurrency limit; one retry; stop after repeated identical failures; regenerate one scene
- [ ] Billing: hold per clip, settle at the clip actually made, refund on failure; the ledger gets kind `video`
- [ ] Clips stored under the run (`clips/scene-N.mp4`) and recorded in the manifest and the library
- [ ] Tests: hold, settle, refund; cap stop; restart does not pay twice

## [MOTION-S5] Render and CapCut with clips
**Points:** 4 · **Priority:** medium
### Acceptance Criteria
- [ ] The timeline accepts `ai_video` assets and fits each to its scene by the S1 policy; no camera-move effect on top; captions, on-screen text and transitions unchanged
- [ ] A golden render with a fixture clip in both aspect ratios; the CapCut export carries the clips
- [ ] CPU and disk per render measured and recorded (D107 notes the zoom cost)

## [MOTION-S6] Interface: toggle, per-scene control, estimate
**Points:** 3 · **Priority:** medium
### Acceptance Criteria
- [ ] Run settings: "Motion — Camera moves on stills (default) | Real motion"; storyboard card: per-scene switch, motion prompt, clip preview; the cost before any generation; Super only to start

## [MOTION-S7] Open real motion to Basic
**Points:** 2 · **Priority:** low until S1–S6 are smoked
### Acceptance Criteria
- [ ] Allow-list change; the price in credits visible; default off; a cheaper model tier for Basic if S1 found one; owner switch `MOTION_BASIC_ENABLED`; terms and privacy mention AI video

---

## EPIC 65 — Style paths (unplaced; analysis and logging only, new 2026-10-21)

Different styles need different directors: Animation (general), Manga, Documentary, Movie, more later. Not needed now. The question of a custom-trained model is answered in `docs/PRODUCT_REVIEW_2026-10-21.md` section 6 (do not train yet; build the evaluation first; training data is a legal question).

## [STYLE-S1] Evaluation harness and the model analysis
**Points:** 5 · **Priority:** medium
### Acceptance Criteria
- [ ] 8–10 fixed scripts across genres; a rubric (shot variety, continuity, pacing against the narration, adherence to the style, valid output) scored by a model judge with a human spot check; `scripts/compare_storyboards.py` runs two prompt versions side by side; results kept in `docs/evals/`
- [ ] First job: the v0.17 vs v0.18 Realistic comparison that was never run (PROJ1-S6), then the default is decided
- [ ] Written analysis with data: do prompt, exemplars and retrieval plateau, and would fine-tuning or a trained model help? What data could be used lawfully?
- [ ] Log, per run, the director's storyboard beside the version finally rendered (LEGAL-S1 covers the consent line), so training and evaluation data accumulate

## [STYLE-S2] Style pack registry
**Points:** 5 · **Priority:** medium · **Depends on:** STYLE-S1
### Acceptance Criteria
- [ ] A style pack = id, label, director prompt id, default master style, shot and motion vocabulary, caption and music defaults, allowed image models, price modifier; run field `style_pack` (default `animation`)
- [ ] The storyboard worker picks its prompt by pack; today's `an-v0.1` becomes pack `animation-general` with the prompt text byte-identical (golden test)
- [ ] New video and project settings list the packs; the API's `type` and `styles` list read the same registry

## [STYLE-S3] Documentary pack · [STYLE-S4] Movie pack · [STYLE-S5] Manga pack
**Points:** 3 · 3 · 8 (tbd) · **Priority:** low until S1 and S2
Manga likely needs more than a prompt: panel-style moves and reveals in the renderer, an image model or reference images that hold screentone and line work, and possibly real motion (EPIC 64). Decide after STYLE-S1's evidence.

---

## EPIC 66 — Character reference photos (new 2026-10-21; reference images were deferred in D108)

**What it is:** a user attaches a photo to a character — their own face, say — and every image in which that character appears keeps the person's features, drawn in the run's master style (animation, watercolour, and so on). **What exists:** characters are text only (name and description in the run, the AI assets library and project assets); the image providers take a text prompt and no input image (`cf_platform/core/image_provider.py`). Which models accept reference images, and how well they hold a likeness inside a strong style, is not known from the repository — REF-S1 finds out.
**Design chosen in grooming (recommendation, change if you disagree):** do not send the raw photo with every scene. Make **one stylised portrait of the character in the master style from the photo**, show it to the user, and use the approved portrait as the reference for the scenes. The user sees what they will get before 14 images are paid for, the photo goes to the provider once, and consistency comes from a reference that is already in the style.
**Sensitive by nature:** a face photo is personal data, and a likeness can be misused (someone else's face, a public figure, a child). The privacy and consent work in REF-S2 is part of the feature, not an extra. Build order: after LEGAL-S1 and, for full self-service deletion, BILL2-S6. Behind a switch `CHARACTER_PHOTOS_ENABLED` (default false) so the owner can open it to Super first.

## [REF-S1] Spike: which models keep a likeness in a style
**Sprint:** P-PLAT · **Status:** backlog · **Priority:** high · **Points:** 2
### Goal
Know which image model, through kie.ai or OpenAI, holds the person's features while following the master style, and what it costs.
### Acceptance Criteria
- [ ] List the models that accept one or more reference images today (verify at the time; do not rely on this document): how many references, input size, aspect ratios, price against a text-only image
- [ ] With the operator's own photo, three styles (the animation default, a painterly one, a near-realistic one) and several scenes (close, medium, wide shot): judge likeness and style adherence side by side; try both routes — the photo as the reference in every scene, and one stylised portrait used as the reference
- [ ] Record where it fails (wide shots, strong styles, two characters, glasses, hair) and the best prompt wording for "keep the features, use this style"
- [ ] Output `docs/REF_SPIKE.md` and a `/decide`: the route (portrait first or direct), the default model for scenes with a reference, the limit on references per image. No product code

## [REF-S2] Upload, storage and consent
**Sprint:** P-REF · **Status:** backlog · **Priority:** high · **Points:** 4 · **Depends on:** LEGAL-S1
### Goal
A photo can be attached to a character safely: kept private, used only for that character, removed with it.
### Acceptance Criteria
- [ ] Upload on the character dialog (run), in the AI assets library and in project assets; JPEG, PNG or WebP up to a size limit from config; re-encoded on upload with metadata (location, camera) removed; one photo per character to start
- [ ] Stored under a private, tenant-prefixed key (never a public prefix, never in another account's library); read only through short-lived presigned links for the owner
- [ ] A consent line the user must tick on each upload: the photo is of them, or of someone who agreed; if the person is a child, the user is the parent or guardian. Stored with the upload (who, when, terms version)
- [ ] The photo is deleted with the character, with the run, with the account (LEGAL-S1 erase script, BILL2-S6), and is part of the data export (BILL2-S5)
- [ ] Moderation: the image moderation step used elsewhere (D115) applies to uploads; the prompt log records that an upload was made (not the image); rules against public figures and impersonation in the terms. The product cannot reliably recognise a face, so the terms, the consent line and a "report a problem" path carry that load — say so plainly in the notice
- [ ] Privacy notice and sub-processor list updated: the photo goes to the image provider; retention stated. **Human step:** decide with legal advice whether children's photos are allowed at all at launch (the bedtime-story use makes this likely); the safe default is not to allow them until decided
- [ ] Tests: another tenant cannot read or list the photo; metadata is gone after upload; deleting the character deletes the file; oversize and wrong-type files refused; flag off hides the control and refuses the route

## [REF-S3] Reference-aware image generation
**Sprint:** P-REF · **Status:** backlog · **Priority:** high · **Points:** 5 · **Depends on:** REF-S1, REF-S2, PLAT-S1
### Goal
Images of a character with a photo keep the person's features in the run's master style.
### Acceptance Criteria
- [ ] `ImageProvider.generate` takes optional reference images; the kie.ai and OpenAI clients use their editing or reference routes; a model without reference support refuses with a plain message instead of quietly ignoring the photo
- [ ] "Character portrait": one call makes a stylised portrait from the photo in the master style; the user approves it or regenerates (priced, shown first); the approved portrait is stored with the character and becomes the reference for scenes (route chosen in REF-S1)
- [ ] The prompt assembled in code (`build_animation_prompt`) adds the "keep the features of the reference, draw in this style" line for scenes whose entities include a character with a reference, and attaches only that character's reference; scenes without that character are unchanged
- [ ] Several characters in one scene use their references up to the model's limit, then fall back to the descriptions
- [ ] The price follows the model and resolution (PLAT-S1) including any extra cost of reference input; billing holds and settles as for any image
- [ ] Changing the photo or the portrait flags the scenes whose images are now out of date, the way a bible edit does
- [ ] Tests: reference attached only to matching scenes, refusal on an unsupported model, portrait approval flow, out-of-date flags, price with reference

## [REF-S4] Interface
**Sprint:** P-REF · **Status:** backlog · **Priority:** medium · **Points:** 3 · **Depends on:** REF-S2, REF-S3
### Goal
Adding a face to a character is obvious and shows the result before the user pays for the whole video.
### Acceptance Criteria
- [ ] Character dialog: "Add a photo", the consent tick, the photo, a "Make my portrait" button with its price, the stylised result with Approve / Try again; the cast chips show the portrait
- [ ] The same control in the AI assets library and project assets, so one saved character with a face is reused across videos
- [ ] The images step says when a scene uses a face reference; phone width checked
- [ ] Hidden while `CHARACTER_PHOTOS_ENABLED` is off; Basic and Super both get it when on

**Notes for neighbours.** Real motion (EPIC 64): the clip's first frame carries the face, so MOTION-S1 should test whether the face holds through a clip. The style paths (EPIC 65) decide how strongly a style may bend a face. The evaluation harness (STYLE-S1) can score likeness once REF-S1 has a way to judge it.

---

## Unassigned backlog

Open stories that belong to no sprint in the current roadmap (D099).

---

## [E54-S1] Chunked voiceover generation for long scripts
**Epic:** E54 — Voice reliability (new 2026-10-10)
**Sprint:** unassigned — operator-requested 2026-10-10, not in the D099 roadmap
**Status:** backlog
**Priority:** medium
**Points:** 5
**Depends on:** —
**Blocks:** nothing in flight. Long scripts (~1,400 words, ~9 min of audio) are a coin flip on PROD until this lands.

> **Groomed 2026-10-21:** priority high → medium. A TTS failure is no longer silent (P-HARD1-S2 raises it with a Retry button) and Basic scripts are capped at 450 words (~3 min), so only the owner's long scripts are exposed. It returns as a **speed lever in SCALE-S5** (chunks made in parallel); do it there.

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

> **Groomed 2026-10-21:** unchanged at low; if nobody asks for better stock relevance by the next grooming, delete it (the animated path is where the beta is).
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
