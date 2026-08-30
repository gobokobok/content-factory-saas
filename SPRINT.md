> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-06-29 the active work is the **Platform v2 track (Sprints P0–P15)**, defined in **docs/v2_platform_plan.md** (decisions D047–D063).
> - **Sprints P0–P9 complete.** P9 velocity: 8/10 stories done; P9-S8 and P9-S10 carry to P10.
> - Sprints **S14–S17** (video-UX polish) are **PAUSED** — they resume later behind the legacy adapter.
> - The legacy Script→Video pipeline (Sprints 1–13) keeps running in DEV/PROD, untouched (D047).
> - Full history: **SPRINT_ARCHIVE.md** (Sprints 1–19 + Platform P0–P4).
> - **Next sprint:** P10 — Production quality + Visual Intelligence Layer.

---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P15)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D063 · **Stories:** BACKLOG_ACTIVE.md (current + next two sprints), BACKLOG.md (full archive).
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
| **P10** | **Production quality + Visual Intelligence Layer** | **~15** | **in-progress** | No food assets for "protein"; researcher portrait from Wikimedia; per-scene asset override in Studio |
| P-UX2 | **Render & narration controls** | **15** | **done** | Caption style preset, per-scene motion dropdown, TTS pace + register |
| P11 | Visual Director + motion effects | ~12 | in-progress | Visual Director agent; sub-scene cuts; film grain; animated callouts |
| P12 | Format tracks | ~10 | planned | `documentary`/`educational`/`animated` via `--format` flag |
| P13 | Analytics & attribution | ~11 | planned | Retention-by-prompt-version report |
| P14 | n8n automation | ~10 | planned | Niche → scheduled YouTube upload with no operator action |
| P15 | Multi-tenant SaaS frontend | ~20 | planned | Multi-channel, multi-run operator UI |

**Core platform (P0–P6) = 116 pts done. P7–P8 = 22 pts done. Total: 138 pts.**

---

# Sprint P5 — Idea→Script Block

**Goal:** P5-S1–S5 built the cyclic loop (shipped); P5-S6 rearchitects as Blueprint IR + single-pass + patch repair (target $0.05–$0.10/run).
**Status:** done
**Points:** 24

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P5-S1 | Script Writer worker (write ×N) | 3 | done |
| P5-S2 | Quality/virality scorer worker | 3 | done |
| P5-S3 | Fact-check tool integration (web search) | 3 | done |
| P5-S4 | Refine loop + convergence logic ⚠️ spike | 5 | done |
| P5-S5 | Assemble idea_to_script graph + interfaces (+ IdeaToScriptState) | 2 | done |
| P5-S6 | Rearchitect Idea→Script — Blueprint IR + single-pass + patch repair | 8 | done |

**Execution order:** P5-S1 → (P5-S2 ∥ P5-S3) → P5-S4 → P5-S5 → P5-S6.

## Sprint P5 Definition of Done
- [ ] Loop converges or stops at `max_iterations`; iteration is a typed state channel (D057)
- [ ] **Human touchpoint:** Telegram idea → fact-checked `script` artifact

---

# Sprint P6 — Orchestrator + Legacy Bridge

**Goal:** Parent graph chains niche→ideas → idea→script → voice → legacy render via the adapter; optional HITL gates; one command → video.
**Status:** done
**Points:** 24

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P6-S1 | Legacy adapter (interface + in-process impl) | 3 | done |
| P6-S2 | Legacy-as-node + parent graph (+ PipelineState) | 5 | done |
| P6-S3 | Human-in-the-loop gates | 3 | done |
| P6-S4 | End-to-end /produce → video | 2 | done |
| P6-S5 | Target duration parameter (run-level → script writer) | 3 | done |
| P6-S6 | Niche-aware prompts (replace hardcoded channel) | 3 | done |
| P6-S7 | Gemini TTS + /testvoice harness | 5 | done |

**Execution order:** (P6-S1 ∥ P6-S5 ∥ P6-S6) → P6-S2 → (P6-S3 ∥ P6-S4) → P6-S7.

## Sprint P6 Definition of Done
- [x] Only the adapter imports `src/`; legacy unchanged and still operable
- [x] One run threads lineage across blocks + legacy node
- [x] **Human touchpoint (P6-S7):** `/testvoice <run_id>` → presigned MP3 URL in ~30s; `/pick <run_id> <n>` → finished video — VERIFIED 2026-06-20 (P8-S0 smoke test sweep)

---

# Sprint P7 — Idea Selection + YouTube Metadata

