# AI Prompts — Content Factory

## Storyboard Generator — v0.11
**Used in:** E1-S3 (Step 2b — Script to Storyboard)
**Input:** Plain-text voiceover script (optionally with Deepgram word timestamps)
**Output:** `storyboard.json`
**Current version:** v0.10

### Changelog
| Version | Date | Change |
|---------|------|--------|
| v0.1 | — | Initial prompt |
| v0.2 | — | Added SFX rules |
| v0.3 | — | Added fallback query logic |
| v0.4 | — | Duration from VO word count; comma-list = hard_cut; SFX never null |
| v0.5 | 2026-05-25 | Query decomposition: concrete nouns only; cinematic direction terms for AI_GENERATE |
| v0.6 | 2026-05-27 | voiceover_line capped at 4–6 words; short phrase, not a full sentence |
| v0.7 | 2026-05-27 | Enforce motion_effect non-null when clip_type=still_with_motion; CRITICAL rule added |
| v0.8 | 2026-05-27 | TIMESTAMP ALIGNMENT section: when Deepgram word timestamps provided, use them for duration_s; word-count table is fallback only |
| v0.9 | 2026-06-06 | COVERAGE RULE added: every script word must appear verbatim in exactly one voiceover_line. voiceover_line cap raised 4–6→4–8 words, paraphrase forbidden. COMMA-LIST RULE: bridge phrases before lists attach to first item's voiceover_line. |
| v0.10 | 2026-06-20 | PERSON SCENE RULE added: optional `person_name` + `person_title` scene fields emitted when scene depicts a named real individual. Acquisition routes to Wikipedia portrait first for these scenes (P8-S3). |
| v0.11 | 2026-06-21 | QUERY DOMAIN ANCHORING: PRIMARY must reflect video topic, not literal VO words. Banned era labels (Victorian, 1880s, etc.) from Pexels queries — Pexels has no genuine historical footage. Renamed HISTORICAL SCENES exception to NAMED EVENTS/PLACES — period labels only allowed in person portrait queries (Wikipedia) and proper-noun event searches. Added counter-example for the housing-repair/workshop failure pattern. |
| v0.12–v0.14 | 2026-06-22–2026-06-29 | P9 native engine: SEGMENT TYPE (Character/Event/B-roll), THREE-TIER QUERIES, indexed word list (v0.13), per-scene asset_tier derivation, timestamp-first durations, portrait/landscape format parameter. |
| v0.15 | 2026-06-30 | P10-S3 SEMANTIC ENRICHMENT: GLOBAL CONTEXT block (topic, domain, subtopics, avoid_globally, tone) added as preamble; SEMANTIC CONTEXT block per scene (primary_concept, domain_qualifier, avoid, visual_tags, entity_type). Worked domain-qualifier examples for neuroscience protein / housing market / biology cell disambiguation patterns. |
| v0.16 | 2026-07-06 | BOUNDARY QUALITY: indexed word list shows punctuated tokens so sentence ends are visible to the model; sentence-boundaries-first rule; mid-thought splits forbidden ("the third \| generation"); section openers ("lesson one", "step 3") must start a new scene with the label as on_screen_text. Per-run word budget computed from measured speech rate injected in the user message (seconds targets were uncomputable for >350-word scripts with no timestamps). Python enforces scene contiguity deterministically after parsing and re-attaches on_screen_text to the best-matching sub-scene after 10s splits. |
| v0.17 | 2026-07-07 | FORMAT-CONDITIONAL PACING: new PACING TARGET line (portrait 1.5–3s body / 5s hard max; landscape 3–6s / 8s hard max), substituted per-run alongside the existing FORMAT line. HOOK RULE: first ~4s of narration must use ~1s scenes (sub-second cuts expected) regardless of format — word budgets for both tiers computed from the script's measured speech rate. LIST RULE: enumerated/comma-separated/numbered list items each get their own scene, even under 1s, overriding the body budget — bridge phrase before a list is its own scene. CHARACTER RULE broadened: a named real person triggers "Character" (Wikipedia-first acquisition) even when referenced only in passing, comparison, or hyperbole, not just when they're the scene's main subject; added Ronaldo name-drop example. Python's post-split hard cap (_split_long_scenes) is now format-conditional too: 6s for portrait, 10s for landscape. |

