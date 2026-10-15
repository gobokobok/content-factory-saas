# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last sprints (P-BILL-1, P-CORE, P-AUTH, P-LITE, P-HARD2, P-HARD1, P-INT1, P-PROJ1, P-UX4, P-AN1, P-UX3) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P-BILL-1] Usage ledger and credits — S1 ledger, S2 credits and charging, S3 hard limits, S4 owner top-up and admin view, S5 the Creator's balance, price and history
**Completed:** 2026-10-15 (built in one pass on branch `claude/p-bill-1` in a cloud sandbox, commit `eaafe87`; **pull request open, not merged; nothing has run on DEV**). AUTH-S10 and P-CORE-S11 (the two live smokes) are the operator's and have not run.
**Handover:**
- **Ledger (S1)** `cf_platform/core/billing.py` + migration `0006_billing.sql`: `usage_entries` (one priced row per paid action: kind llm / tts / transcription / image / render, units, raw provider cost, actual cost, credits, status held → settled / refunded, or `exempt` for the owner and `metered` while billing is off), `credit_accounts` (`CHECK balance >= 0`), `credit_transactions` (every balance change, signed; a unique index makes the sign-up grant once-only). Store protocol with in-memory and Postgres implementations, as in `limits.py`.
- **Credits (S2, D123)** price = ceil(raw × `CREDIT_MARKUP` / `CREDIT_VALUE_USD`), at least 1 for any non-zero cost (defaults ×2 and $0.01: a $0.05 call is 10 credits). `billing.reserve()` takes the hold **before** the provider call (credits first, then the existing daily USD bound; a refused daily bound gives the hold back), `settle()` closes it at the actual cost when known (excess returned; an overrun is absorbed by the platform), `refund()` returns it when the action failed. Wired into: storyboard, voice, render, voiceover transcription, single and bulk scene images (bulk settles at the images actually made), write-prompt, idea-to-script (settled at the iterations that ran) and **metadata** (which `spend_gate` never covered). Routes take the hold after every check that can refuse the request, so a 402 starts nothing and discards nothing. **`BILLING_ENABLED` defaults to false**: the ledger meters (records what each action would cost) and nothing is held or refused, so merging changes nothing for the existing accounts.
- **Hard limits (S3)** `PaymentRequiredError` → 402 `{detail, cost_credits, balance_credits}`; "The voiceover costs 10 credits; you have 5." The balance cannot be overdrawn by concurrent holds (one conditional `UPDATE`; also a `CHECK` in the table).
- **Owner (S4)** owner-only `GET /platform/admin/billing/users`, `POST …/topup` (by email or tenant, positive or negative, never below zero, actor and note recorded), `GET …/usage` (filters), `POST …/refund-stale` (gives back holds whose job never finished, `BILLING_HOLD_TTL_MINUTES`); an owner-only **Settings → Credits** screen in `/create` (accounts table, top-up dialog, usage list); `SIGNUP_CREDITS` granted once at first Google sign-in.
- **Creator (S5)** `GET /platform/billing/me` (Basic-allowed, own tenant, no tenant parameter): balance, flat prices, last 30 priced actions. `/create` shows a Credits entry with the balance, the price on the Voice and Storyboard buttons, the price in credits in the images confirmation, and a Credits screen with the history; all of it hidden while billing is off. A refusal appears as the page's usual error line (the server's sentence).
- ENV added: `BILLING_ENABLED`, `CREDIT_VALUE_USD`, `CREDIT_MARKUP`, `SIGNUP_CREDITS`, `BILLING_HOLD_TTL_MINUTES`, `EST_TRANSCRIPTION_USD` (see ENV.md). Migration `0006`. Decision **D123**. No new dependency.
- Tests: **3353 passing** in the cloud sandbox (+125: 47 core, 13 job wiring, 48 routes with real sessions, 17 page checks) plus 6 integration tests against a real Postgres (`tests/integration/test_billing_postgres.py`, `CF_TEST_DATABASE_URL`). The 2 golden-render tests (`test_golden_each_motion_effect_portrait` / `_landscape`) fail in this sandbox only because of its ffmpeg build and were not touched. One older test's fake background function gained a `hold=None` parameter.
- **Files that mattered:** `cf_platform/core/billing.py`, `cf_platform/interfaces/routes/billing.py`, `cf_platform/interfaces/routes/workers.py` (where each hold is taken and closed), `studio_ai.py` (`_run_billed_image_job`), `src/static/ui/creator.js` (`loadBilling`, `priceTag`, `showCredits`), `src/static/ui/core.js` (owner Credits screen), `tests/test_p_auth_billing_routes.py`.
**Found while building:** the first Postgres store asked the connection pool for a second connection to read the balance after a refused hold while still holding the first; with the app's pool of 4, several refusals at once would hang. Only the real-Postgres run showed it (fixed; pinned by `test_many_refused_holds_do_not_exhaust_the_pool`).
**Not verified:**
- **Nothing has run on DEV or Railway.** Migration 0006 and the SQL were run against a throwaway local Postgres 16 (applied twice; concurrent holds, refusals, the once-only grant, the summary query, the `CHECK`), not against DEV's database.
- No provider was called: every voice, storyboard, image, render, transcription and metadata path was run with a fake provider. The real cost of one video in credits at the default markup has not been seen.
- The pages were driven in a headless Chromium against a local in-memory server (friend: balance, prices, history; owner: users table, top-up to 410, menu entry; no page errors). The phone-width layout and the dialog on a real account were not looked at.
- Settling is exact for images, transcription (minutes) and scripts (iterations that ran). **LLM calls (storyboard, director, metadata) and voice are priced at their flat estimates** (`EST_LLM_CALL_USD`, `EST_TTS_CALL_USD`), not their token or character counts, so a real call can cost more or less than it is charged.
- D123 point (4), "a user's own provider key is never charged", is **not built**: no non-owner can save a key today (Integrations is Super-only), so there is nothing to exempt yet.
- Holds are closed by the background job that took them; a restart mid-job leaves the hold open until the owner presses "Give back stuck holds" (nothing does it automatically).
- `/audit` was not run; `docs/SECURITY.md` says it is still due before `BILLING_ENABLED` is turned on.
**Smoke test:** DEFERRED — needs the branch merged and deployed to DEV (migration 0006 applies at start-up), after AUTH-S10 and P-CORE-S11. Steps (as the owner on DEV, with a second Google account in `ALLOWED_EMAILS`):
1. With `BILLING_ENABLED` unset: sign in as the friend and make a short video as before; nothing is refused. As the owner, Settings → Credits lists the friend with the actions as `metered` and what each would have cost.
2. Set `BILLING_ENABLED=true`: the friend's Credits entry shows 0; "Generate voiceover · 10 credits" is refused with "The voiceover costs 10 credits; you have 0." and no job starts.
3. Owner: Settings → Credits → Top up the friend by 500; the friend's balance updates after the next action or reload.
4. The friend makes a video start to finish; each step is charged once; the Credits screen history matches; the owner's usage list shows raw provider cost beside the credits, and you can judge `CREDIT_MARKUP`.
5. Make a step fail on purpose (revoke a key, or an unreachable provider): the friend is refunded and the history says Refunded.
6. Bulk images with some scenes failing: only the images made are charged.
7. As the owner (and under View as Basic) make a step: nothing is charged and the owner's balance does not move.
**Promoted to backlog:**
- **Run the scoped `/audit` on DEV before `BILLING_ENABLED` is turned on** (money paths; SECURITY.md lists what to check).
- Gate the acquisition worker and any other paid call outside `spend_gate` before a second Super account exists (SECURITY.md).
- LLM-token and TTS-character settling (replace the flat estimates with the provider's usage).
- Automatic refund of stale holds (a janitor, with the session purge already listed under P-AUTH).
- Own-key exemption (D123 point 4) when non-owners can save keys (INT2-S1).
- Per-user daily spend (`CAP_DAILY_SPEND_USD`) is now a second ceiling next to credits; decide at the first month's data whether to keep it.
- VERIFY (operator, DEV): the markup against one real video's raw cost; the Credits screens on a phone.
- VERIFY (Claude, DEV logs): `billing: could not settle|refund` should never appear.

---

## [P-CORE] The Studio in the new design — S1 shell and Projects, S2 project page, S3 Libraries, S4 Integrations and Defaults, S5 New video and Script sources, S6 Voice, S7 realistic look, S8 cast / language / look, S9 Metadata / CapCut / Auto-advance, S10 retire the old pages
**Completed:** 2026-10-14 (built in one pass on `sprint/p-core`, merged and on DEV the same day; closed with the UX pass that followed the operator's first DEV use)
**Handover:**
- **UX pass 2 (2026-10-14):** AI assets library (`/platform/creator/assets`, stored in the tenant's Creator project config; pick on New video and in the settings Cast; "Save to AI assets" in the storyboard entry dialog); Images library (`images` kind: stock + AI stills; filter Stock / AI generated); BG music without SFX plus the tenant's uploads; named Gemini voices with a cached sample (`/platform/creator/voice-samples/{voice}`); script locked once a voiceover exists (409 on the voice route, "Start a new video from this one"); previous render kept as `output/final-<stamp>.mp4`; delete video (archive, `DELETE /platform/creator/runs/{id}`); Basic has no script generation; video settings panel reordered (Auto-advance, Format, Look, Language, Master style, Cast AI Director/Custom). Not enforced server-side: master-style lock after the first image; format is fixed at creation.
- **Mobile / UX pass after the first DEV smoke (2026-10-14):** at ≤820px the panels float over the page with a scrim (nothing is squeezed; Escape or a tap on the scrim closes; the left panel starts closed and closes after a choice); the two panel buttons scroll with the page and come back as a solid bar with a shade when the user scrolls up. Explanatory text moved from the screens into the Information panel (`CFApp.addHelp/setHelp`; Core's screens register theirs; "cannot be changed later" notes removed). Basic gets script generation (`POST /platform/blocks/idea-to-script` on the allow-list; caps, moderation and spend gate already apply) and voice speed/style (the worker already composes them into the Gemini instruction). Library: search is an icon beside the title; BG music lists the platform's tracks and the tenant's uploads only (no SFX, no type filter).
- **Basic has Libraries too:** Videos, AI generations and BG music for a Basic account (`GET /platform/library/{videos|ai|music}`, tenant-scoped; Audio and Footage stay Super's, refused in the route as well as by the allow-list). Basic loads `core.js` for that screen only; project links and filter are hidden for it.
- **Left panel (the beta's):** Runs first (the landing page for everyone; no New video / My videos buttons); for Super, section headers Projects (All projects, and the open project's Overview / Ideas / Runs / Settings), Libraries (Videos, AI generations, BG music) and Settings (Integrations, Defaults) in one flowing list with no rules; View as Basic and Log out at the bottom. Audio and Footage libraries remain reachable at `#library/audio` and `#library/footage`.
- **Host:** `src/static/ui/creator.js` hands unknown hash routes to `window.Core`, exposes `window.CFApp` (state and helpers) and loads `/ui/core.js` only when `/auth/me` says the session is effectively Super. `core.js` loads `core-run.js`. `super-menu.js` links to the screens. `/ui/*` is served `no-cache`.
- **S1–S4 (`core.js`):** routes `#projects`, `#project/<id>[/ideas|runs|settings]`, `#library/<kind>`, `#settings/integrations|defaults`. Ports of the old projects, project, library and settings pages onto the same routes, in the new design; nothing new on the server. A tenant's hidden personal project is filtered out of `/platform/projects`.
- **S5:** New video for Super picks a project and a look; language and format come from the project, else Defaults; "Start video" from ideas passes the ideas through `POST /projects/{id}/runs` and then writes the run's settings. `POST /platform/creator/runs` accepts `look` (realistic = stock, no characters) and `project_id`; both are Super-only and the project is scoped to the caller's tenant. Script step: Paste / Generate (length 30–600 s via `/platform/blocks/idea-to-script`, now capped, moderated and spend-gated for non-owners) / From a voiceover.
- **S6:** narration pace and style on the Voice step; voiceover upload (`voice-source`, `voice/upload`, transcription poll), transcript word editing and "Rebuild from text", language check and `PUT …/language`; replacing an uploaded voice asks first.
- **S7:** `isStock()`; "Acquire footage / Acquire N missing / Re-acquire all" through `/platform/workers/acquisition`; per scene: asset type, search words, "Find again" (`reacquire`), own file, sound effect when `SFX_ENABLED`; Script view (boundaries with a dry run).
- **S8:** right panel: Look (realistic ↔ animated through `PUT …/visuals` with the 409 confirm), Language, Cast (free / one person with a project character or text); "Save to project assets" in the character dialog.
- **S9:** a fifth step Metadata (`/platform/workers/metadata`, copy buttons); CapCut package download and edited-video upload; Auto-advance (script → voice → storyboard → footage → render → metadata; stops at image generation, which asks for the estimate, and after one failed attempt at a step).
- **S10:** `/`, `/studio` → hop page; `/project`, `/library`, `/settings` → 302 to the screen; deleted `studio-v2.html`, `studio.html`, `projects.html`, `project.html`, `library.html`, `settings.html`, `create-run.html`, `ui/shell.*`, `ui/app.*` and the five test files that grepped them. New: `tests/test_p_core_pages.py`. D121.
- **Server changes:** creator config adds `sfx_enabled` and a script limit by account type (Basic 450, Super tenant `CAP_SCRIPT_WORDS`, owner 20000); empty Railway variables count as unset (found on DEV after P-AUTH).
- **Preview harness:** `scripts/preview_core.py` + `core-preview` in `.claude/launch.json` — local server, in-memory storage, `GET /__seed/{run_id}` seeds a 3-scene stock storyboard. Never for real data.
- No new dependency, no migration, no new ENV variable. Tests: 3218 passing (about 80 old page tests removed, about 60 added).
- **Files that mattered:** `src/static/ui/core.js`, `core-run.js`, `creator.js`, `cf_platform/interfaces/routes/creator.py`, the retired `studio-v2.html` (git history) for the call sequences.
**Not verified:**
- Everything above was looked at in a local preview with fake storage: screens render, routes switch, the realistic storyboard shows its controls and the settings panel works. **No provider call was made**: script generation, voice upload and transcription, stock acquisition, re-acquire, metadata, CapCut export and upload, render of a realistic run, and Auto-advance end to end have not run.
- Pixel-level parity with the old pages was not checked, and the mobile layout of the new screens was not looked at.
**Smoke test:** PARTIAL — PASSED on DEV 2026-10-14 (operator, desktop and a phone): the new shell, panels, Libraries (Videos, Images, AI assets, BG music), New video, Script / Voice / Storyboard / Render screens and the settings panel were used and reviewed through an iteration of UX fixes. REMAINS: the provider-backed steps below (script generation, voice upload and transcription, realistic stock acquisition and re-acquire, CapCut, metadata, Auto-advance end to end), and the voice samples (listen to the eight voices) → cleared by P-CORE-S11 in Sprint P-BILL-1.
**Steps (after the DEV deploy lands, as the owner):**
1. `/create` lands on Projects. The old addresses `/studio`, `/project?id=…`, `/library?kind=ai`, `/settings?tab=defaults` land on their screens.
2. Project → Settings: change the niche and a default; Ideas: add an idea; Videos: filter.
3. Start a video from the idea: Realistic, English. Script → Generate (90 s) → a script appears. Next.
4. Voice: pace Fast, Generate voiceover, play it. Next.
5. Storyboard: Create storyboard; "Acquire footage". Open a scene: change the search words, "Find again"; set one scene to Upload and upload a file.
6. Render: render the video; play it; download the CapCut package.
7. Metadata: generate; copy the title.
8. Second video: Auto-advance from a pasted script: it should run voice → storyboard → footage → render → metadata, and stop with a readable message if anything fails.
9. Script step → From a voiceover: upload a recording; edit a word in the transcript; the storyboard step works from it.
10. Libraries: the video appears with its project and a working Download. Integrations: a provider's model change saves. Defaults: spend cap saves.
**Promoted to backlog:**
- P-CORE-S11 (1 pt, Sprint P-BILL-1): run the DEV smoke above; each failure becomes a fix story.
- VERIFY (operator, DEV): the new screens on a phone-width window.
- VERIFY (Claude, DEV logs): no 4xx from `/platform/studio/runs/*/…` calls the screens make that the Studio used not to make.
- Candidate: delete the pre-P12 import, `pipeline.html` and the legacy routes when `LEGACY_ROUTES_ENABLED` is no longer wanted.

---

## [P-AUTH] Accounts and isolation — S1 Google sign-in and sessions, S2 tenants, S3 scoped repos and guards, S4 Basic / Super + View as, S5 isolation tests, S6 deny-by-default gating, S7 Super menu, S8 caps and spend bounds, S9 moderation and terms
**Completed:** 2026-10-14 (built in one pass on `sprint/p-auth` while the operator was away; merged to `main` and deployed to DEV the same day, commit `c5a7dbe`). AUTH-S0 (`PROD_URL`) is the operator's.
**Handover:**
- **S1** `cf_platform/core/accounts.py` (users, sessions, principal), `google_oauth.py` (code flow + PKCE, no dependency), `src/routes/auth.py` (`/auth/google/start|callback`, `/auth/me`, `/auth/view-as`, `/auth/terms/accept`, `/auth/providers`; password login now issues a session), migration `0005_accounts.sql` (`users`, `sessions`, `oauth_states`, `tenant_usage`, `prompt_log`), `src/main.py` middleware (principal, Origin check, terms gate, Basic gating). The legacy constant cookie works as the owner while `ACCEPT_LEGACY_COOKIE` (default true).
- **S2** a Google user gets tenant `u_<random>` and a hidden default project `default-<tenant>` that is also their Creator project; the owner's e-mail (`OWNER_EMAILS`) maps onto tenant `operator`, so the owner keeps every run, project and key.
- **S3** `PLATFORM_USER_ID` is gone from the routes (87 uses → `current_tenant_id()`); `interfaces/guards.py` (router-level scope guard on path and JSON-body `run_id`, `require_owner`); repos take `tenant_id`; library, run and project lists, counts and activity are tenant-filtered; `DELETE /runs/{id}` and run settings are behind the guard; F5 fixed (a non-owner's unreadable key is a 409, never the owner's key).
- **S4** account type is a field, re-derived from `OWNER_EMAILS` / `SUPER_EMAILS` at each sign-in; View as Basic is a flag on one session (`POST /auth/view-as`), checked against the account's own type.
- **S5** `tests/test_p_auth_accounts.py` (92 tests, real middleware and real cookies): sessions, OAuth, isolation across read / write / list / import / delete, deny-by-default over every route in the OpenAPI schema, a snapshot of Basic's allow-list, every call `creator.js` makes is open to Basic.
- **S6** `cf_platform/core/gating.py` (allow-list), `require_super` on routers, `/platform/version` / echo / produce Super-only, Telegram unmounted unless `TELEGRAM_ROUTES_ENABLED`, in-memory repos refused unless `ALLOW_IN_MEMORY_STORE` (503).
- **S7** `src/static/ui/super-menu.js` (Projects, Libraries, Integrations, Defaults, Open in Studio) loaded by `creator.js` only for an effective Super session; View as Basic toggle and banner; the Basic page contains none of it.
- **S8** `cf_platform/core/limits.py` + `CAP_*` / `EST_*` settings; hooks in the storyboard / voice / render workers, scene generate, bulk generate, write-prompt, scene patch, continuity, Creator run, run settings, uploads. The owner is exempt. Spend is reserved atomically before the provider call.
- **S9** `cf_platform/core/moderation.py` (local rules + optional OpenAI), `prompt_log`, `src/static/terms.html` at `/terms`, owner routes `/platform/admin/users`, `…/disable|enable`, `…/prompt-log`; "Report a problem" via `ABUSE_CONTACT_EMAIL`.
- ENV added: see ENV.md (Google, `OWNER_EMAILS`, `SUPER_EMAILS`, `ALLOWED_EMAILS`, `SIGNUP_OPEN`, `SESSION_TTL_DAYS`, `ACCEPT_LEGACY_COOKIE`, `ALLOW_IN_MEMORY_STORE`, `ALLOWED_ORIGINS`, `TERMS_VERSION`, `ABUSE_CONTACT_EMAIL`, `TELEGRAM_ROUTES_ENABLED`, `CAP_*`, `EST_*`, `MODERATION_*`). Decisions: D119, D120. Migration 0005. No new dependency. Tests: 3293 passing (+136).
- **Files that mattered:** `src/main.py` (middleware), `cf_platform/core/accounts.py`, `cf_platform/interfaces/guards.py`, `cf_platform/core/gating.py`, `cf_platform/interfaces/dependencies.py`, `docs/SECURITY.md` ("Fixed in P-AUTH").
**Not verified:**
- The real Google round trip (consent screen, token endpoint, redirect URI) — mocked only.
- Migration 0005 and the conditional-upsert SQL on a real Postgres — mock-checked only.
- The Basic pages in a browser (the Super menu, the banner, the terms page, the Google button).
- A start-up surface: DEV needs no variable to start; sign-in is off until the Google variables are set, and the owner's password and old cookie keep working.
**Smoke test:** PARTIAL — PASSED on DEV 2026-10-14 (operator): deploy, `/health` `migrations: ok`, Google sign-in as the owner (existing data present, `account_type: super`), `ACCEPT_LEGACY_COOKIE=false` and still signed in. REMAINS: a second (Basic) Google account through the terms and the Creator, the isolation 404, the View-as toggle, a cap and a moderation refusal, logout invalidation → cleared by AUTH-S10 in Sprint P-BILL-1.
**Promoted to backlog:**
- AUTH-S10 (1 pt, Sprint P-BILL-1, first): run the friend-account smoke steps 4–9 listed in BACKLOG_ACTIVE.md; clears this entry's PARTIAL.
- Run the scoped `/audit` on DEV before P-BILL-1 (the live OAuth flow, the admin routes, the Origin rule).
- Purge expired sessions and unused OAuth states (a janitor); tenant-prefixed keys for generated assets (with P-BILL-1).
- Allow-list the image `model` string (audit medium, still open); F16, F19, CSP header, restore drill as listed in SECURITY.md.
- VERIFY (operator, DEV): the terms page, Super menu, View-as banner and Google button look right in a browser.
- VERIFY (Claude, DEV logs): that no request reaches a route without a principal (a 401 spike after the deploy would mean a route the middleware skips).

---

## [P-LITE] The Creator flow — S1 New run with characters, S2 listed characters only, S3 per-run voice, S4 the Creator pages at /create, S5 sound effects off by default
**Completed:** 2026-10-14 (built in one pass on branch `sprint/p-lite`, before P-AUTH by operator decision — D117; the design became the platform's core the same day — D118)
**Handover:**
- **S1** `GET /platform/creator/config` (the Creator's project — found by a `creator` flag in its config, created on first use as `CREATOR_PROJECT_NAME` — voices, script limit) and `POST /platform/creator/runs` (an animated run with format, language, master style and up to 6 characters written to settings.json). `VideoSettings` now carries `look`, `cast_mode` (free / single / listed), `protagonist_*`, `characters`, `voice` — this fixed a DEV defect: `POST /runs/{id}/settings` dropped them, so D113's single cast was never stored from the Studio and any save erased the look.
- **S2** `cast_mode: "listed"`: `resolve_listed_cast`, `listed_prompt_block`, `enforce_listed_cast` (`cf_platform/core/cast.py`). One listed character = D113's rule; several = an invented person is removed from bible and scenes, never swapped; project characters are not added to a listed cast.
- **S3** per-run `voice` (male / female) → `resolve_tts_voice` (`routes/workers.py`). Male is listed first and is the default; empty `CREATOR_VOICE_MALE` = `GEMINI_TTS_VOICE` (Sadachbia on DEV). Female = `Kore`, a placeholder.
- **S4** `src/static/creator.html` + `src/static/ui/creator.js` at `/create`: My videos, New video, Script (paste, word limit), Voice (one dropdown, audio track), Storyboard (cards, split / merge, chips, characters-props-settings cards and modal, pencil dialog, "Write with the director", Create assets with the estimate first), Render (captions default none, music upload, Render / Re-render, Download through a blob). Progress lines and Retry on every long action; jobs resumed on reload. Studio routes reused; `/studio` unchanged.
- **Added at the DEV smoke:** status routes (voice / storyboard / render) answer `none` for a job never started (they said `running`, so the page showed phantom generation); `GET …/video` 404s without a final.mp4 (a presigned URL was made for a missing file); `POST …/storyboard/scenes/{id}/write-prompt` + `scene_prompt_writer.py` — the Visual Director writes one scene's prompt with sections 2, 5, 6, 7 of its own prompt (D117 (9)).
- **S5** `SFX_ENABLED` (default false) — `sfx_enabled()`, `without_sfx()`; honoured by the timeline / render / CapCut routes and the render worker. Off in the Studio too (D114 (6)). The full-pipeline orchestrator path does not pass it.
- ENV added: `CREATOR_VOICE_MALE`, `CREATOR_VOICE_FEMALE`, `CREATOR_PROJECT_NAME`, `CREATOR_SCRIPT_MAX_WORDS`, `SFX_ENABLED`. Decisions: D117, D118. No migration, no new dependency. Tests: 3157 passing (+100).
- **Files that mattered:** `src/static/studio-v2.html` (the API calls the Studio makes — the reference for the Creator client), `cf_platform/interfaces/routes/studio.py` (status, video, patch routes), `cf_platform/interfaces/routes/workers.py` (storyboard / voice / render), `cf_platform/workers/animation_storyboard_worker.py` (director prompt sections), `src/models.py#VideoSettings`, `docs/mockups/studio-beta-ui.html`, `docs/UI_GUIDELINES.md` (file downloads, Creator section).
**Smoke test:** PASSED — operator on DEV 2026-10-14: new video with characters, script, voice, storyboard, split + "Write with the director", images, render with no sound effects, download, My videos shows Rendered, `/studio` still works. Three defects found and fixed during the smoke (phantom jobs, female default voice, never-rendered run read as rendered).
**Promoted to backlog:**
- LITE-S6 → AUTH-S6 (server-side gating, D118); the Super menu → AUTH-S7; P-CORE outlined (D118).
- VERIFY (operator, DEV): choose the female voice after listening and set `CREATOR_VOICE_FEMALE`.
- VERIFY (operator, DEV): a run whose listed character has a Cyrillic name (ids fall back to `character_N`).
- VERIFY (Claude, DEV logs): the cost of one "Write with the director" call.

---

## [P-HARD2] Make PROD recoverable — S1 backups runbook, S2 the audit's small fixes, S3 deploy safety
**Completed:** 2026-10-14 (built 2026-10-13 in `b6a8b6a`, base image pinned in `0caa757`; closed at the P-LITE close by operator request)
**Handover:**
- **S1** `docs/RUNBOOK.md` "Backups and restore" section — procedure only; F1 stays open until a restore drill is recorded.
- **S2** start-up validators (`OPERATOR_PASSWORD` / `SESSION_SECRET_KEY` at least `AUTH_SECRET_MIN_LENGTH` = 12; prod refuses to start without `SETTINGS_ENCRYPTION_KEY`), `run_id` pattern (`_run_id.py`), Secure cookie, proxy-aware lockout, legacy routes off unless `LEGACY_ROUTES_ENABLED`, capped uploads (F7, F9, F18, F14, F3, F10, F12). D116.
- **S3** migration advisory lock and status in `/platform/health`, a PROD post-deploy check in `cd.yml`, `pip-audit` warn-only in CI, non-root container on a pinned base image (F11, F20).
- **Found at the P-LITE push:** DEV crashed on start because its `OPERATOR_PASSWORD` was 6 characters (the S2 validator, as D116 warned). The operator set a longer one on 2026-10-14; DEV has run since.
**Smoke test:** PASSED — cleared by the operator at the 2026-10-14 sprint review ("closed"); no per-step detail was recorded. The restore drill (F1) is a separate open item in `docs/RUNBOOK.md`.
**Promoted to backlog:** none. AUTH-S0 is now the `PROD_URL` check.

---

## [P-HARD1] Audit and hardening — S1 first SECURITY.md, S2 loud voice failure, S3 word-matching suite, S4 bulk-job guard, S5 cost-log backfill
**Completed:** 2026-10-13 (built in one pass on branch `sprint/p-hard1`; **not pushed** — the operator was copying DEV to PROD in another session, and a push to `main` redeploys DEV)
**Handover:**
- **S1** `docs/SECURITY.md`: 23 findings with `file:line`, an accepted-risk register and what the audit could not see (dashboards). Fixed inline: log redaction of presigned-URL signatures and the Telegram bot token (F15), constant-time webhook secret compare (F17), `max_iterations` bounded 1–5 (F4 part). **D115** records the moderation stance (minimal, implemented in P-LITE); settled by Claude, for the operator to confirm. Highest open items: F1 no backup / restore drill, F3 legacy routes, F5 key fallback, F2 tenant scoping (P-AUTH). The audit was run by a subagent; its claims about code were spot-checked, not all re-verified.
- **S2** `voice_production` now raises `VoiceGenerationError` when `GEMINI_API_KEY` / `GEMINI_TTS_VOICE` is missing, the TTS call fails or the audio cannot be stored; the message is readable and secret-free (`key=` redacted). The job document says `error` with the reason, `/voice/status` returns it, and the Voice button reads "Retry voiceover". Only Deepgram alignment still degrades (audio exists). Tests: worker, job, status.
- **S3** `tests/cf_platform/test_hard1_word_matching.py`: corpus of transcript / script pairs through `canonical_units`, `align_text` and `edits_from_text`. The suite found and fixed: years said as two pairs ("twenty twenty four" read as 44, "nineteen ninety nine" as 118), hyphenated numbers ("sixty-five" and the editor's stripped "sixtyfive"), "one million two hundred thousand" split in three. Pinned gaps: ordinals ("twenty first" vs "21st"), "one twenty" (read as 21, not 120).
- **S4** split, merge and `PUT …/storyboard/boundaries` answer 409 while a bulk image job runs for the run (a preview with `dry_run` is allowed). The server message reaches the operator through the existing error line.
- **S5** `.apex/cost-log.jsonl`: P-PROJ1 and P-INT1 entries backfilled from commit times (flagged `backfilled`, estimates; session ids unknown). P-UX4 already had one. This sprint has its own range entry.
- Tests: 3000 passing (+70). No migration, no new dependency, no ENV change.
**Not verified:** nothing ran on DEV (not pushed). The "real DEV pastes" for S3 were the pastes recorded in earlier handovers plus constructed forms — if DEV shows another way a number is written, add it to `CORPUS`. The Retry label was checked by reading the code, not in a browser.
**Smoke test:** PASSED — the operator ran the four DEV steps (voice failure with Retry, number paste in the script view, bulk-job guard, SECURITY.md) and reported "done" on 2026-10-13; no per-step detail was recorded. Cleared as HARD1-S6.
**Promoted to backlog:**
- HARD2-S1..S3 (see BACKLOG_ACTIVE.md): backups and restore drill, small audit fixes, deploy safety.
- VERIFY (operator, on DEV): a number written another way than the corpus covers (ordinals "21st", "one twenty") in the script view; the Retry button in a browser.

---

## [P-INT1] Integrations v2 — S1 five blocks, S2 provider registry + LLM adapter, S3 default and model per provider, S4 what a run was made with
**Completed:** 2026-10-11 (built in one pass; settled by Claude while the operator was away — D112)
**Handover:**
- **Five blocks** (`cf_platform/core/providers.py`): Thinking models, Audio models (default per role: voice / transcription), Image generation, Stock acquisition, Destination. `GET /platform/tenant/blocks` gives each provider's key state (hint only), default, model, suggested models and how far it is wired (`full` / `partial` / `planned`); `PUT /platform/tenant/blocks/{block}` takes `default` and/or `model: {provider, model}`. Choices are stored in `tenant_settings.defaults["blocks"]`; the image block's choice is the P14 `image_provider` / `image_model`.
- **Settings → Integrations** is regrouped by block: per provider a key (the existing `PUT /tenant/integrations/{service}`), a Make default button and a model field.
- **LLM adapter** (`cf_platform/core/llm.py`): `LLMClient.complete`, `AnthropicLLM`, `OpenAILLM`, `build_llm_client`. **The YouTube metadata worker is the only one on it** — with OpenAI as the Thinking models default, `POST /platform/workers/metadata` answers from OpenAI (the artifact's lineage records the model); without a key it is a readable 409. Every other worker still calls Claude directly (D112).
- **Run details** shows "Made with" (model per artifact, from lineage) and "Defaults for the next step" (`GET /platform/studio/runs/{id}/providers`).
- ENV added: `OPENAI_LLM_MODEL` (default `gpt-4.1-mini`). No migration, no new dependency. Decision: **D112**. Tests: 2907 passing.
- **Not verified:** nothing ran against a real OpenAI account or DEV. The OpenAI request shape (`max_completion_tokens`, chat completions) is exercised against a mock transport only; the default model id `gpt-4.1-mini` is an assumption — check it exists on the account, or set `OPENAI_LLM_MODEL`. The regrouped Integrations page was syntax-checked and covered by page tests, not looked at in a browser.
- **Not built (by design, D112):** script, storyboard and the other text workers on the adapter; per-user keys and the automatic default switch (P-AUTH); alternative audio providers.
**Smoke test:** PASSED — on DEV 2026-10-13 the five blocks, key state and Make default; the operator marked the remaining OpenAI default / metadata item done at the 2026-10-13 review (named by them). Not independently observed in this log; re-check it when the Integrations rework (INT2-S1, candidate, unscheduled) is planned.
**Promoted to backlog:** INT1-S6 candidate: move script, storyboard and fact-check workers onto `LLMClient` (or an equivalent that keeps thinking and streaming), one at a time with a prompt check; per-block fallback order for providers; key validity check on save.

---

## [P-INT1 / P-PROJ1 close fix] The test suite no longer depends on a developer's `.env.local`
**Completed:** 2026-10-13
**Handover:**
- CI failed on three new route tests that built the app with no settings overrides (they passed locally from `.env.local`; CI lacks `OPERATOR_PASSWORD` and `SESSION_SECRET_KEY`). The three were fixed, and `tests/conftest.py` now fills any missing required setting for every test (`hermetic_settings_env`). The full suite (2930) passes with `.env.local` moved away and an empty environment. See `docs/TESTING.md#hermetic-settings-2026-10-13`.
**Smoke test:** PASSED — full suite run with no `.env.local` and `env -i`.

---

## [P-PROJ1 follow-up] One character throughout a run; master visual prompt at project and run level (D113)
**Completed:** 2026-10-13 (operator question after the P-PROJ1 smoke)
**Handover:**
- **Run settings → Cast** (AI-generated runs): "The director decides" or "One character throughout" with a project character or a typed description. Stored as `cast_mode`, `protagonist_asset_id`, `protagonist_text` in settings.json. `cf_platform/core/cast.py`: `resolve_cast`, `prompt_block`, `enforce_single_cast`; wired in `generate_animation_storyboard` and the storyboard route. Other character entries are dropped and their scenes show the protagonist; regenerating keeps the rule.
- **Master visual prompt:** it already existed at both levels (project: `ai_image_style`, run: `master_style`, the run wins). The project field is now named "Master visual prompt (project default)", says the run's wins, and the New Run modal notes when the project's will be used.
- Tests: 2930 passing.
**Not verified:** against a real model — the enforcement is deterministic and tested, but how well the image model keeps one face across scenes depends on the description. Not applied to Realistic (stock) runs.
**Smoke test:** PASSED — the operator set Cast to "One character throughout" with the project character on DEV (2026-10-13) and the storyboard came back with one character entry used by the scenes with a person.

---

## [P-PROJ1 / P-UX4 post-close fixes] Scene boundaries tolerate spelled numbers and punctuation; compact animation scene cards
**Completed:** 2026-10-11 (operator feedback on DEV)
**Handover:**
- **Script view / `PUT …/storyboard/boundaries`:** the voiceover's words come from Deepgram (`smart_format`: "$109 million", "60%", no punctuation), so script text pasted into the view never matched ("The words differ"). `align_text_to_words` (`storyboard_edit.py`) now compares words ignoring case, punctuation, currency/percent marks and spelled-out numbers ("one hundred nine million dollars" = "$109 million", "two thousand eight" = "2008", "one point seven" = "1.7") and maps paragraph breaks through the matched units; a real wording change is still a 422. The response carries `matched_by_position`. Not handled: years said as two pairs ("twenty twenty four") — they read as "20 24" and are refused.
- **Animation scene card:** the prompt, concept, shot and keywords sit in one collapsed "Image prompt" section (open by itself only when a scene has no prompt; the choice survives a redraw); Merge shares the tools row; the repeated "ai_generated" badge is gone. A card drops from about 290 px to about 120 px.
- **Second round (same day):** the same paste also failed in the **Script step's transcript editor** (uploaded voiceover) — its own matcher read "dollars" as an added word. Both editors now share `cf_platform/core/word_match.py` (`canonical_units`, `unit_spans`): "percent" / "dollars" / "cents" are dropped only straight after a number, so a stray "dollars" is still a real word. Text that says the same as the transcript answers "nothing to change" instead of an error; a real correction beside differently written numbers still comes through as an edit.
- **Third round:** the storyboard Script tab still said "differs by more than paragraph breaks" on DEV data I could not see. Since boundaries never change words, `align_text` (`storyboard_edit.py`) now accepts text that reads differently in a few places (≥60% of words line up), uses only its paragraph breaks and reports the differing stretches in the confirm summary and in `differences`; text that is mostly different is refused and the message lists the first differences. This replaces the strict "one changed word is refused" rule for the script view only — the transcript editor, which does change words, keeps its timing-safe rules.
- Tests: 2919 passing.
**Not verified:** against real DEV storyboard data (the number matcher was exercised on the operator's pasted paragraph with a constructed transcript). If the DEV transcript writes a number in a form not covered (say "F one" for F1, or a year said as two pairs), the editor will still refuse it and say which words it could not map.

---

## [P-PROJ1] Visual source model and project-level settings — S1 look + image source, S2 channel identity, S3 project assets, S4 storyboard reuses assets, S5 prompt v0.18
**Completed:** 2026-10-11 (built in one pass; operator asked for P-PROJ1 and P-INT1 back to back with no questions, so the open design points were settled by Claude — see D111)
**Handover:**
- **Look and image source are two settings (D111).** `settings.look` (realistic / animated, null until chosen) and `settings.visual_mode` (the image source, unchanged name). `GET/PUT /platform/studio/runs/{id}/visuals` (`routes/studio_visuals.py`) own the change: with a storyboard it answers 409 `needs_confirmation`, and `confirm_reset` discards the storyboard and acquired assets (same mechanism as a voiceover re-upload, now public as `discard_storyboard` in `studio_voice.py`). Run settings show Look and Image source; the New Run modal sets both from its Style. Look is the master-style fallback for AI images and, on stock, an "animation illustration" hint on non-person queries (`apply_look_hint`).
- **Channel identity** — `project.config.channel_identity` (≤2000 chars), edited in Project settings; `POST /platform/workers/metadata` passes it and the project niche to the metadata worker.
- **Project assets** — `cf_platform/core/project_assets.py`; `config.assets`; routes `GET/POST /platform/projects/{id}/assets`, `PATCH/DELETE …/assets/{asset_id}`, `POST …/assets/from-run` (copy a run's bible entry). Project settings has the list; a bible entry has "Save to project". The project config PATCH cannot change assets.
- **The animation worker reuses assets** — they go in the user message (`PROJECT ASSETS`), and any continuity entry with an asset's id is overwritten with the saved name, kind and description and marked `project_asset_id` (`apply_to_continuity`). Relation is a copy, not a link.
- **Prompt v0.18** (`_METHOD_V018`, Sonnet 5.5, adaptive thinking, streamed) is built and selected by `STORYBOARD_STOCK_PROMPT_VERSION`; **v0.17 stays the default**. The registration's lineage records v0.18 when it is used.
- ENV added: `STORYBOARD_STOCK_PROMPT_VERSION` (default `v0.17`). No migration, no new dependency. Decision: **D111**. Tests: 2890 passing.
- **Not verified:** nothing here ran against a real model or DEV. The v0.18 side-by-side test (v0.17 vs v0.18 on one real script) was NOT run — it needs real API calls and the operator's judgement — so the default did not switch. Whether the model really reuses an asset by id (the code enforces the text once it does) is only checked with a mocked answer. The "animated look on stock" search hint is a heuristic and has not been looked at against real footage results. The lock/reset dialogs and the Project assets page were checked by tests and a syntax check, not in a browser against DEV.
**Smoke test:** PASSED — the operator walked the INT1-S5 sweep on DEV (2026-10-13): channel identity and a project character, a new Animated run, Look and Image source as two settings, the lock dialog naming what it discards (Cancel changes nothing), the storyboard with one character entry used by the scenes with a person and tagged "Project asset", compact scene cards, Generate all images with the cost shown first, and a render. **Not done:** the v0.17 vs v0.18 storyboard side-by-side — an operator decision, not a smoke item; `STORYBOARD_STOCK_PROMPT_VERSION` stays `v0.17`.
**Promoted to backlog:** PROJ1-S6 candidate: run the v0.17 vs v0.18 side-by-side on one real script and switch the default; a way to attach a project asset to an existing run's bible; a character reference image (deferred in D108).

---

## [P-UX4] Pipeline flow and polish — S1 shell polish, S2 minimal New Run modal, S3 Script step, S4 Voiceover step, S5 Storyboard step, S6 Video step, S7 library names
**Completed:** 2026-10-11 (built in one pass, commit `a7da166`, CI on `main`)
**Handover:**
- **Every step starts its own work and ends with Next.** Script: Generate-from-idea first and collapsed (hidden in Paste), Next. Voiceover: pace and tone live here (moved out of Run settings), *Generate / Regenerate voiceover*, *Skip voiceover*, Next. Storyboard: its own *Generate storyboard* button with a note pointing to Run settings and a warning that the style is locked afterwards; a stock run with acquired assets asks before regenerating. Video: caption toggle and style on top, Next to Metadata. Upload flow: Next goes to the Voiceover step; "Review transcript" stays as a second button.
- **An uploaded voiceover is a replaceable asset (D109 point 2).** `POST /platform/workers/voice` no longer answers 409 for an uploaded run; it answers 409 `needs_confirmation` with what would be discarded, and with `confirm_discard: true` it flips `voice_source` to `generated` and discards the storyboard (`discard_for_generated_voice` in `studio_voice.py`, shared with `PUT …/voice-source`). The old bug (Voice step "Needs attention") is gone because the script artifact marked `uploaded_vo` is superseded by the script written at generation.
- **One setting, two places:** captions toggle and style are mirrored between the Video step and Run settings (`syncCaptionStyleEnabled`).
- **New Run modal:** Title, Language, Format, Style (Realistic / Animated) and, for Animated, an "Add master visual prompt" sub-modal; the style rides to Studio in `sessionStorage` (`cf_new_run_style`) and is saved with the run's first settings. The brief field is gone (combined ideas still pass their summaries).
- **Shell:** burger and phone drawer removed (a narrow screen keeps the 56 px rail); the panel's folded state is remembered across pages and runs; sidebar-panel icon; `.select` has a chevron with room; no divider above step buttons; storyboard uses the standard content width; Merge-with-next sits bottom right with a narrower search-words field.
- **Library:** videos and voiceovers are named after the run title (`titled_name`, `name_from_run` in `core/library.py`); display and download names; footage and AI images are unchanged.
- No ENV vars, migration or dependency. Tests: 2869 passing, ruff clean.
- **Not verified:** the New Run modal and the voiceover-replace confirmation were checked by tests and in the static demo only, not against DEV; the phone layout without a drawer was not looked at; the master-prompt sub-modal on a real run.
**Smoke test:** PASSED — the operator walked the INT1-S5 sweep on DEV (2026-10-13): the minimal New Run modal with the master-prompt sub-modal, the format selector, shared captions between the Video step and Run settings, the phone-width rail without a burger, library file names after the run title, and generating a voice over an uploaded mp3 (it asks before replacing). Earlier fixes (voiceover spacing, compact scene cards, storyboard width, script view) were confirmed as they shipped.
**Promoted to backlog:** none. Candidates: the style lock is still the existing one (disabled buttons after a storyboard); the explicit "reset storyboard" arrives with P-PROJ1.

---

## [P-AN1] Animation mode — S1 visual mode + master style, S2 animation storyboard worker + continuity bible, S3 image prompt assembled in code, S4 scene cards + editable bible, S5 generate all images, S6 Nano Banana + smoke test
**Completed:** 2026-10-11 (built in one pass, commit `5bfa361`; smoke fix `19f0c2f`)
**Handover:**
- **A run has a visual mode** (`settings.json`: `visual_mode` `stock` | `ai_animation`, `master_style`, `image_spend_cap_usd`). The master style falls back to the project's `ai_image_style`. `cf_platform/core/run_visuals.py` resolves all of it; `POST /runs/{id}/settings` now merges instead of overwriting.
- **A second storyboard worker** (`cf_platform/workers/animation_storyboard_worker.py`, prompt `an-v0.1`, `claude-sonnet-5-5`, one call, no review pass) is chosen by the storyboard endpoint from the run's mode. It emits the same `verified_storyboard` artifact with `visual_mode`, a `continuity` list and, per scene, `visual_concept`, `visual_keywords`, `shot`, `entities`, `motion_note`, `flags` and a scene-only `ai_prompt`. Scenes over 5 s are flagged, not split. Downstream code reads the mode from the storyboard, not from the settings.
- **The image prompt is assembled in code** (`build_animation_prompt` in `core/ai_images.py`): scene prompt → bible descriptions → fixed lines → master style → aspect phrase. `POST …/scenes/{n}/prompt-preview` shows the exact text.
- **One place pays for an image:** `generate_scene_image` in `cf_platform/workers/scene_images.py`; the per-scene route and the bulk job wrap it. Bulk job: `GET …/images/plan`, `POST …/images/generate`, `GET …/images/status`; retries once, stops at the cap, stops after three identical failures, survives a restart without paying twice.
- **Continuity bible edits:** `workers/continuity_edit.py` and `routes/studio_animation.py`; an edit flags the scenes whose image is now out of date. Split and merge follow D102 with the animation rules (a cut scene has no prompt and is flagged).
- **Image model:** kie.ai `nano-banana-2-1` works through the unchanged provider at $0.02 per 1K image. Cost is per model (`IMAGE_MODEL_COSTS_USD`); a model saved for the wrong provider is refused and ignored.
- **ENV vars added:** `IMAGE_MODEL_COSTS_USD`, `IMAGE_RUN_SPEND_CAP_MAX_USD`, `IMAGE_JOB_CONCURRENCY` (all with defaults; none set on Railway). No migration, no new dependency. Decision: **D108** (amends D104). Tests: 118 new in six files; 2856 passing, CI green on `19f0c2f`.
- **Not verified on DEV:** the stop at the spend cap and the cap raise; restart recovery of a bulk job; "Regenerate those…" after a bible edit; the model refusal and provider-switch behaviour in Settings after the fix; the cost of one storyboard on Sonnet 5.5. Shot variety is not checked in code. A split or merge during a bulk job is not guarded. The estimate for `gpt-image-1` rests on one run.
**Smoke test:** PASSED — the operator made a 9:16 run (47 s, 14 scenes, with background music and on-screen text) and a 16:9 run on DEV, each from script to rendered video in Animation mode, the second on Nano Banana 2.1 via kie.ai. One defect found and fixed during the smoke (`19f0c2f`: kie.ai's model id was sent to OpenAI). The operator reports consistency as "worked", with no detail and no bible entry reported as tightened.
**Promoted to backlog:** none. Candidates: a guard on split / merge while images are generating; a per-run or per-project image resolution (today `IMAGE_RESOLUTION` is one Railway variable; 1K is below the 1080p frame); a shot-variety check in code; reference images for characters (deferred in D108).

---

## [P-UX3] UI/UX redesign — S1 audit, S2 information architecture, S3 prototype, S4 decision (and the build, folded in)
**Completed:** 2026-10-11 (designed 2026-10-07, built 2026-10-08 in `83e333c` / `2e0bd93`, renderer fixes `58f361e` and `a199b76` after the smoke test)
**Handover:**
- **One shell on every page** (`src/static/ui/shell.js`, `shell.css`, `app.js`, `app.css`): foldable left panel (Projects; the open project's Overview / Ideas / Runs / Settings; Libraries; Settings), breadcrumbs on the page background, phone drawer. A run starts folded. Project pages are `/project?id=&tab=overview|ideas|runs|settings`; `/library?kind=`; `/settings?tab=integrations|defaults`. The prototype stays at `/prototype/`.
- **A run starts from one or several ideas or from a title alone** (`POST /platform/projects/{id}/runs`, `item_ids` optional, `title`, `brief`, `aspect_ratio`); ideas are editable (`PATCH …/shortlist/{item_id}`). Run rows carry voice source, language, format, derived progress (`cf_platform/core/run_progress.py`).
- **One five-step pipeline per run** (Script → Voice → Storyboard → Video → Metadata): the Script step chooses generate / paste / from a voiceover; `PUT /platform/studio/runs/{id}/voice-source` answers 409 `needs_confirmation` before an uploaded recording is replaced (the storyboard is discarded through the P14b marker). Run settings are a drawer. Storyboard scenes are cards: on-screen text inline, SFX, motion, split on a word, merge, pencil on the asset.
- **Tenant Integrations and Defaults** (`cf_platform/core/integrations.py`, migration `0004_tenant_defaults.sql`): a key saved in Settings wins over the Railway variable and reaches every route through `get_effective_platform_settings`; defaults for language, format, captions and the AI-image cap, inherited tenant → project → run (a run copies at creation).
- **Libraries** (`cf_platform/core/library.py`, `GET /platform/library/{kind}`): videos, audio, footage, AI generations, music & SFX, read from the run folders — nothing is indexed; asset ID = prefix + 6 hex of the key's hash; download through a blob.
- **Renderer (D107):** pans are drawn at 4× (quarter-pixel steps) and always have 10 % of the frame width to travel, in the FFmpeg render and the CapCut export; ken burns / zoom in / zoom out are enlarged 4× before `zoompan` so they no longer tremble. Pan scenes cost about twice, zoom scenes about four times the CPU of before, and about 200 MB per scene.
- **ENV vars added:** none. Migration `0004`. No new dependency. Decisions: **D105, D107**. Tests: 2738 passing, CI green on `a199b76`.
- **Not built (D105):** library "use in a scene", music chosen from the library, per-service default models, Research / Publishing panel entries, saved keys for Freesound / ElevenLabs / Replicate.
- **Not verified:** the operator has not re-rendered since the zoom fix (`a199b76`) — the shake was measured fixed on the operator's own images, not seen by them; saved keys were covered by unit tests, and the Integrations step of the smoke list was closed by the operator without notes — a full acquisition run with a saved key was not observed; which pages still feel crowded was never named.
**Smoke test:** PASSED — the operator walked the ten-step list on DEV on 2026-10-10 (one real 16:9 run, five scenes with their own uploads) and found two renderer defects, both fixed (D107); the remaining items were closed by them. The zoom fix is the one thing not re-checked by the operator.
**Promoted to backlog:** none. Candidates: a pan that is clearly visible on every still without a minimum zoom (decided against); "which pages feel crowded" when the operator next names them.

---

---