**Goal:** Operator sees 5 ranked ideas, picks one, and receives a finished 16:9 video with ready-to-paste YouTube metadata (title, description, tags) in a single Telegram flow.
**Status:** done
**Points:** 8

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P7-S1 | Idea selection flow | 3 | done |
| P7-S2 | YouTube metadata worker | 3 | done |
| P7-S3 | Produce with selected idea + metadata reply | 2 | done |

**Execution order:** P7-S1 → (P7-S2 ∥ P7-S3).

## Sprint P7 Definition of Done
- [x] `/ideas <niche>` reply shows 5 numbered ideas
- [x] `/pick <run_id> <n>` triggers the full pipeline for the chosen idea
- [x] Telegram reply includes presigned video URL + YouTube metadata block
- [x] **Human touchpoint:** operator receives a 16:9 video + copy-paste YouTube metadata — VERIFIED 2026-06-20 (P8-S0 smoke test sweep)

---

# Sprint P8 — Footage Quality

**Goal:** Replace the serial Pexels→Replicate fallback with a multi-source merge+rank pipeline (Pexels + Pixabay searched concurrently; Wikimedia Commons added in S2; winner selected by resolution/QA score). Replicate retired. Add real-person photo routing via Wikipedia, gate every clip through a quality check, surface per-source coverage in the Telegram reply, and apply a colour grade to the final render. All `src/` code is written as clean isolated modules for direct import by P9's native AcquisitionWorker.
**Status:** done
**Completed:** 2026-06-20
**Points:** 14

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P8-S1 | Pixabay source — videos + photos | 3 | done |
| P8-S2 | Wikimedia Commons source — historic + general + person photos | 3 | done |
| P8-S3 | Real person detection + Wikimedia person photo routing | 3 | done |
| P8-S4 | Footage QA — per-scene quality gate + retry | 3 | done |
| P8-S5 | Source telemetry + Telegram footage report | 2 | done |
| P8-S6 | Colour grading presets (FFmpeg) | 2 | done |

**Execution order:** (P8-S1 ∥ P8-S6) → P8-S2 → P8-S3 → P8-S4 → P8-S5

## Sprint P8 Definition of Done
- [x] Pexels + Pixabay searched concurrently, winner by resolution; `PIXABAY_API_KEY` in ENV; D063 logged; Replicate retired (P8-S1)
- [x] Wikimedia Commons added to merge pool; historic-first routing; attribution stored per asset (P8-S2)
- [x] Storyboard prompt v0.10: `person_name` + `person_title` fields; PERSON SCENE exceptions; HISTORICAL SCENE exceptions; Wikimedia person photo first; fallback to generic stock on miss (P8-S3)
- [x] Every acquired clip passes resolution + duration + optional CLIP quality gate; retry on `fallback_query`; `CLIP_RERANK_ENABLED` in ENV (P8-S4)
- [x] `asset_manifest.json` records `source`, `qa_passed`, `qa_clip_score`, `fallback_used` per scene (P8-S4)
- [x] `footage_summary.json` written to R2 after acquisition; surfaced in Telegram reply with QA warning (P8-S5)
- [x] Early acquisition check: RuntimeError raised before ffmpeg if any scene has `file_key=None` (P8 hotfix)
- [x] `smart_format=true` for Deepgram — numerals in captions match verbatim script text (D045 revision)
- [x] Script generator prompt enforces word-count RANGE (min + max), not ceiling only
- [x] `COLOR_GRADE_PRESET` in ENV; 5 presets apply correct FFmpeg filter chain; `BLUR_FILL_ENABLED` for landscape stills (P8-S6)
- [x] All `src/` modules (`pixabay_client.py`, `wikimedia_client.py`, `footage_qa.py`) are standalone and importable by P9
- [x] **Human touchpoint:** `/run <niche>` → video + footage coverage line in Telegram reply; colour grade applied; 2:47 video at --duration 167 confirmed 2026-06-20

---

# Sprint P9 — Native Documentary Production Graph
**Status:** done (2026-06-29) · Velocity: 8/10 · P9-S8 and P9-S10 carried to P10

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P9-S1 | Storyboard schema v2 | 3 | done |
| P9-S2 | Native StoryboardWorker (generate → review → patch internal) | 5 | done |
| P9-S3 | Native AcquisitionWorker | 4 | done |
| P9-S4 | Native RenderWorker (dumb executor — reads render_options) | 4 | done |
| P9-S5 | Retire InProcessLegacyVideoAdapter + wire native pipeline | 2 | done |
| P9-S6 | Portrait/landscape format parameter (`--format` flag) | 2 | done |
| P9-S7 | Caption word assignment by timestamp (drop script text-matching) | 1 | done |
| P9-S8 | Per-scene asset override — custom query re-acquire + operator upload | 4 | carried→P10 |
| P9-S9 | Timestamp-first storyboard — word indices + Python-derived duration and asset tier | 5 | done |
| P9-S10 | Asset quality, character sourcing, and OST consistency | 5 | carried→P10 |