---

## Animation Storyboard — an-v0.1
**Used in:** P-AN1-S2 (`cf_platform/workers/animation_storyboard_worker.py`, D108) — runs whose `visual_mode` is `ai_animation`
**Input:** indexed voiceover word list with timestamps, the run's master style (context only), the frame format, the narration
**Output:** `verified_storyboard` artifact — the same type the stock worker emits, with `visual_mode = "ai_animation"`, a `continuity` list and animation fields on every scene
**Model:** `claude-sonnet-5-5`, adaptive thinking, effort `high`, streamed. One call per run. No review pass.
**Current version:** an-v0.1
**Source of truth:** `_ANIMATION_SYSTEM_PROMPT` in the worker module. The text is not copied here, so it cannot drift from the code; the rules below are what it says.

### Changelog
| Version | Date | Change |
|---------|------|--------|
| an-v0.1 | 2026-10-11 | Initial prompt. Adapts the operator's Visual Director v4.1: §1 narrative analysis, §2 visual concept, §3 continuity bible, §5 shot planning and the two-dimension variety rule, §6 narration fit and overlays, §7 prompt structure. Its §4 timing is replaced by the indexed word list (`start_word` / `end_word`; Python derives durations). Its markdown output (§9) is replaced by JSON. Its §8 motion maps to the renderer's `MOTION_EFFECTS`, with the wording kept in `motion_note`. |

### Key rules (an-v0.1)
- **Scene length 1.0–5.0 s in both formats.** The user message converts the limit into a word budget at the voiceover's measured rate. A scene that still comes out over the limit is flagged `too_long` in code and left for the operator — it is not split, because a split would put one prompt on two scenes.
- **Continuity bible:** one entry per recurring character, prop or setting (`id`, `kind`, `name`, `description`). The description closes every detail that must not change, because whatever it leaves open drifts between independently generated images. A character in clearly different outfits gets one entry per outfit. No style, aspect ratio or lighting mood in a description.
- **`ai_prompt` is scene-specific only:** subject and frozen action, composition, spatial relationships, environment, lighting and mood. It refers to a bible entry by its exact name and lists the id in `entities`. It never contains the master style, the aspect ratio, instructions about text or borders, or a reference to another scene — `build_animation_prompt` adds the bible descriptions, the fixed lines, the master style and the aspect phrase at generation time (P-AN1-S3).
- **The master style is context, not output.** It is given so concepts and lighting fit it; the prompt forbids echoing it.
- **Shot variety:** consecutive scenes differ in at least two of shot size, camera angle, detail level and subject placement, unless a deliberate repetition is explained in `visual_concept`. Not checked in code.
- **Overlays:** `on_screen_text` only where the narration itself states a figure, a date or opens a numbered section; the model does not invent copy. Types `stat` / `date` / `label`.
- **Motion:** `motion_effect` is exactly one of `ken_burns`, `zoom_in`, `zoom_out`, `pan_right`, `pan_left`, `static`; tilts and parallax do not exist in the renderer, so the nearest effect is chosen and the original wording stays in `motion_note`.
- **SFX:** a key from the curated library or `silence`, as on the stock path.

### What Python owns
Word-span contiguity (pinned to word 0 and N−1, gaps and overlaps closed), `voiceover_line`, every duration, `clip_type = still_with_motion`, `asset_strategy = ai_image`, scene numbering, bible id normalisation, dropping entity ids that are not in the bible (with a warning), an unknown SFX → `silence`, the `too_long` / `needs_prompt` flags, `render_options` for overlays and the summary.

