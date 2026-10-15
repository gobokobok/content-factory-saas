# Testing Strategy — Content Factory

## Rule
Every story ships with tests. CI must be green before a story is marked complete.

## Test layers

### Unit tests (required for every story)
- Location: `tests/test_*.py`
- Scope: single function or class
- External APIs: always mocked
- Run with: `pytest -m "not integration"`
- Must pass in CI

### Integration tests (optional, run locally only)
- Location: `tests/integration/test_*.py`
- Scope: real API calls (Drive, Claude, Pexels, Replicate)
- Excluded from CI via pytest marker
- Use sparingly — smoke tests cover the same ground manually

## Mocking conventions

Use `unittest.mock.patch` or `pytest-mock` to mock:
- `src.drive.DriveClient` — mock folder creation, file upload/download
- `anthropic.Anthropic.messages.create` — mock Claude API responses
- `requests.get` / `requests.post` — mock Pexels, Freesound
- `replicate.run` — mock Replicate predictions

Always mock at the import boundary (patch the name where it's used, not where it's defined).

## What to test per story

| Story type | Required tests |
|------------|---------------|
| API endpoint | Happy path, missing/invalid input (422), upstream error (500) |
| Service module | Happy path, API error handling, fallback logic |
| Parsing/validation | Valid input, invalid/malformed input, edge cases |

### Golden render scripts (P13b)

`tests/golden/render/*.sh` pin the exact FFmpeg script the RenderWorker produces for a spread of runs
(motion effects, footage, captions, SFX, overlays, timing paths). `test_p13b_s1_golden_render.py` runs the
whole worker with FFmpeg stubbed. A golden changes only on purpose: regenerate with
`UPDATE_GOLDEN=1 pytest tests/cf_platform/test_p13b_s1_golden_render.py`, review the diff, and state it in
the story Handover. The `# generated_at` line is masked.

### Uploaded voiceover (P14b)
- Deepgram is always mocked: patch `cf_platform.workers.voice_upload._deepgram_transcribe` with a `DeepgramTranscript`. The request itself (the `language` parameter) is tested with `httpx.MockTransport`.
- `tests/cf_platform/test_p14b_transcript_edit.py` pins the timing-safe edit rule (slot arithmetic, refusals) on pure functions; `test_p14b_upload_routes.py` covers the routes, the guards and one end-to-end run (upload → edit → storyboard → timeline → render script).
- `tests/test_log_redaction.py` pins that no provider key (`key=`, `token=`, `api_key=`) survives in a formatted log record.

### Animation mode (P-AN1)
- `tests/cf_platform/pan1_helpers.py` gives `animation_env`: the P13 in-memory run with an Animation storyboard (every scene `ai_image`, a two-entry bible), a `FakeProvider` in place of the image provider, and the image settings. It clears the bulk job's process-local state (`scene_images._ACTIVE_JOBS`, `_RESERVED_USD`, `_RUN_LOCKS`) on entry.
- The model call is never made: patch `animation_storyboard_worker.request_animation_storyboard` with the JSON answer. `parse_animation_storyboard` and `build_animation_prompt` are pure and tested directly.
- kie.ai is replaced with `httpx.MockTransport` (`test_pan1_s6_nano_banana.py` pins the Nano Banana 2.1 request body).
- The bulk job runs inside the request in tests (TestClient executes background tasks before it returns), so a `POST …/images/generate` followed by `GET …/images/status` sees the finished job.

## Minimum test cases per function
1. Happy path — expected input, expected output
2. One failure case — API down, invalid response, missing field

## CI configuration
See `.github/workflows/ci.yml`. Tests run on every push to any branch.
```
pytest tests/ -m "not integration" --tb=short
```

## Coverage
No hard coverage threshold for POC. Aim for all critical path functions covered.

## Hermetic settings (2026-10-13)

Every test gets the settings the app requires from `tests/conftest.py` (`hermetic_settings_env`), filled in only where the environment does not already set them. The suite therefore passes on a clean machine with no `.env.local` and an empty environment, which is how CI runs. A test that builds the app still overrides the dependencies it cares about (storage, repositories); it no longer has to override the settings just to start. To check hermeticity: move `.env.local` away and run `env -i HOME=$HOME PATH=$PATH .venv/bin/python -m pytest tests -m "not integration"`.


## Word-matching regression corpus (2026-10-13)
`tests/cf_platform/test_hard1_word_matching.py` holds transcript / script pairs for the script view and the transcript
editor. When DEV refuses a paste, add the pair to `CORPUS` (transcript form, script form, expected start words) before
fixing `cf_platform/core/word_match.py`.

## Hardening tests (P-HARD2, 2026-10-13)

`tests/test_hard2_hardening.py` covers the start-up checks (`check_deployment_settings`), the `run_id` pattern, cookie `Secure`, the proxy-aware lockout, the legacy routes being unmounted by default, capped uploads, migration status in `/health` and the Dockerfile / workflow contract. Two things to know when adding to it or to other tests:

- **Routes are mounted at import time.** `tests/conftest.py` sets `LEGACY_ROUTES_ENABLED=true` before `src.main` is imported so the legacy routes stay testable; the "off by default" test runs `src.main` in a subprocess without it.
- **The secret-length and cookie checks are relaxed for the suite** (`AUTH_SECRET_MIN_LENGTH=1`, `COOKIE_ALLOW_INSECURE=true` in `conftest.py`'s defaults). A test of those checks passes the values explicitly.

## Billing tests (P-BILL-1, 2026-10-15)

- `tests/test_p_bill1_billing.py` — price arithmetic, hold / settle / refund, hard limits, who is charged (owner, View-as, billing off), top-up, stale holds; in-memory store, request principal set with `set_principal`.
- `tests/test_p_bill1_wiring.py` — each background job (voice, storyboard, render, transcription, bulk images) settles on success and refunds on failure, with a fake provider.
- `tests/test_p_auth_billing_routes.py` — routes with the **real auth middleware and real session cookies** (the `test_p_auth` prefix is what keeps `tests/conftest.py` from swapping in the owner): 402 body, holds taken by each route, `GET /platform/billing/me` isolation, the owner-only admin routes, the sign-up grant. A route that must see a non-owner principal belongs in a `test_p_auth*` file; a `TestClient` call in another file always runs as the owner.
- `tests/test_p_bill1_pages.py` — static checks of the Creator page and the owner's Credits screen.
- `tests/integration/test_billing_postgres.py` — migration 0006 and the conditional SQL against a **real Postgres** (`CF_TEST_DATABASE_URL`, excluded from CI). Run it after any change to `PostgresBillingStore`: it found a pool-exhaustion bug that no mock could (a refused debit asked the pool for a second connection while holding the first).
- Ordering tests read the route source (`route_source(...)` in the routes test) instead of `inspect.getsource` on the imported function: other tests patch those objects.
