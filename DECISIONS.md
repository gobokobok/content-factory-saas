# Architecture & Dependency Decisions

All significant architecture decisions and new dependency introductions are logged here.
**Rule:** No new dependency may be added to `requirements.txt` without a corresponding entry in this file.

---

## D029 — concat demuxer replaced with filter_complex trim+setpts
**Date:** 2026-05-24
**Decision:** FFmpeg script generation switches from concat demuxer to filter_complex with trim+setpts per scene.
**Rationale:** concat demuxer causes non-monotonic DTS on mixed-framerate sources (e.g. Pexels videos at 24fps mixed with Replicate images padded to 25fps). Non-monotonic DTS causes progressive audio drift and occasional "DTS out of order" errors that silently corrupt the output. filter_complex with `setpts=PTS-STARTPTS` resets timestamps correctly after every trim, eliminating carryover from source container timestamps.
**Implementation:** ffmpeg_builder.py — replace per-scene file list + `ffmpeg -f concat` with a single filter_complex graph: `[0:v]trim=...,setpts=PTS-STARTPTS[v0]; [1:v]trim=...,setpts=PTS-STARTPTS[v1]; ... [v0][v1]...concat=n=N:v=1:a=0[outv]`.
**No new dependencies.**

---

## D028 — zoompan parameters: fps=25, d=duration_s×25, scale+pad required
**Date:** 2026-05-24
**Decision:** zoompan filter uses fps=25, d=duration_s*25, s=1080x1920. All image inputs must be pre-scaled and padded to 9:16 before zoompan.
**Rationale:** zoompan `d` parameter is frame count, not seconds — using a hardcoded value (e.g. d=125 = 5s) causes incorrect duration on non-5s scenes. At fps=25, d=duration_s*25 is always correct. scale+pad normalization is required because zoompan `s` parameter only sets output size, not input size; a non-9:16 source will stretch rather than fill-and-crop without a preceding scale+pad filter.
**Parameters:** still_with_motion: z=1.0→1.05 (gentle zoom in). animated: z varies by motion_effect (zoom_in/zoom_out/pan_left/pan_right).
**No new dependencies.**

---

## D027 — ASS subtitles over FFmpeg drawtext
**Date:** 2026-05-24
**Decision:** Captions burned into video using ASS subtitle format via `vf ass=` filter, not FFmpeg drawtext.
**Rationale:** ASS supports full typographic control (font family, size, bold, color, outline, shadow, alignment, margin), animation (fade in/out, karaoke), and word-level timing in a single file. drawtext requires one filter invocation per text event and has limited styling: no outline blur, no per-event positioning, no animation. Escaping special characters in drawtext filter strings is error-prone and fragile. ASS is the industry standard for styled subtitle burn-in.
**Font:** Montserrat Bold or Roboto Bold, 72pt, white, MarginV=120 (bottom third). Text uppercased per YouTube Shorts style.
**Dockerfile change required:** `apt-get install -y fonts-open-sans` (or Montserrat via curl) to embed font in Railway container.
**No new Python dependencies.**

---

## D026 — Query decomposition strategy: concrete nouns only, two-tier primary/fallback
**Date:** 2026-05-24
**Decision:** Storyboard prompt updated to enforce query decomposition for Pexels search: primary_query uses 3-4 concrete nouns only (no adjectives); fallback_query uses 1-2 words (core subject only). Few-shot examples included in prompt.
**Rationale:** Pexels is keyword-matched, not semantic. Adjectives reduce recall without improving precision — "rundown suburban neighborhood" matches fewer clips than "suburban street house". Concrete nouns represent what a cameraman would frame, which is how stock footage is tagged. Two-tier structure ensures a broad fallback when primary specificity returns zero results.
**Flux/Replicate prompts** updated separately to use cinematic direction terms (shallow depth of field, golden hour lighting, cinematic) which do improve AI generation quality but are irrelevant for keyword search.
**Scope:** docs/PROMPTS.md storyboard system prompt only. No code changes to acquisition pipeline — queries flow through unchanged.

---

## D025 — R2 bucket versioning enabled at infrastructure level (not in code)
**Date:** 2026-05-24
**Decision:** Enable object versioning on the `content-factory-dev` (and `content-factory-prod`) R2 bucket via the Cloudflare dashboard. No code changes required.
**Rationale:** R2 native versioning provides full artifact history (every storyboard, manifest, script, and video version is recoverable) with zero application code. Building step-level versioning in the pipeline would add complexity and storage management burden without meaningful benefit over what R2 provides natively.
**Action required:** Operator enables versioning on both R2 buckets in Cloudflare dashboard → R2 → bucket → Settings → Object versioning → Enable. Takes ~30 seconds. One-time setup.
**Deferred indefinitely:** In-code artifact versioning strategy.
**No new dependencies. No new ENV vars.**

