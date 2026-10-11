# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last sprints (P-UX4, P-AN1, P-UX3) plus every older entry whose smoke test is still DEFERRED (currently P-UX4) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

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
**Smoke test:** DEFERRED — operator will smoke test after both sprints → cleared by INT1-S5 in Sprint P-INT1 (the INT1-S5 list covers P-UX4, P-PROJ1 and P-INT1).
**Promoted to backlog:** INT1-S6 candidate: move script, storyboard and fact-check workers onto `LLMClient` (or an equivalent that keeps thinking and streaming), one at a time with a prompt check; per-block fallback order for providers; key validity check on save.

---

## [P-PROJ1 / P-UX4 post-close fixes] Scene boundaries tolerate spelled numbers and punctuation; compact animation scene cards
**Completed:** 2026-10-11 (operator feedback on DEV)
**Handover:**
- **Script view / `PUT …/storyboard/boundaries`:** the voiceover's words come from Deepgram (`smart_format`: "$109 million", "60%", no punctuation), so script text pasted into the view never matched ("The words differ"). `align_text_to_words` (`storyboard_edit.py`) now compares words ignoring case, punctuation, currency/percent marks and spelled-out numbers ("one hundred nine million dollars" = "$109 million", "two thousand eight" = "2008", "one point seven" = "1.7") and maps paragraph breaks through the matched units; a real wording change is still a 422. The response carries `matched_by_position`. Not handled: years said as two pairs ("twenty twenty four") — they read as "20 24" and are refused.
- **Animation scene card:** the prompt, concept, shot and keywords sit in one collapsed "Image prompt" section (open by itself only when a scene has no prompt; the choice survives a redraw); Merge shares the tools row; the repeated "ai_generated" badge is gone. A card drops from about 290 px to about 120 px.
- Tests: 2914 passing.
**Not verified:** against real DEV storyboard data (the number matcher was exercised on constructed examples).

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
**Smoke test:** DEFERRED — operator will smoke test after P-INT1 → cleared by INT1-S5 in Sprint P-INT1 (list in INT1-S5, extended below).
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
**Smoke test:** DEFERRED — operator decision 2026-10-11: test after P-INT1 is built → cleared by INT1-S5 in Sprint P-INT1. List: create a run from the modal (Animated + master prompt) and walk the five steps with Next only; upload a voiceover, switch Script to Generate, go to Voiceover and generate over it; toggle captions on the Video step and see Run settings follow; check a video's file name in the library; view a narrow screen.
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