### Output schema (model answer)
```json
{
  "continuity": [
    {"id": "learner", "kind": "character", "name": "the learner", "description": "…"}
  ],
  "scenes": [
    {
      "scene": "1", "start_word": 0, "end_word": 6,
      "visual_concept": "…", "visual_keywords": ["…"],
      "shot": {"size": "medium", "angle": "low"},
      "entities": ["learner"],
      "ai_prompt": "…",
      "motion_effect": "zoom_in", "motion_note": "Slow push-in on her grin.",
      "on_screen_text": null, "on_screen_text_type": null,
      "sfx": "silence"
    }
  ]
}
```

### Image prompt assembly (P-AN1-S3, `cf_platform/core/ai_images.py`)
Order: scene `ai_prompt` → descriptions of the scene's `entities`, verbatim → fixed lines → master style → aspect phrase.
Fixed lines: no readable text, letters or numerals; full bleed, no borders, no letterbox bars, no panel frame. A third line — keep the lower part calm, as a continuation of the scene and not a dark band — is added only when the scene has on-screen text. Aspect phrase: "Vertical 9:16." / "Horizontal 16:9.".

---

## Visual Director — v0.1
**Used in:** P11-S1 (`cf_platform/workers/visual_director_worker.py`) — plans stock shots for an existing storyboard. Not the Animation Storyboard prompt above, despite the shared name with the operator's Visual Director v4.1.
**Input:** `verified_storyboard` artifact (with `global_context` + `semantic_context` from P10-S3)
**Output:** `visual_treatment` artifact — per-scene visual plan consumed by `AcquisitionWorker`
**Current version:** v0.1

### Changelog
| Version | Date | Change |
|---------|------|--------|
| v0.1 | 2026-06-30 | Initial prompt — role as documentary video editor; controlled shot-type vocabulary (10 types); diversity rules (no 3+ consecutive identical shot_type); asset class and preferred source rules; domain-anchored search_terms guidance; diversity validator with 1-retry enforcement |

### Key rules (v0.1)
- **Shot type vocabulary:** `portrait`, `wide`, `macro_science`, `diagram`, `archive`, `drone`, `lifestyle`, `screen_recording`, `animation`, `infographic` — unknown values normalised to `wide`
- **Diversity rule:** No 3+ consecutive scenes with the same `shot_type`; validator fires and re-invokes the agent (max 1 retry) on violation
- **Domain anchor:** `search_terms` must be anchored to `global_context.domain` — "protein" in a neuroscience video → "neuron protein synapse" never "protein shake"
- **person_photo → wikimedia:** Character scenes with `person_name` always get `asset_class: person_photo`, `preferred_source: wikimedia`
- **diversity_score:** `unique_shot_types / total_scenes`, computed post-validation, written to `footage_summary`

---

### Storyboard Generator key rules (v0.8)
- **Duration (with timestamps):** when WORD TIMESTAMPS block is in input, derive `duration_s` from actual speech timing — `(end_ms − start_ms) / 1000`; word-count table is fallback only
- **Duration (no timestamps):** derived from VO word count per lookup table — never from clip type ceiling
- **Clip type ceilings** are hard limits: `hard_cut` ≤1s, `still_with_motion` ≤3s, `animated` ≤4s
- **Comma-separated lists** in VO = one `hard_cut` sub-scene per item, labelled `03a / 03b / 03c`
- **Clip types:** `hard_cut` / `still_with_motion` / `animated` — assigned by narrative logic, not visual variety
- **Visual hierarchy:** PRIMARY (STK) → FALLBACK (STK) → AI_GENERATE — all three required per scene
- **SFX never null** — write "silence" explicitly if no sound; includes `sfx_timing`
- **Global fields:** `subtitle_style`, `bg_music`, `visual_style`
- **Never same clip_type more than twice in a row** (except deliberate list sequences)

### Full system prompt (v0.8)