---

## D023 — Custom Dockerfile for FFmpeg on Railway
**Date:** 2026-05-23
**Decision:** Replace the default Railway Nixpacks buildpack with a custom `Dockerfile` based on `python:3.11-slim` that installs FFmpeg via `apt-get`.
**Rationale:** Railway's default Python buildpack does not include FFmpeg. The render pipeline (`ffmpeg_script.sh`) requires FFmpeg to be present at runtime. Confirmed by exit code 127 (`ffmpeg: command not found`) in `run_log.txt` during smoke testing.
**Implementation:** `Dockerfile` in repo root; `railway.toml` and `railway.prod.toml` updated to `builder = "DOCKERFILE"`.
**No new Python dependencies** — FFmpeg is a system package only.

---

## D022 — Human touchpoint rule applied at epic granularity
**Date:** 2026-05-22
**Decision:** Every epic must include a UI story that delivers a human-testable artifact at the end of the epic's first functional stories. Applied immediately: E6-S1 added after E2-S1 to cover the pipeline through asset manifest generation.
**Rationale:** D019 (Human Touchpoint Rule) established that no sprint should pass without something a human can touch. D022 refines this to the epic level — each epic's core backend work must be followed by a UI story before proceeding to the next epic. Prevents accumulating multiple epics of backend-only work with no operator-facing validation.
**Trade-off:** Slight delay to next backend epic (E3-S1) while UI story is completed. Accepted — the touchpoint catches integration issues early and keeps non-technical stakeholders engaged.
**Applied to:** E6-S1 (end-to-end pipeline UI covering POST /runs, POST /runs/{run_id}/storyboard, POST /runs/{run_id}/manifest).

---

## D001 — Modular pipeline architecture
**Date:** 2026-05-21
**Decision:** Each pipeline step is a standalone module exposed as an API endpoint. Steps are triggered manually (POC).
**Rationale:** Easier to develop, test, and retry individual steps. Manual handoff acceptable for POC. Orchestration can be added later.
**Trade-off:** More manual operator intervention vs. fully automated pipeline. Accepted for POC.

---

## D002 — Railway for hosting (DEV + PROD)
**Date:** 2026-05-21
**Decision:** Railway hosts both DEV and PROD as isolated services with separate ENV vars and Drive roots.
**Rationale:** Simple Python service deploy, no infrastructure management, free tier sufficient for POC.
**Trade-off:** Railway free tier has usage limits. Acceptable for POC volume.

---

## D003 — Storage layer
**Date:** 2026-05-21 (revised 2026-05-22 — see D020, D021)
**Decision:** Storage layer migrated from Google Drive to Cloudflare R2. See D021 for final rationale.
**History:** Originally Google Drive with service account auth → revised to OAuth refresh token (D020) → replaced with Cloudflare R2 (D021) due to OAuth being incompatible with autonomous operation.

---

## D004 — FastAPI over Flask
**Date:** 2026-05-21
**Decision:** FastAPI chosen as the web framework.
**Rationale:** Native async support for concurrent API calls (Pexels, Replicate, Drive), Pydantic validation built-in, auto-generated OpenAPI docs useful during development.
**Trade-off:** Slightly more setup complexity than Flask. Acceptable given async requirements.
**Dependency added:** `fastapi`, `uvicorn[standard]`

---

## D005 — Pydantic-settings for ENV validation
**Date:** 2026-05-21
**Decision:** Use `pydantic-settings` to declare and validate all required ENV vars at startup.
**Rationale:** Fail-fast on missing config, type coercion, clean settings object passed through the app.
**Dependency added:** `pydantic-settings`

---

## D006 — Pexels API for stock footage/images (free tier)
**Date:** 2026-05-21
**Decision:** Pexels as primary asset source. Free tier, no watermark.
**Rationale:** Free, adequate quality for POC, no per-request cost.
**Trade-off:** Rate limits on free tier. Handled with retry/backoff.
**Dependency added:** `requests` (HTTP client for Pexels)

---

## D007 — Replicate + Flux for AI image generation fallback
**Date:** 2026-05-21
**Decision:** Replicate API with Flux model as fallback when Pexels returns no result.
**Rationale:** Free tier available, Flux produces high-quality images suitable for documentary style.
**Trade-off:** Generation latency (async polling required). Acceptable as fallback path.
**Dependency added:** `replicate`

