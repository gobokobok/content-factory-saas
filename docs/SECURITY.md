# Security posture

First audit: **2026-10-13** (P-HARD1-S1, run with `/audit` on branch `sprint/p-hard1`). Read-only review of the
code and docs; **nothing was checked in the Railway, Cloudflare or Postgres dashboards** — every "unverified" below
needs the operator to look there. Next audit: at P-AUTH close (it touches auth, tenants and personal data), and no later
than 60 days from the date above.

Context: today the system has **one operator and one shared identity**. The friends beta (D114) adds strangers' text,
per-user provider keys and prepaid credits. Findings are ranked for *that* moment, not for today.

## Verdict

Reasonable for a single operator: tenant provider keys are Fernet-encrypted and only a hint is ever returned; uploads
derive their extension from a MIME whitelist; ffmpeg runs from an argument list and script text is quoted; the git
history (555 commits) holds no keys. **Do not let strangers in until F1–F5 are closed or consciously accepted.**

## Findings

| ID | Severity | Finding | Evidence | Status | Fix |
|----|----------|---------|----------|--------|-----|
| F1 | High | No documented Postgres or R2 backup, and no restore drill. D025's R2 versioning is an operator action nobody verified; R2's object versioning support itself needs a dashboard check | DECISIONS.md D025; nothing in docs/ | **procedure written** (RUNBOOK, 2026-10-13); closes when a drill is recorded; R2 versioning unverified | Story **HARD2-S1**: enable Railway Postgres backups, verify R2, write the RUNBOOK section, run one restore onto a scratch database |
| F2 | High | One shared identity: `PLATFORM_USER_ID="operator"` (75 uses); run repos have no user filter; run content is keyed `runs/{run_id}/…` with no tenant prefix | `cf_platform/interfaces/dependencies.py:68`, `core/postgres_repos.py:122,133`, `routes/studio.py` | **fixed in P-AUTH** (see below; unverified on DEV) | P-AUTH must scope everything by tenant (R2 prefix, repos, a central run-ownership dependency) |
| F3 | High | Legacy routes list, read and delete every run in the bucket; legacy ids are guessable `{date}_{slug}`; the legacy UI is served at `/legacy` | `src/routes/runs.py:70,80-92,257-273`, `src/main.py:197` | **fixed** 2026-10-13 (D116): `/legacy` and the legacy run routes mount only with `LEGACY_ROUTES_ENABLED=true`; Studio's delete and run-settings routes remain | Unmount `/legacy` and the `src/routes/runs.py` router, or admin-gate them, **before P-AUTH ships** |
| F4 | High | `max_iterations` taken from the client with no bound (paid LLM calls); script and niche fields have no length cap | `routes/blocks.py:139`, `routes/workers.py:76,402` | **max_iterations fixed** (bounded 1–5, this sprint); length caps open | Server-side script length cap (word count tied to the video length) — decided in D115 |
| F5 | High (at beta) | A tenant key that cannot be decrypted falls back to the operator's Railway key, so one stranger's broken key spends the operator's account | `core/integrations.py:111-113` | open | At P-AUTH: for non-operator tenants fail the call with a readable error instead of falling back |
| F6 | Medium | Session cookie is a constant HMAC, valid one year, no user id, no expiry, no revocation | `src/auth.py:61-67`, `src/routes/auth.py:12` | accepted for one operator | Replaced by real sessions in P-AUTH |
| F7 | Medium | `OPERATOR_PASSWORD` / `SESSION_SECRET_KEY` accept empty or weak values; `SETTINGS_ENCRYPTION_KEY` defaults to empty with only a UI warning | `src/config.py:102-103`, `core/config.py:77` | **fixed** 2026-10-13: start-up refuses short / empty secrets and a prod start without the key (`check_deployment_settings`); active on DEV now, on PROD at release | Validators: non-empty, min length; refuse to start on `ENVIRONMENT=prod` without the encryption key. Not applied inline: a start-up check can take PROD down while it is being copied from DEV — do it with a release |
| F8 | Medium | Spend caps are per run only (image); no per-tenant or daily cap; LLM and TTS uncapped; no per-user rate limit | `core/config.py:112-114` | open | P-BILL-1 credit ledger; an interim daily cap if the beta opens first |
| F9 | Medium | `run_id` is not validated in worker request bodies and reaches a local `/tmp/{run_id}` path in the render | `routes/workers.py:76,402,673`, `src/ffmpeg_builder.py:985-989`, `workers/render_worker.py:849` | **fixed** 2026-10-13: worker request bodies and `idea-to-script` constrain `run_id` to `^[A-Za-z0-9_-]{1,128}$` | Constrain `run_id` to the uuid / legacy-id pattern in the request models |
| F10 | Medium | Legacy presigned PUT takes an arbitrary filename with no size or type bound | `src/routes/runs.py:102`, `src/models.py:647` | **fixed** 2026-10-13 with F3 (route unmounted by default) | Goes away with F3 |
| F11 | Medium | A failed migration is swallowed: the app starts on the old schema, `/platform/health` shows only DB reachability, no lock between instances | `core/migrations.py:73-75`, `src/main.py:73-85` | **fixed** 2026-10-13: advisory lock, `/health` and `/platform/health` report migration status, PROD deploy workflow checks it (needs the `PROD_URL` repository variable) | Report migration status in health; advisory lock; a CD post-deploy check |
| F12 | Medium | Scene and music uploads read the whole file before the size check (200 MB / 50 MB) | `routes/studio.py:1250,1373` | **fixed** 2026-10-13: scene and music uploads read in 1 MB chunks and stop at the limit | Stream with early abort as the MP4 upload already does (`studio.py:445`) |
| F13 | Medium | No moderation, terms or abuse process for strangers' text and generated images | no code | **decided in D115** (minimal stance) | Implement in P-LITE / P-AUTH |
| F14 | Medium | Login lockout keys on the proxy's IP; any stranger can lock the operator out with 5 bad tries | `src/routes/auth.py:39` | **fixed** 2026-10-13: lockout keys on the right-most `X-Forwarded-For` entry (`TRUST_PROXY_HEADERS`) | `--proxy-headers` / trusted forwarded IP in `entrypoint.sh`; gone with P-AUTH |
| F15 | Low | R2 presigned-URL signature parameters and the Telegram bot token were not covered by log redaction | `src/log_redaction.py` | **fixed this sprint** | — |
| F16 | Low | One Fernet key, no rotation (`ENV.md`: "never change it") | `core/secret_box.py:19` | open | `MultiFernet` with a key id per stored key; needed before the first rotation |
| F17 | Low | Telegram webhook secret compared with `!=`; an empty allow-list means every chat is allowed; the route is dormant (D093) but can start paid jobs | `routes/telegram_webhook.py:478`, `interfaces/telegram.py:526` | **compare fixed this sprint**; allow-list open | Unmount the route while D093 stands |
| F18 | Low | Session cookie is not `Secure` outside `prod` (DEV is https) | `src/routes/auth.py:60` | **fixed** 2026-10-13: cookie is `Secure` unless `COOKIE_ALLOW_INSECURE=true` | `secure=True` for every non-local environment |
| F19 | Low | Uploads trust the client MIME; no magic-byte or `ffprobe` check before ffmpeg | `routes/studio.py:1246`, `workers/voice_upload.py:74` | open | `ffprobe` validation on upload |
| F20 | Low | No lockfile or hashes; no dependency scanner in CI; container runs as root; unpinned `python:3.11-slim`; `sentence-transformers` installed while `CLIP_RERANK_ENABLED` is off | `requirements.txt`, `Dockerfile`, `.github/workflows/ci.yml` | **part fixed** 2026-10-13: non-root user, base image pinned by digest, `pip-audit` in CI (warn-only); lockfile open | `pip-audit` in CI, lockfile, `USER app`, pinned base |
| F21 | Info | No SSRF vector: fetched URLs come from provider responses, no endpoint takes a user URL | `core/image_provider.py:148`, `workers/acquisition_worker.py:448` | verified | Re-check when P-AUTH or P16 adds a user-supplied URL or webhook field |
| F22 | Info | No secrets in the repo or its history (scan of 555 commits for `sk-`, `sk-ant-`, `AKIA`, `AIza`, private keys, `key=<24+>`) | git history | verified | The Pixabay key in DEV logs is a log leak, already tracked in CLAUDE.md |
| F23 | Info | No shell injection in ffmpeg script building: argument list, `shlex.quote`, `expansion=none` text files | `workers/render_worker.py:413-429`, `src/ffmpeg_builder.py:837-846` | verified | — |