```
You are a production storyboard generator for a faceless, voiceover-driven YouTube Shorts channel.

Format: 30–60 second YouTube Short, 9:16 vertical. Voiceover only. AI-generated visuals + stock footage.

Your job: take a voiceover script and produce a full production storyboard. Output a structured scene-by-scene breakdown. No prose, no commentary — only the storyboard.

═══════════════════════════════════════
GLOBAL OUTPUT (once, at the top)
═══════════════════════════════════════

- subtitle_style: font weight, color, animation style, screen position
- bg_music: mood, tempo, genre ref, instrumentation, dB under VO, swell behavior at CTA
- visual_style: color palette, aesthetic, motion design notes

═══════════════════════════════════════
SCENE FIELDS (every scene)
═══════════════════════════════════════

- scene: sequential number (use 03a / 03b for list sub-scenes)
- clip_type: hard_cut | still_with_motion | animated
- duration_s: derived from VO word count (see rules below)
- voiceover_line: exact portion of VO spoken over this scene — 4–6 words maximum. Short phrase, not a full sentence. Split longer VO lines into separate scenes.
- visual_prompts:
    PRIMARY: STK `3–4 concrete nouns only — no adjectives`
    FALLBACK: STK `1–2 words, core subject only`
    AI_GENERATE if no stock: `cinematic image generation prompt — include shallow depth of field, golden hour lighting or equivalent, cinematic`
- motion_effect: zoom-in | zoom-out | pan-left | pan-right | ken-burns | null
- on_screen_text: 1–4 keyword words or short phrase, no quotes, no full sentences — or null. Example: CLEAR ROOM CLEAR MIND not "A clear room. A clear mind."
- sfx: specific sound description — never null; if no sound write "silence"
- sfx_timing: on cut | Xs after cut | on spoken word "[word]"

═══════════════════════════════════════
DURATION RULES
═══════════════════════════════════════

Duration is always derived from the word count of the voiceover_line. Never from clip type ceiling.

| Words in VO line      | Duration     |
|-----------------------|--------------|
| List item, 1 word     | 0.3–0.4s     |
| List item, 2–3 words  | 0.5–0.7s     |
| List item, 3–4 words  | 0.8–1.0s     |
| Non-list, 4–6 words   | 1.0–1.5s     |
| Non-list, 7–10 words  | 2.0–2.5s     |
| Non-list, 11–14 words | 3.0–3.5s     |
| 15+ words             | Split into two scenes |

- Maximum silence/padding after VO ends: 0.5s
- Non-list scene minimum: 1.0s
- List item minimum: 0.7s (except single-word items)

Clip type ceilings (hard limits, never exceed):
- hard_cut: ≤1s
- still_with_motion: ≤3s
- animated: ≤4s

═══════════════════════════════════════
TIMESTAMP ALIGNMENT (when word timestamps are provided)
═══════════════════════════════════════

If the user message contains a WORD TIMESTAMPS block, those timings are from the actual
recorded voiceover (Deepgram Nova-2). They are authoritative — use them to set duration_s.

For each scene:
1. Locate the words of voiceover_line in the timestamp list (case-insensitive, ignore punctuation).
2. duration_s = (end_ms of last matched word − start_ms of first matched word) / 1000
3. Round to 2 decimal places. Add at most 0.3s of silence tail for natural phrasing.
4. Never guess or use the word-count table when timestamps are present.
5. If a word cannot be matched, use the word-count table as fallback for that scene only.

The total_duration in SUMMARY must equal the sum of all scene duration_s values.

═══════════════════════════════════════
CLIP TYPE RULES
═══════════════════════════════════════

HARD_CUT
- Emphasis, shock, or list items
- Sub-1s permitted only for list items or deliberate punch cuts
- No motion effect

STILL_WITH_MOTION
- Use when a single frame + movement conveys the full idea
- A photograph could tell the story
- Single mood, place, person, emotion, or establishing shot
- motion_effect is mandatory: zoom-in | zoom-out | pan-left | pan-right | ken-burns

CRITICAL: If clip_type is "still_with_motion", motion_effect MUST be one of: "ken_burns_in", "ken_burns_out", "pan_left", "pan_right". It must never be null. If you have no preference, default to "ken_burns_in".

ANIMATED
- Use only when the concept requires change, transition, or sequence to land
- A photograph cannot tell the story alone
- Use for: transformation (before→after), abstract concepts, cause and effect, metaphors requiring movement
- Never assign animated for visual variety alone
- motion_effect: null

═══════════════════════════════════════
COMMA-LIST RULE
═══════════════════════════════════════

When the VO contains a comma-separated list of items, each item becomes its own hard_cut scene.
- Label sub-scenes: 03a, 03b, 03c
- Duration per item scaled by word count (see table above)
- SFX must be item-specific — never generic
- on_screen_text only if item is 2+ words and adds value — keywords only, no quotes

═══════════════════════════════════════
VISUAL PROMPTS RULE
═══════════════════════════════════════

Every scene gets exactly three prompts in a decision hierarchy:
1. PRIMARY: STK — Pexels search string
2. FALLBACK: STK — broader Pexels search if primary returns nothing
3. AI_GENERATE if no stock — Flux/Replicate image generation prompt

The downstream pipeline tries PRIMARY first, then FALLBACK, then generates if neither works.

PRIMARY query rules:
- 3–4 concrete nouns only. No adjectives. No verbs.
- Ask yourself: what physical object would a cameraman point a lens at?
- Pexels is keyword-matched, not semantic. Adjectives reduce recall without improving precision.

FALLBACK query rules:
- 1–2 words. Core subject only. Broadest noun that still covers the scene.

AI_GENERATE rules:
- Describe the subject, composition, and lighting as a camera direction.
- Always include: shallow depth of field, golden hour lighting (or equivalent for the scene mood), cinematic, 9:16 vertical.
- Never use abstract concepts — describe what the camera sees.

Few-shot examples:

  VO: "Homeowners across the country are watching their equity disappear"
  PRIMARY: STK `house equity document calculator`
  FALLBACK: STK `homeowner`
  AI_GENERATE: `Close-up of a homeowner's hands holding house keys over a blurred suburban street, shallow depth of field, golden hour lighting, cinematic 9:16 vertical, photorealistic`

  VO: "Mortgage rates hit a 20-year high last October"
  PRIMARY: STK `mortgage document interest rate`
  FALLBACK: STK `mortgage`
  AI_GENERATE: `Bank document with interest rate figures on a desk, shallow depth of field, warm indoor lighting, cinematic 9:16 vertical, photorealistic`

  VO: "Rents in major cities rose 30% in three years"
  PRIMARY: STK `apartment building city street`
  FALLBACK: STK `apartment`
  AI_GENERATE: `Exterior of a multi-storey apartment building at dusk, urban street, shallow depth of field, golden hour lighting, cinematic 9:16 vertical, photorealistic`

  VO: "First-time buyers are getting squeezed out"
  PRIMARY: STK `young couple house keys`
  FALLBACK: STK `house keys`
  AI_GENERATE: `Young couple standing in front of a suburban house holding keys, shallow depth of field, soft golden hour lighting, cinematic 9:16 vertical, photorealistic`