---

## D008 — Freesound API for SFX (free tier)
**Date:** 2026-05-21
**Decision:** Freesound API for SFX acquisition.
**Rationale:** Free, large library, API access with attribution.
**Trade-off:** Attribution required. Logged in output metadata.

---

## D009 — FFmpeg for video assembly (Railway-native)
**Date:** 2026-05-21
**Decision:** FFmpeg runs directly on Railway. Assets downloaded to `/tmp` for assembly, output uploaded to Drive.
**Rationale:** No external video service needed. FFmpeg available on Railway Linux containers.
**Trade-off:** Disk/memory usage on Railway during render. Monitor for large productions.

---

## D010 — Music: shared library, manual upload, POC selects first track
**Date:** 2026-05-21
**Decision:** Operator maintains a `/music-library` folder at Drive root. POC pipeline copies the first available track to the run folder. Smart selection logic deferred.
**Rationale:** Unblocks pipeline POC without building a music matching system.
**Trade-off:** Same track may repeat across runs. Acceptable for POC.

---

## D011 — Voiceover: manual operator upload for POC
**Date:** 2026-05-21
**Decision:** Operator records and uploads `.mp3` voiceover to run's `/voiceover` folder via the operator UI before triggering FFmpeg assembly. TTS (ElevenLabs) deferred.
**Rationale:** Unblocks pipeline without building TTS integration. Operator retains control over voice quality.
**Trade-off:** Manual step in pipeline. Deferred epic: ElevenLabs TTS integration.

---

## D012 — Run ID format: `{YYYY-MM-DD}_{operator-slug}`
**Date:** 2026-05-21
**Decision:** Run IDs are `{YYYY-MM-DD}_{slug}` where date is auto-prepended by the pipeline and slug is operator-provided via UI.
**Rationale:** Human-readable, sortable chronologically, unique by design.
**Constraint:** Slug must be lowercase, hyphens only (no spaces or special chars). Validated in UI.

---

## D013 — Step checkpointing via run_log.json
**Date:** 2026-05-21
**Decision:** `run_log.json` in the run folder tracks each step's status (`pending`/`complete`/`failed`). On restart, pipeline resumes from first incomplete/failed step.
**Rationale:** Enables reliable retry without re-running completed steps. Critical for expensive steps (AI generation, FFmpeg render).

---

## D014 — No UI framework; plain HTML/JS
**Date:** 2026-05-21
**Decision:** Operator UI is plain HTML/JS, no frontend framework.
**Rationale:** Minimal operator UI; framework overhead not justified. Served statically from FastAPI.
**Constraint:** No React, Vue, or similar. Vanilla JS only.

---

## D015 — Google service account JSON stored as base64 ENV var *(superseded by D021 — R2 migration)*
**Date:** 2026-05-21 (superseded 2026-05-22 by D021)
**Decision:** ~~`GOOGLE_SERVICE_ACCOUNT_JSON` ENV var holds the base64-encoded contents of the service account JSON file. Decoded at startup.~~
**Status:** Superseded. Storage migrated to Cloudflare R2 (D021). `GOOGLE_SERVICE_ACCOUNT_JSON` is no longer used or required. See D021 for current storage auth approach.

---

## D017 — Model selection policy (task-based routing)
**Date:** 2026-05-21
**Decision:** Claude API calls are routed to different models based on task type. No hardcoded model strings in modules — all routing goes through `src/utils/model_router.py` (E8-S4).

| Task type | Model | Rationale |
|-----------|-------|-----------|
| `VALIDATE` — schema checks, field validation | `claude-haiku-4-5-20251001` | Structured, low-complexity; cost matters at scale |
| `TRANSFORM` — storyboard → asset manifest | `claude-haiku-4-5-20251001` | Pure structured transformation, no reasoning required |
| `SUMMARIZE` — run_log.json → run_log.txt | `claude-haiku-4-5-20251001` | Template-like output, no creativity required |
| `GENERATE` — script → storyboard (prompt v0.4) | `claude-sonnet-4-6` | Creative + structured; quality matters for output |
| `REASON` — sprint review, architecture decisions | `claude-opus-4-7` | Highest complexity; used outside the pipeline |

**Rationale:** Haiku is sufficient for deterministic transformation tasks. Sonnet handles the core creative/structured generation. Opus reserved for high-stakes reasoning outside the production pipeline.
**Constraint:** Model strings must never be hardcoded in individual modules. Always use `ModelRouter` with task type constants.
**Override:** Each task type's model is overridable via `MODEL_<TASK_TYPE>` ENV var for testing and cost tuning.