## Fixed in this audit (P-HARD1-S1)

- **F15** log redaction now covers `X-Amz-Signature` / `X-Amz-Credential` / `X-Amz-Security-Token` and `/bot<id>:<token>`
  (`src/log_redaction.py`, tests in `tests/test_log_redaction.py`).
- **F17** webhook secret compared with `hmac.compare_digest`.
- **F4 (part)** `max_iterations` bounded 1–5 on `POST /platform/blocks/idea-to-script`.

Deliberately **not** fixed inline: F5, F7, F9, F18 change behaviour that PROD depends on while a DEV → PROD copy is under
way, and F3 / F10 / F14 are decided together with P-AUTH. Each is a one-sitting change once the release is out.

## Fixed in P-HARD2 (2026-10-13)

F3, F7, F9, F10, F11, F12, F14, F18 and the non-root / pinned-image / `pip-audit` part of F20; F1 has a written procedure and
no drill yet. Decision D116. Tests: `tests/test_hard2_hardening.py`. Caveats:

- **F3 / F10:** the unmounting is by default, not removal. Studio still calls `DELETE /runs/{id}` and `GET`/`POST
  /runs/{id}/settings` in the legacy module, and those stay unscoped (F2) until P-AUTH moves them to the platform.
- **F14:** trusting `X-Forwarded-For` is right only behind Railway's proxy; a direct connection could spoof it, which
  would only let a caller dodge their own lockout.