---

# Sprint P10 — Production Quality + Visual Intelligence Layer

**Goal:** Two tracks running in parallel. Track A (quality fixes): plug the five production bugs observed on v0.16.0 real runs, add per-scene asset override. Track B (intelligence): inject global semantic context into the storyboard and replace the current flat query lookup with an Entity Resolver + enriched visual signals — eliminating context-free acquisition without a full agent decomposition.
**Status:** done (2026-07-03) · all stories complete; human touchpoint line below remains deferred to a future DEV smoke test
**Points:** ~15

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P10-S1 (was P9-S10) | Asset quality, character sourcing, and OST consistency | 5 | done |
| P10-S2 (was P9-S8) | Per-scene asset override — custom query re-acquire + operator upload | 4 | done |
| P10-S3 (was P10-S1) | Semantic enrichment — global context + Entity Resolver + visual deduplication | 6 | done |

**Execution order:** P10-S1 and P10-S2 are independent; both can start immediately. P10-S3 depends on neither but should follow S1 (shares acquisition_worker.py).

## Sprint P10 Definition of Done
- [x] No `lower_third` rendered in any scene; Character scene person name appears as centre OST (P10-S1)
- [x] Character + historic scenes query Wikimedia first; `asset_manifest.source == "wikimedia"` confirmed (P10-S1)
- [x] No two scenes in the same run share the same `file_key` (P10-S1)
- [x] Every Event scene has non-empty `on_screen_text` after generation (P10-S1)
- [x] `→` `↑` render as correct glyphs in OST (Noto Sans font) (P10-S1)
- [x] Studio pencil icon: operator can swap a scene's asset without re-running full pipeline (P10-S2)
- [x] `verified_storyboard` contains `global_context` block on every run (P10-S3)
- [x] Every scene has `semantic_context` with `domain_qualifier` + `avoid` + `visual_tags` (P10-S3)
- [x] Entity Resolver routes Character + historic scenes to Wikimedia deterministically (P10-S3)
- [x] Visual concept deduplication pass fires when 3+ consecutive scenes share the same concept (P10-S3)
- [x] 6 pre-existing test failures in `test_ffmpeg_builder.py` / `test_runs.py` fixed — confirmed resolved at 2026-07-03 sprint review (full suite: 2000 passed, 0 failed)
- [ ] **Human touchpoint:** a re-render of a neuroscience topic run shows: no food assets for biological-protein scenes; researcher portrait from Wikimedia; all habit milestones have OST; Unicode arrows render correctly; operator can swap one scene asset from Studio — DEFERRED

---

# Sprint P11 — Visual Director + Motion Effects

**Goal:** Introduce the Visual Director as a dedicated post-storyboard LangGraph node that produces a full visual treatment (shot type, search terms, motion, diversity plan) before any asset is fetched. Add motion effect presets to the render layer. The acquisition layer becomes a pure fulfillment layer.
**Status:** PAUSED — S1 done; S2/S3 resume after Sprint P-UX2 (render & narration controls, 2026-08-30). S2 is now narrower: P-UX2-S3 shipped the motion vocabulary and the operator-facing dropdown it depended on.
**Points:** ~15

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P11-S1 (was P10-S2) | Visual Director agent — post-storyboard visual treatment | 6 | done |
| P11-S2 | Motion effect presets — film grain, camera shake, light leak | 3 | todo |
| P11-S3 | Sub-scene asset timeline — 2–3 assets per scene with sub-clip in/out points | 5 | todo |

**Execution order:** P11-S1 → P11-S2 (S2 adds `motion` preset execution that S1 specifies). P11-S3 is independent but large.

## Sprint P11 Definition of Done
- [ ] `visual_treatment` artifact written to R2 on every run
- [ ] `AcquisitionWorker` reads `visual_treatment.search_terms` as primary source
- [ ] No 3+ consecutive scenes with same `shot_type`; diversity validator with 1-retry enforced
- [ ] `footage_summary` includes `diversity_score`
- [ ] At least 3 further motion presets (film_grain, camera_shake, light_leak) applied correctly in render script
      — zoom/pan/Ken Burns already shipped in P-UX2-S3 as the `MOTION_EFFECTS` vocabulary (D081); S2 extends it
