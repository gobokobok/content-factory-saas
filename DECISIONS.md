# Architecture & Dependency Decisions

All significant architecture decisions and new dependency introductions are logged here.
**Rule:** No new dependency may be added to `requirements.txt` without a corresponding entry in this file.

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

## D003 — Google Drive for storage (service account auth)
**Date:** 2026-05-21
**Decision:** Google Drive is the run storage layer. Auth via service account JSON (base64-encoded in ENV var).
**Rationale:** Operator already uses Drive; no new storage infra needed. Service account avoids OAuth flow.
**Trade-off:** Requires operator to set up a GCP service account. One-time setup cost.

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

## D015 — Google service account JSON stored as base64 ENV var
**Date:** 2026-05-21
**Decision:** `GOOGLE_SERVICE_ACCOUNT_JSON` ENV var holds the base64-encoded contents of the service account JSON file. Decoded at startup.
**Rationale:** Railway ENV vars don't handle multiline JSON well. Base64 is a clean workaround.
**How to encode:** `base64 -i service-account.json | tr -d '\n'`
