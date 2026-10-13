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
| F1 | High | No documented Postgres or R2 backup, and no restore drill. D025's R2 versioning is an operator action nobody verified; R2's object versioning support itself needs a dashboard check | DECISIONS.md D025; nothing in docs/ | open | Story **HARD2-S1**: enable Railway Postgres backups, verify R2, write the RUNBOOK section, run one restore onto a scratch database |
| F2 | High | One shared identity: `PLATFORM_USER_ID="operator"` (75 uses); run repos have no user filter; run content is keyed `runs/{run_id}/…` with no tenant prefix | `cf_platform/interfaces/dependencies.py:68`, `core/postgres_repos.py:122,133`, `routes/studio.py` | accepted until P-AUTH (D114) | P-AUTH must scope everything by tenant (R2 prefix, repos, a central run-ownership dependency) |
| F3 | High | Legacy routes list, read and delete every run in the bucket; legacy ids are guessable `{date}_{slug}`; the legacy UI is served at `/legacy` | `src/routes/runs.py:70,80-92,257-273`, `src/main.py:197` | open | Unmount `/legacy` and the `src/routes/runs.py` router, or admin-gate them, **before P-AUTH ships** |
| F4 | High | `max_iterations` taken from the client with no bound (paid LLM calls); script and niche fields have no length cap | `routes/blocks.py:139`, `routes/workers.py:76,402` | **max_iterations fixed** (bounded 1–5, this sprint); length caps open | Server-side script length cap (word count tied to the video length) — decided in D115 |
| F5 | High (at beta) | A tenant key that cannot be decrypted falls back to the operator's Railway key, so one stranger's broken key spends the operator's account | `core/integrations.py:111-113` | open | At P-AUTH: for non-operator tenants fail the call with a readable error instead of falling back |
| F6 | Medium | Session cookie is a constant HMAC, valid one year, no user id, no expiry, no revocation | `src/auth.py:61-67`, `src/routes/auth.py:12` | accepted for one operator | Replaced by real sessions in P-AUTH |
| F7 | Medium | `OPERATOR_PASSWORD` / `SESSION_SECRET_KEY` accept empty or weak values; `SETTINGS_ENCRYPTION_KEY` defaults to empty with only a UI warning | `src/config.py:102-103`, `core/config.py:77` | open | Validators: non-empty, min length; refuse to start on `ENVIRONMENT=prod` without the encryption key. Not applied inline: a start-up check can take PROD down while it is being copied from DEV — do it with a release |
| F8 | Medium | Spend caps are per run only (image); no per-tenant or daily cap; LLM and TTS uncapped; no per-user rate limit | `core/config.py:112-114` | open | P-BILL-1 credit ledger; an interim daily cap if the beta opens first |
| F9 | Medium | `run_id` is not validated in worker request bodies and reaches a local `/tmp/{run_id}` path in the render | `routes/workers.py:76,402,673`, `src/ffmpeg_builder.py:985-989`, `workers/render_worker.py:849` | open | Constrain `run_id` to the uuid / legacy-id pattern in the request models |
| F10 | Medium | Legacy presigned PUT takes an arbitrary filename with no size or type bound | `src/routes/runs.py:102`, `src/models.py:647` | open | Goes away with F3 |
| F11 | Medium | A failed migration is swallowed: the app starts on the old schema, `/platform/health` shows only DB reachability, no lock between instances | `core/migrations.py:73-75`, `src/main.py:73-85` | open | Report migration status in health; advisory lock; a CD post-deploy check |
| F12 | Medium | Scene and music uploads read the whole file before the size check (200 MB / 50 MB) | `routes/studio.py:1250,1373` | open | Stream with early abort as the MP4 upload already does (`studio.py:445`) |
| F13 | Medium | No moderation, terms or abuse process for strangers' text and generated images | no code | **decided in D115** (minimal stance) | Implement in P-LITE / P-AUTH |
| F14 | Medium | Login lockout keys on the proxy's IP; any stranger can lock the operator out with 5 bad tries | `src/routes/auth.py:39` | open | `--proxy-headers` / trusted forwarded IP in `entrypoint.sh`; gone with P-AUTH |
| F15 | Low | R2 presigned-URL signature parameters and the Telegram bot token were not covered by log redaction | `src/log_redaction.py` | **fixed this sprint** | — |
| F16 | Low | One Fernet key, no rotation (`ENV.md`: "never change it") | `core/secret_box.py:19` | open | `MultiFernet` with a key id per stored key; needed before the first rotation |
| F17 | Low | Telegram webhook secret compared with `!=`; an empty allow-list means every chat is allowed; the route is dormant (D093) but can start paid jobs | `routes/telegram_webhook.py:478`, `interfaces/telegram.py:526` | **compare fixed this sprint**; allow-list open | Unmount the route while D093 stands |
| F18 | Low | Session cookie is not `Secure` outside `prod` (DEV is https) | `src/routes/auth.py:60` | open | `secure=True` for every non-local environment |
| F19 | Low | Uploads trust the client MIME; no magic-byte or `ffprobe` check before ffmpeg | `routes/studio.py:1246`, `workers/voice_upload.py:74` | open | `ffprobe` validation on upload |
| F20 | Low | No lockfile or hashes; no dependency scanner in CI; container runs as root; unpinned `python:3.11-slim`; `sentence-transformers` installed while `CLIP_RERANK_ENABLED` is off | `requirements.txt`, `Dockerfile`, `.github/workflows/ci.yml` | open | `pip-audit` in CI, lockfile, `USER app`, pinned base |
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