- [ ] **Human touchpoint:** neuroscience run — no food for protein scenes; diversity score in Telegram; 2 motion presets visibly applied in output video

---

# Sprint P-UX2 — Render & Narration Controls

**Goal:** Treat the validated 9:16 setup as the template and add operator-selectable variants on top of it: a caption style preset, a real per-scene motion-effect vocabulary (the field was dead code before this sprint), narration pace + emotional register, all driven through one shared dropdown component.
**Status:** done (2026-08-30)
**Points:** 15

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P-UX2-S1 | `.cf-select` dropdown component + SFX column restyle | 3 | done |
| P-UX2-S2 | Caption style preset — Standard / Punch (one word, ALL CAPS) | 4 | done |
| P-UX2-S3 | Motion effect vocabulary + per-scene Motion dropdown | 5 | done |
| P-UX2-S4 | Narration pace + emotional register | 3 | done |

**Execution order:** S1 → (S2 ∥ S3 ∥ S4).

## Sprint P-UX2 Definition of Done
- [x] One shared `.cf-select` component styles every dropdown (Settings selects, Motion and SFX table cells)
- [x] Settings stage exposes caption style, narration pace and narration register; all three persist to `settings.json` and rehydrate on run load
- [x] `caption_style` reaches the renderer (`RenderWorkerRequest` → `state.inputs` → `_build_render_script`); Punch renders one uppercased word per caption with no active-word highlight
- [x] `motion_effect` is honoured by the render script for the first time (it was dead code — see D081), patchable per scene, and validated against `MOTION_EFFECTS`
- [x] Pans traverse the full landscape image inside a 9:16 frame (time-driven `crop`, verified in FFmpeg)
- [x] Narration pace + register reach the TTS via `settings.json`, with D073's pause wording preserved verbatim in every combination
- [x] **No regression:** a pre-D081 storyboard produces a byte-identical render script before and after
- [ ] **Human touchpoint:** operator picks Punch captions + a narration pace in Settings, sets a scene to *Pan right* in the Storyboard table, renders a 9:16 video, and sees all three — PENDING a DEV run

---

# Sprint P-UX1 — Studio UX Redesign

**Goal:** Redesign the Studio operator UI per the approved mockup: centered run-list landing screen, a centered pipeline shell (stage nav + auto-advance + info panel, no "Studio"/run-id header chrome), a new Settings stage (aspect ratio, style, background music, captions) so these are chosen before acquisition instead of at render time, and a new Metadata stage (title/description/tags/pinned comment) wired to the existing `youtube_metadata` worker. Legacy `pipeline.html` stops being the default UI — Studio becomes primary.
**Status:** done (2026-07-03)
**Points:** 14

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P-UX1-S1 | Run shell redesign — centered landing + pipeline header + info panel | 3 | done |
| P-UX1-S2 | Settings stage — aspect ratio, style, music upload, captions | 5 | done |
| P-UX1-S3 | Metadata stage — youtube_metadata worker wired into Studio | 3 | done |
| P-UX1-S4 | Retire legacy pipeline.html as default UI (`/` → Studio) | 3 | done |

**Execution order:** S1 → (S2 ∥ S3) → S4.

## Sprint P-UX1 Definition of Done
- [x] Landing screen shows a centered run list (from `studio_runs` local history) with a "+ New run" button above it
- [x] Pipeline header has no "Studio" label or run-id badge; stage nav is centered with auto-advance toggle + info icon on the same row
- [x] Info icon opens a slide-out panel with run id, created date, cost placeholder, aspect ratio
- [x] Settings stage: aspect ratio (9:16/16:9) and captions on/off flow into the storyboard + render worker calls; style pills show Realistic active / Animated disabled
- [x] Background music: operator can upload an MP3 to the run; render falls back to the shared `music-library/` copy when none is uploaded
- [x] Metadata stage: suggested title/description/tags/pinned comment generated via the existing `youtube_metadata` worker (P7-S2), editable, with a permanently-disabled "Upload to channel" button (channel API is out of scope)
- [x] `GET /` serves Studio; legacy `pipeline.html` moved to `/legacy` (kept operable, not deleted, per D047)
- [x] **Human touchpoint:** operator opens `/`, sees the run list, starts a new run, sets aspect ratio + captions in Settings, runs the pipeline through to Metadata — VERIFIED 2026-07-03 against the real R2 DEV bucket via browser preview; "Upload to channel" correctly disabled pending channel API (out of scope)