---

## D021 — Migrate storage from Google Drive to Cloudflare R2
**Date:** 2026-05-22
**Decision:** Replace Google Drive (with OAuth refresh token auth) with Cloudflare R2 as the pipeline storage layer.
**Rationale:**
- Service accounts have no storage quota on personal Google Drive (HTTP 403 — D020)
- OAuth refresh token requires a human-in-the-loop consent flow, which is incompatible with autonomous Claude Code operation and adds ongoing maintenance burden (token expiry, re-auth)
- Cloudflare R2 uses static API token auth: 3 ENV vars, no expiry, no consent flow, no quota issues on personal accounts
- R2 is S3-compatible — boto3 works out of the box with a custom endpoint URL
- Free tier: 10 GB storage, 1M Class A operations/month — sufficient for POC
**Endpoint format:** `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`
**No real folders:** R2 is a flat key-value store. Run "folders" are key prefixes (e.g. `runs/2026-05-22_test-affordability/`). No folder creation needed.
**Updates:** D003 and D020 revised to reflect final decision.
**Dependency added:** `boto3` (replaces all google-* libraries)

---

## D020 — OAuth refresh token (superseded by D021)
**Date:** 2026-05-22 (superseded 2026-05-22 by D021 — R2 migration)
**Decision:** Authenticate with Google Drive using a stored OAuth 2.0 refresh token (`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_REFRESH_TOKEN`) instead of a service account JSON key.
**Rationale:** Service accounts have no personal Drive storage quota — uploads fail with HTTP 403 `storageQuotaExceeded` on personal Google accounts. Shared Drives (which solve the quota issue) require Google Workspace, which the operator does not have.
**Alternatives rejected:**
- Shared Drive — requires Google Workspace (Enterprise). Not available on personal accounts.
- OAuth delegation — requires Workspace admin and domain-wide delegation. Not available.
- Raw REST calls — same quota limitation applies; no benefit over SDK.
**How:** One-time local flow via `scripts/get_drive_token.py` (uses `google-auth-oauthlib`). Refresh token is long-lived unless revoked. Publish the OAuth consent screen to Production mode to remove the 7-day Testing-mode expiry.
**Dependency added:** `google-auth-oauthlib>=1.2.0` (local script only; production code uses `google.oauth2.credentials.Credentials` from the existing `google-auth` package).
**Updates:** D003 revised — service account JSON auth replaced by OAuth refresh token approach.

---

## D019 — Human Touchpoint Rule adopted into APEX-DEV methodology
**Date:** 2026-05-22
**Decision:** Every sprint must deliver at least one artifact a non-technical stakeholder can interact with. If a sprint is purely infrastructure, a minimal UI shim or smoke-test endpoint must be added before the sprint is finalized.
**Rationale:** Avoid multi-sprint infrastructure builds with zero stakeholder visibility. Catching UX and integration assumptions early is cheaper than discovering them after the pipeline is complete.
**Applied retroactively:** E6-S0 (Minimal run creation UI, 2 points) added to Sprint 1 to satisfy this rule — Sprint 1 was otherwise pure backend infrastructure.
**Enforcement:** Added to `sprint-review.md` step 6 (sprint planning) as a required check. Also documented in `CLAUDE.md` under Hard Constraints.

---

## D018 — Google Drive SDK choice *(superseded by D021 — R2 migration)*
**Date:** 2026-05-22 (superseded 2026-05-22 by D021)
**Decision:** ~~Use `google-api-python-client` + `google-auth` + `google-auth-httplib2` for all Google Drive operations.~~
**Status:** Superseded. Storage migrated to Cloudflare R2 (D021). All Google Drive SDK dependencies removed. Current storage client is `boto3` (S3-compatible, targeting R2 endpoint). See D021.

---

## D016 — Client-side Claude API calls in script-generator.html
**Date:** 2026-05-21
**Decision:** `tools/script-generator.html` calls the Claude API directly from the browser using the `anthropic-dangerous-client-side-api-key-allowed` header. Acceptable for local `/tools` use only.
**Rationale:** Standalone operator tool, opened locally, no server required. Browser-direct is the simplest and correct architecture for this use case.
**Constraint:** If Step 2a (script generation) is ever integrated into the Railway operator UI, the Claude API call must move server-side to avoid exposing the API key in a shared web context.
**Status:** Deferred — out of scope for current epics. Integration is not planned.