- **F20:** `pip-audit` has not produced a report yet; it is non-blocking until the first one is triaged.

## Accepted-risk register

| Risk | Condition that makes it acceptable | Re-check when |
|------|------------------------------------|---------------|
| Shared identity and unscoped runs (F2) | One operator, no strangers | P-AUTH starts |
| Constant session cookie (F6) | Same | P-AUTH starts |
| Fallback to the operator's key on a broken tenant key (F5) | The tenant *is* the operator | A second user can save a key |
| Telegram webhook reachable (F17) | Dormant, secret set or route rejects with 401 | Telegram is revived (D093) |
| PROD behind DEV (CLAUDE.md) | Operator's call (D-policy) | Release |

## What the audit could not see

Railway backup settings, whether R2 versioning is on, which variables PROD actually has set (Telegram, encryption key),
Cloudflare access rules. These are the first things to check in the dashboards.

---

## Audit — 2026-10-14 (scoped: P-AUTH readiness and the P-LITE surface)
**Scope:** the Creator routes and page (`/create`, `creator.py`, `creator.js`, `write-prompt`, `cast.py`), and the design the P-AUTH multi-user work builds on (F2, F5, F6, F8, F13 re-checked against current code). One read-only subagent; nothing was exercised live. Spot-checked by the reviewer: no moderation code exists, `PLATFORM_USER_ID` has 87 uses, the final-video route returns a 24-hour presigned URL by id. Not read in full: `studio_voice.py`, upload bodies, acquisition and render workers, `studio-v2.html`. F1, F9, F11, F12, F14, F18, F20 were not re-verified.
**Findings:** 3 critical, 5 high, 6 medium, 5 low (all would hold only once a second user exists; with one operator they are the same accepted risks as F2 / F6).
- **Critical:** (1) run-scoped routes have no ownership check — F2 updated: video, render, settings, delete, spend, uploads and the worker routes act on any `run_id`; `DELETE /runs/{id}` and the run settings routes are mounted even with legacy off. (2) constant session cookie, one year, no user id — F6. (3) operator-key fallback on a failed or missing tenant key — F5.
- **High:** (4) no server bound on paid work — script words, prompts and master style are capped only by the page; runs are free and unlimited (F8, F4); (5) no moderation in code (F13, D115 unbuilt); (6) repos have no tenant clause (`get`, `list_runs`, `count_by_project`); (7) the library lists every run of every tenant and signs links; (8) `/studio`, `/project`, `/library`, `/settings` and the old routes are ungated until tier gating exists.
- **Medium:** tenant settings share one row; the image `model` string is not allow-listed; prompt injection into the director (output parsed, no tools, blast radius is the user's own output and cost); CSRF and OAuth constraints (no Origin check, login-CSRF, `redirect_uri` must be config not `Host`, no `--proxy-headers`); in-memory login limiter; `run_id` path params not pattern-checked; writes to arbitrary `runs/{any}/` folders and no per-tenant storage quota.
- **Low:** no CSP / `X-Frame-Options`; Telegram webhook mounted with an empty allow-list meaning every chat (F17); `/platform/version` and `/platform/health` readable by any signed-in user; in-memory repo fallback if `DATABASE_URL` is empty; F16 (one Fernet key) matters more with many tenants. No XSS found in `creator.js` (`esc()` on user text; the rest of the file and `studio-v2.html` not read line by line).
**Stories opened (approved by the operator 2026-10-14):** AUTH-S1 gains the OAuth constraints; AUTH-S3 gains `require_run` / `require_project` and tenant-scoped repos; AUTH-S6 becomes `require_super`; new AUTH-S8 (server caps, per-tenant spend, runs per day) and AUTH-S9 (moderation gate and acceptance row, D115). In SPRINT.md and BACKLOG_ACTIVE.md.
**Accepted risks re-confirmed:** PROD behind DEV (operator's call; holds only while PROD stays single-user); legacy routes off (holds on code, but see finding 1).
**Accepted risks now expired:** F2 shared identity, F6 constant cookie, F5 operator-key fallback, D117 "Creator is simpler, not restricted" — each expires the moment a second account can sign in. Telegram (F17): holds only if PROD has a webhook secret, unverified.
**Ordering rule from this audit:** do not open Google sign-in before the `current_user` dependency, tenant-scoped repos with `require_run`, and `require_super` are merged — until then a second account is a full operator.
**Next audit due:** at the P-AUTH close, before P-BILL-1 (money) ships.


## Fixed in P-AUTH (2026-10-14, built on `sprint/p-auth`; decisions D119, D120)

Built from the 2026-10-14 audit's "ordering rule": sign-in is allow-listed, and the principal, tenant-scoped repositories with
the run / project guards, and deny-by-default gating are all in. **Nothing has run on DEV yet; the live Google flow, the
Postgres SQL (conditional upserts, the `tenant_id` clauses) and the new migration 0005 have only been exercised against mocks
and in-memory stores — the DEV smoke test is the first real check.**

| Finding | Status | What changed |
|---------|--------|--------------|
| F2 / audit 1, 6, 7 | **fixed in code** | `current_tenant_id()` replaces `PLATFORM_USER_ID` in every route (the Telegram module keeps the owner constant and is unmounted). A router-level guard (`interfaces/guards.py`) checks `run_id` / `project_id` from the path **and** `run_id` from a JSON body; another tenant's run is a 404 like a missing one; a run with no row is the owner's only. Repos take `tenant_id`; `/platform/runs`, project lists, run counts, activity and the library are filtered; `DELETE /runs/{id}` and the run settings moved behind the guard; importing another tenant's run id claims nothing. |
| F5 / audit 3 | **fixed** | A non-owner tenant's unreadable saved key raises a readable 409 instead of using the owner's Railway key. The owner's tenant keeps the old fallback. |
| F6 / audit 2 | **fixed** | Sessions are rows: random token, hashed at rest, 14-day expiry, revoked at logout, new at every login. The constant cookie is accepted as the owner only while `ACCEPT_LEGACY_COOKIE` is on — **set it false once the owner has signed in again**. |
| F4 / F8 / audit 4 | **fixed (interim)** | Server caps on script words, prompt, style and character text; runs per day; a per-tenant daily spend row reserved atomically before every paid call; one render at a time per tenant; an upload quota. D120. The spend figure is an estimate. |
| F13 / audit 5 | **built** | Moderation gate in front of storyboard, voice, scene prompts, write-with-the-director, image generate, continuity entries, Creator run text and run settings; terms click-through; per-tenant prompt log; owner routes to read the log and switch accounts off. The keyword rule is narrow by design. |
| audit 8 | **fixed** | Basic is a deny-by-default allow-list in the middleware and `require_super` on routers; `/platform/version` / health / echo / produce are Super-only; the Telegram router is unmounted unless `TELEGRAM_ROUTES_ENABLED` (F17's allow-list issue goes with it). |
| audit medium | **fixed** | Origin check on every mutating request (`ALLOWED_ORIGINS`); `redirect_uri` from config; single-use `state` + PKCE; `next` allow-list; in-memory repositories refused outside local (`ALLOW_IN_MEMORY_STORE`); `run_id` path params are checked as ownership (unknown or foreign = 404). |

**Still open or accepted after P-AUTH**

- Generated assets live under `runs/{run_id}/…` with no tenant prefix; ownership is the `runs` row and the ids are UUIDs. Revisit with P-BILL-1 (per-tenant delete / export).
- The login lockout limiter is in memory and per IP (the owner's password route); Google sign-in has no per-IP limiter.
- The moderation keyword rule can false-positive and cannot see impersonation or harassment; `MODERATION_PROVIDER=openai` adds a classifier. No review pipeline (D115).
- Image-model strings are still not allow-listed (audit medium); F16 key rotation, F19 `ffprobe`, F1 restore drill, CSP / `X-Frame-Options` header: unchanged, listed as "not in this sprint".
- Several session / OAuth rows are never purged (expired sessions, unused states): small, but add a janitor before the beta grows.
- A Super account that is not the owner is trusted with Studio routes of its own tenant only; it cannot read `/platform/admin/*`.

**Next audit:** at the P-AUTH close as planned — run it against DEV once the smoke test has exercised the real flow, and before P-BILL-1.


## Built in P-BILL-1 (2026-10-15, branch `claude/p-bill-1`; decision D123) — money paths, not yet audited

Credits, holds and refunds are new code that moves money-equivalents, and the next audit is **still due before `BILLING_ENABLED` is turned on** (the "Next audit" line above has not been met: AUTH-S10 and P-CORE-S11 have not run).

| Area | What was built | What to check in the audit |
|------|----------------|----------------------------|
| F8 (credit ledger) | `usage_entries`, `credit_accounts` (`CHECK balance >= 0`), `credit_transactions`; a hold is one conditional `UPDATE`, a refusal writes no row; the sign-up grant is a unique index | SQL was run against a real Postgres 16 (concurrency: 10 holds on 100 credits, 3 succeed; 20 refusals at once on a pool of 4; grant once) — **not** against Railway's database or migration 0006 on DEV |
| Owner routes | `/platform/admin/billing/{users,topup,usage,refund-stale}` behind `require_owner` and Super-only routers; the owner's own actions are never charged | top-up is a credit-creating route: only the owner's tenant may call it; every top-up records its actor and note |
| User route | `GET /platform/billing/me` (Basic allowed) answers for the caller's own tenant; there is no tenant parameter | isolation is tested with two real sessions |
| Failure handling | a hold is settled or refunded by the background job that took it; a job that never finishes (restart) leaves the hold open until the owner runs "Give back stuck holds" (`BILLING_HOLD_TTL_MINUTES`) | a ledger fault in `settle` / `refund` is logged and swallowed so it cannot mask the job's own result: look for `billing: could not settle|refund` in the log |

**Not covered by credits (a gap, unchanged from P-AUTH; the first two are accepted legacy exceptions in D123):** `POST /platform/runs/{run_id}/resume`, `POST /platform/pipeline/produce`, the acquisition worker (`/platform/workers/acquisition`: stock APIs, possibly a paid fallback) and the legacy pipeline do not call `limits.spend_gate`, so they are neither held nor metered. A Basic account cannot reach them (not on its allow-list); a **Super account that is not the owner can** — so while `SUPER_EMAILS` names only the owner nothing is exposed, and the day it names anyone else those calls are unbounded for them. Gate them (one `billing.reserve` each) before adding another Super account. (`POST /platform/workers/metadata` was in this list and is now held, settled and refunded like the others.)


## Audit — 2026-10-22 (scoped: money paths, erase tool, retention, legal pages)
**Scope:** `billing.py`, `limits.py`, the billing routes and every `reserve` / `settle` / `refund` call site (after BILL-F1 and BILL-F2), `erasure.py` + `scripts/erase_tenant.py`, `retention.py`, `legal_pages.py`; the accepted-risk register re-checked. Run by a read-only subagent; HIGH-1 was reproduced with a script, HIGH-2 and the rest were read, not run. 22 integration tests re-run on a throwaway Postgres.
**Findings:** 0 critical, 2 high, 4 medium, several low.
- **HIGH-1** A non-owner Super account that switches on View as Basic is never charged and never bound by the daily cap: `_charging_principal` returns None for any `view_as_basic` principal (`billing.py`), and `POST /auth/view-as` is open to every Super. Exposed the day a second Super account exists. Fix: skip charging only for `is_owner and view_as_basic`, or make view-as owner-only.
- **HIGH-2** Erasure can leave files behind: R2 `list_keys` makes one `list_objects_v2` call (max 1000 keys, no continuation), so a tenant with more objects is only partly deleted while the rows (and so the run ids) are removed. Fix: paginate `list_keys`; loop list-and-delete until empty; print bucket and DB host in the report.
- **MEDIUM** flat `EST_*` prices and `CREDIT_MARKUP=1.0` (compare with `trace_events`; set the 2K image price 0.03; a 0 price skips `spend_gate`); image-model strings not allow-listed for Super; unpriced `resume` / `produce` and uncapped `niche` / `angle` / `supporting_points` fields reachable by a non-owner Super; raw exception text returned to users as job errors, no security headers / CSP, and erasure does not disable the account first.
- **LOW** voice upload size read before the check; render-enqueue marker race; render copies and generated images not metered; a crashed bulk image job refunds images already made; `refund_stale_holds` marks every stale hold as having a reservation; top-up has no idempotency key; re-invite after erasure grants `SIGNUP_CREDITS` again.
**Sound (checked):** one close per hold (row-locking CTE), debit + entry in one transaction, no negative balance, no credits from nothing, parameterised SQL, owner routes behind `require_owner`, `/billing/me` has no tenant parameter, release-on-close fires only for the closing caller, client disconnect does not cancel a handler, erase tool refuses the owner and cannot match another tenant's prefix, legal pages escape every value.
**Fixed 2026-10-23 (same session, with tests):** HIGH-1 — only the owner's View-as-Basic preview is free; a non-owner Super is charged and bound (`_charging_principal`, `tests/test_p_bill1_audit_fixes.py`, 2 of 7 fail on the old rule). HIGH-2 — `R2ArtifactStorage.list_keys` follows the continuation token, `erasure.delete_prefixes` re-lists until empty and fails loudly after 50 passes, and the erase report prints the bucket and database host. **Fixed 2026-10-26 (BILL-F3):** a zero or unreadable price is refused for non-owners (the old behaviour let it skip `spend_gate`), and non-owner image models must be in `IMAGE_MODEL_COSTS_USD` (MEDIUM-1 zero-price part and MEDIUM-2); the estimate calibration itself waits on the operator (invoices, markup). **Stories opened:** BILL-F3 built; the medium findings are not yet stories.
**Accepted risks re-confirmed:** PROD behind DEV (while PROD is single-user); Telegram F17 (while unmounted); F5 operator-key fallback; legacy routes / F3 (off by default, owner-only).
**Accepted risks now expired:** F6 constant cookie (`ACCEPT_LEGACY_COOKIE` still defaults true — set false once the owner has signed in with Google); F2 "one operator" (now several tenants); no CSP / security headers; the "nothing exposed while `SUPER_EMAILS` names only the owner" note is exactly the condition HIGH-1 and the unpriced routes depend on.
**Could not verify:** Railway backups and the restore drill (F1), live Google flow and migration 0006 on DEV, `pip-audit`, git-history secret scan, real provider cost vs `EST_*`.
**Next audit due:** after HIGH-1 / HIGH-2 are fixed and before `BILLING_ENABLED` is set; then every 4th sprint review.