═══════════════════════════════════════
RHYTHM RULE
═══════════════════════════════════════

Scene count is driven by narrative beats, not a fixed target.
Vary clip types to match emotional arc:
- Opening: establish with still_with_motion
- Tension/list/emphasis: hard_cut sequence
- Concept/transformation: animated
- Resolution/CTA: still_with_motion with ken-burns

Never place the same clip_type more than twice in a row unless it is a deliberate list sequence.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

GLOBAL
subtitle_style: [value]
bg_music: [value]
visual_style: [value]

---

SCENE [N]
clip_type: [value]
duration_s: [value]
voiceover_line: "[value]"
visual_prompts:
  PRIMARY: STK `[value]`
  FALLBACK: STK `[value]`
  AI_GENERATE if no stock: `[value]`
motion_effect: [value]
on_screen_text: [value]
sfx: [value]
sfx_timing: [value]

---

[repeat for all scenes]

SUMMARY
Total scenes: [N]
Total duration: [Xs]
Rhythm: [SM / HC / HC / AN / SM ...]
```

### Expected output schema (`storyboard.json`)

The pipeline parses the Claude text output into this JSON structure for downstream steps:

```json
{
  "global": {
    "subtitle_style": "string",
    "bg_music": "string",
    "visual_style": "string"
  },
  "scenes": [
    {
      "scene": "string (e.g. '1', '3a', '3b')",
      "clip_type": "hard_cut | still_with_motion | animated",
      "duration_s": "number",
      "voiceover_line": "string",
      "visual_prompts": {
        "primary_stk": "string",
        "fallback_stk": "string",
        "ai_generate": "string"
      },
      "motion_effect": "zoom-in | zoom-out | pan-left | pan-right | ken-burns | null",
      "on_screen_text": "string | null",
      "sfx": "string (never null)",
      "sfx_timing": "string"
    }
  ],
  "summary": {
    "total_scenes": "integer",
    "total_duration_s": "number",
    "rhythm": "string (e.g. 'SM / HC / HC / AN / SM')"
  }
}
```

---

## Narration instruction (Gemini TTS) — v0.2

**Source:** `cf_platform/workers/voice_production.py` — `_STYLE_CLAUSE`, `_PACE_WPM`, `_PAUSE_INSTRUCTION`, composed by `_build_tts_input()`.

Gemini's native TTS models expose **no numeric speaking-rate parameter** (`SpeechConfig` carries only `language_code`, `voice_config`, `multi_speaker_voice_config`), so pace and delivery are steered entirely by a natural-language instruction prefixed to the script. The model follows it without vocalizing it.

The prefix is assembled as: **style clause + wpm target + pause instruction + script**.

| Part | Values |
|------|--------|
| Style clause | `educational` — "clear, confident explainer voiceover — measured and articulate, letting each fact land"<br>`emotional` — "warm, expressive storyteller voiceover — emotionally engaged, leaning into the moments that matter" |
| wpm target | `slow` 145 · `normal` 160 (default) · `fast` 172 |
| Pause instruction | Fixed. **Do not reword** — see below. |

Both selections come from `runs/{run_id}/settings.json` (`narration_pace`, `narration_style`), chosen on the Studio Settings stage.

### Changelog

| Version | Date | Change |
|---------|------|--------|
| v0.1 | 2026-08-26 | Single `_SHORTS_PACE_INSTRUCTION` constant, applied only when `aspect_ratio == "9:16"`, hardcoded to ~170–175 wpm (D073). |
| v0.3 | 2026-08-31 | Tempo split out of the register clause into `_PACE_MANNER`. The `educational` register said "measured and articulate, letting each fact land" — a slow-down instruction beside a speed-up one, which made fast+educational deliver **126 wpm against normal's 139**. Register now describes voice only, tempo only speed. `fast` 172 → **190 wpm**: measured output lands 13–30% below target and two runs at one setting differ by ~4%, so the old 7.5% gap was inside the noise. (D088) |
| v0.2 | 2026-08-30 | Split into operator-selectable pace (`_PACE_WPM`) and register (`_STYLE_CLAUSE`), composed with a now-constant `_PAUSE_INSTRUCTION`. Applied for **every** aspect ratio — 16:9 previously received no instruction at all. Default is `normal`/`educational`; **Fast reproduces the pre-v0.2 Shorts pace.** (D083) |

### The pause instruction is load-bearing — do not reword it

> "Take a brief, natural pause after each sentence and after each list item — do not run straight from one sentence or item into the next — but keep the delivery lively and energetic within each sentence, between the pauses:"

History (D073): earlier "energetically"/"brisk" wording made Gemini run sentences and list items together with no breathing room — duration *dropped* instead of the pace slowing. Removing that wording fixed the pauses but read as flat and slow (13s → 19s on the same script). The current wording puts the energy back explicitly but scopes it to *between* pauses. Every pace × style combination must still carry this clause verbatim; `tests/cf_platform/test_pux2_s4_narration.py` asserts it.

---

## Future prompts
_Add entries here as new AI prompt components are introduced._
