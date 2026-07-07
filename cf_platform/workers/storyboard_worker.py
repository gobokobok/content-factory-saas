"""StoryboardWorker (P9-S2) — Script → verified_storyboard artifact.

Internal generate→review→patch cycle. Single `verified_storyboard` artifact emitted.
No intermediate reviewer artifact surfaced externally.

Pipeline position (after P9-S5 wiring):
    voice_production → storyboard_worker → acquisition_worker → render_worker

Steps:
  1. Generate (Sonnet, prompt v0.12) — JSON output with segment_type, three-tier
     queries (primary_stk / context_stk / concept_stk), on_screen_text_type.
  2. Review (Haiku) — checks five quality dimensions; returns structured JSON patches.
  3. Patch (deterministic) — applies patches, then computes render_options per scene.
  4. Emit verified_storyboard artifact to R2 via the observability wrapper.
"""

import json
import logging
import math
import re
import string
from datetime import datetime, timezone
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
from src.models import (
    GlobalContext,
    LowerThirdSpec,
    OnScreenTextOverlay,
    SceneRenderOptions,
    SemanticContext,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
)

logger = logging.getLogger(__name__)

STORYBOARD_PROMPT_VERSION = "v0.17"

_SONNET_MODEL = "claude-sonnet-4-6"
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

STORYBOARD_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version=STORYBOARD_PROMPT_VERSION,
    prompt="",
    model=_SONNET_MODEL,
    sampling_params={"max_tokens": 32000},
)

# Format lines substituted into _GENERATE_SYSTEM_PROMPT per-run based on format_track.
_FORMAT_LINE_SENTINEL = "Format: 16:9 horizontal. Voiceover only. Stock footage + Wikimedia Commons."
_FORMAT_LINE_PORTRAIT = "Format: 9:16 vertical, 30–60 second YouTube Short. Voiceover only. Stock footage + Wikimedia Commons."
_FORMAT_LINE_LANDSCAPE = "Format: 16:9 horizontal, 30–180 second YouTube video. Voiceover only. Stock footage + Wikimedia Commons."

# Pacing lines — short-form Shorts need faster cuts than long-form video.
# Exact word budgets (computed from this script's measured speech rate) are injected
# per-request into the user message; these lines set the qualitative target in seconds.
_PACING_LINE_SENTINEL = "PACING_TARGET_PLACEHOLDER"
_PACING_LINE_PORTRAIT = (
    "PACING TARGET (short-form 9:16): body scenes 1.5–3 seconds, hard maximum 5 seconds.\n"
    "HOOK: the first ~4 seconds of narration must cut fast — target ~1 second per scene;\n"
    "sub-second scenes are expected and encouraged here to hook the viewer."
)
_PACING_LINE_LANDSCAPE = (
    "PACING TARGET (long-form 16:9): body scenes 3–6 seconds, hard maximum 8 seconds.\n"
    "HOOK: the first ~4 seconds of narration must still cut fast — target ~1–1.5 seconds per scene."
)

# Seconds-based targets used to derive per-request word budgets in _generate().
_HOOK_WINDOW_S = 4.0
_HOOK_TARGET_S = 1.0
_BODY_PACING_SECONDS: dict[str, tuple[float, float, float]] = {
    # format_track -> (target_lo_s, target_hi_s, hard_max_s)
    "portrait": (1.5, 3.0, 5.0),
    "landscape": (3.0, 6.0, 8.0),
}

_GENERATE_SYSTEM_PROMPT = """\
You are a production storyboard generator for a faceless, voiceover-driven YouTube channel.

Format: 16:9 horizontal. Voiceover only. Stock footage + Wikimedia Commons.

Your job: take a voiceover script and produce a full production storyboard.
Output ONLY a valid JSON object — no prose, no markdown fences, no extra keys.
Every word in the script must appear verbatim in exactly one scene's voiceover_line.

═══════════════════════════════════════
SEGMENT TYPE
═══════════════════════════════════════

Every scene has a segment_type. Use exactly one of:

"Character" — the voiceover names a specific real individual (scientist, politician,
  researcher, historical figure, athlete, celebrity). Use this even if the scene is
  about their work or study, OR references them only in passing, comparison, or
  hyperbole — the visual should be their portrait, not generic B-roll. A famous name
  dropped for effect ("you don't need Ronaldo's contract") still triggers Character;
  it does not need to be the scene's main subject.
  MUST set person_name and person_title.
  Acquisition: tries Wikipedia portrait first; falls back to Pexels+Pixabay on miss.

"Event" — the voiceover names a specific historical event, era, or landmark (e.g. London
  Blitz, Great Depression, Letchworth Garden City, postwar housing boom).
  Acquisition: searches Wikimedia Commons for archival imagery first.

"B-roll" — everything else: generic stock video/photo illustrating a concept.
  Acquisition: Pexels + Pixabay concurrent merge+rank.

Rules:
- Never assign "Character" without setting person_name.
- Never assign "Event" for abstract concepts (inflation, demand, equity) — use "B-roll".
- FIRST mention of a named real person — including a passing name-drop, comparison, or
  hyperbole, not just the scene's main subject — → MUST be "Character" with person_name
  set. This is their introduction scene; show their portrait. Resolve an ambiguous
  first name (e.g. "Ronaldo") to the most famous/contextually likely full name.
- SUBSEQUENT mentions of the same person → use "B-roll" with contextual queries about
  their work (e.g. the study, the concept they're associated with). Do not show the
  same portrait twice.
- Never assign "Character" to a scene that is a second or later reference to the same person.

Examples:
  First mention: VO: "Jerome Powell signalled rates would stay high"
    → segment_type: "Character", person_name: "Jerome Powell", person_title: "Chair, Federal Reserve"
  Second mention: VO: "Powell's decision sent mortgage rates to a 20-year high"
    → segment_type: "B-roll", primary_stk: "federal reserve interest rate mortgage"
  First mention: VO: "Kirk Erickson's 2011 study found aerobic exercise grew the hippocampus"
    → segment_type: "Character", person_name: "Kirk Erickson", person_title: "Neuroscientist, University of Pittsburgh"
  Name-drop/comparison (still Character): VO: "you don't need Ronaldo's contract or abs
  to make money off soccer"
    → segment_type: "Character", person_name: "Cristiano Ronaldo", person_title: "Professional Footballer"
  First mention: VO: "Cotman and Berchtold's 2002 review established this link directly"
    → segment_type: "Character", person_name: "Carl Cotman", person_title: "Neuroscientist, UC Irvine"
  The London Blitz destroyed four million homes"
    → segment_type: "Event"
  VO: "Homeownership rates dropped to 1960s lows"
    → segment_type: "B-roll"

═══════════════════════════════════════
THREE-TIER QUERIES
═══════════════════════════════════════

Every scene gets three search queries in priority cascade order.

1. primary_stk — Pexels+Pixabay search string
   - 3–4 concrete nouns only. No adjectives. No verbs. No era labels.
   - Topic-anchored: what B-roll would a documentary filmmaker cut to for THIS line in
     this video's topic domain? ("Repairs" in a housing video = house renovation, not tools.)
   - SEMANTIC RULE: query the CONCEPT being communicated, never the literal words spoken.
     VO "point zero three percent annual growth" → concept is tiny growth rate →
       primary_stk: "economy slow growth graph" NOT "pointing finger".
     VO "inflation eating savings" → concept is purchasing power erosion →
       primary_stk: "money value decline chart" NOT "eating food".
   - For Character: start with person's full name (e.g. "Jerome Powell Federal Reserve")
   - For Event: include the specific proper noun (e.g. "London Blitz 1940 ruins")

2. context_stk — broader Pexels+Pixabay fallback
   - 1–2 words. Core subject only. Broadest noun that still covers the scene.
   - For Character: person's surname only (e.g. "Powell")
   - For Event: event/place name only (e.g. "London Blitz")

3. concept_stk — most abstract fallback
   - Single noun. The most universal term for the scene's concept.
   - Examples: "housing", "interest", "economy", "city", "people", "government"

Example:
  VO: "Rents in major cities rose 30% in three years"
  primary_stk: "apartment building city rental"
  context_stk: "apartment"
  concept_stk: "housing"

═══════════════════════════════════════
ON_SCREEN_TEXT TYPE
═══════════════════════════════════════

on_screen_text_type MUST be exactly one of these four string literals (or null):
- "stat" — a data point, percentage, or number (e.g. "38% decline", "$450K median price")
- "date" — a year or date range (e.g. "1970–1990", "March 2022")
- "label" — a structural section title (e.g. "Habit 1: Aerobic Exercise", "Step 3: Recovery")
- "lower_third" — reserved; do NOT use this — the reviewer computes it for Character scenes

Any other string (e.g. "emphasis", "quote", "highlight") is INVALID and will cause a hard error.

Rules:
- When the voiceover_line introduces a numbered section, habit, step, or rule (e.g. "Habit 1", "Step 3", "Rule 2"), set on_screen_text to the full label (e.g. "Habit 1: Aerobic Exercise") and on_screen_text_type: "label". This is MANDATORY — never omit the label for a section-opener scene.
- When on_screen_text contains a stat or figure, set on_screen_text_type: "stat"
- When on_screen_text is a year or date, set on_screen_text_type: "date" — but NEVER use a bare year alone (e.g. "2011" is forbidden). Always pair with context: "2011: Hippocampus Study" or "2002 Nature Review"
- If the text does not fit "stat", "date", or "label", set both on_screen_text and on_screen_text_type to null
- When on_screen_text is null, on_screen_text_type must also be null

═══════════════════════════════════════
RENDER DECISION NOTE
═══════════════════════════════════════

Do NOT set render_options — that field is computed by the storyboard reviewer.
Your job is to set the raw scene fields accurately. The reviewer reads them and writes render_options.

═══════════════════════════════════════
GLOBAL CONTEXT — write this FIRST before any scenes
═══════════════════════════════════════

Before writing scenes, output a top-level "global_context" block that names the
video's knowledge domain and its most specific subtopics. This block guides asset
acquisition so generic words (e.g. "protein", "cell", "market") are never searched
in the wrong domain.

Fields:
- topic: 5–10 word plain-English summary of the full video subject
- domain: single word or short phrase (e.g. "neuroscience", "housing economics",
  "urban planning history", "personal finance")
- subtopics: 4–8 key technical concepts from the script (exact nouns, no verbs)
- avoid_globally: 3–6 terms that stock-photo engines commonly associate with words in
  this script BUT are wrong for this domain. These are added as exclusion signals.
- tone: one of "evidence-based documentary" | "educational explainer" | "investigative"

Examples:
  Neuroscience script about exercise and brain health →
    topic: "How exercise improves brain health and memory",
    domain: "neuroscience",
    subtopics: ["neurons", "BDNF", "hippocampus", "synaptic plasticity", "cortisol", "memory"],
    avoid_globally: ["food preparation", "cooking", "dietary supplements", "gym selfie"],
    tone: "evidence-based documentary"

  Housing economics script about rent crisis →
    topic: "Why US rents tripled in a decade",
    domain: "housing economics",
    subtopics: ["rent burden", "supply shortage", "zoning", "median income", "vacancy rate"],
    avoid_globally: ["luxury interior design", "home decor", "real estate agent smiling"],
    tone: "investigative"

═══════════════════════════════════════
SEMANTIC CONTEXT — one block per scene
═══════════════════════════════════════

Every scene must include a "semantic_context" block. This enriches the three-tier
STK queries with domain-aware signals so stock engines return conceptually correct
results even when VO words are ambiguous.

Fields:
- primary_concept: 3–8 word plain-English label for the visual concept (not the VO words)
- domain_qualifier: how this concept relates to the video domain — prevents wrong-domain
  results when the concept word is ambiguous. Keep to 4–10 words.
- avoid: 2–5 specific stock-photo categories to exclude for THIS scene
- visual_tags: 3–5 search terms in priority order, from most specific to broadest.
  These are used as alternative queries if primary_stk misses. Must NOT overlap with
  the avoid list. Concrete nouns only.
- entity_type: "person" | "historic_event" | "location" | "organization" | null
  Use "person" for Character scenes; "historic_event" for Event scenes depicting
  a named event; "location" for place-centric scenes; "organization" for
  institution-centric scenes; null for generic B-roll.

Domain-qualifier examples (key pattern — always resolve the ambiguity):
  Script mentions "protein" in a neuroscience video →
    primary_concept: "neuronal protein synthesis",
    domain_qualifier: "neurological protein, not dietary",
    avoid: ["food", "cooking", "protein powder", "fried eggs"],
    visual_tags: ["neuron microscopy", "brain cell protein", "synaptic growth", "BDNF molecule"]

  Script mentions "market" in a housing video →
    primary_concept: "housing market supply and demand",
    domain_qualifier: "real estate market, not stock market or food market",
    avoid: ["stock ticker", "Wall Street", "produce market", "supermarket"],
    visual_tags: ["real estate graph", "house price chart", "housing supply shortage", "rental vacancy"]

  Script mentions "cell" in a biology video →
    primary_concept: "biological cell under microscope",
    domain_qualifier: "biological cell, not prison cell or phone cell",
    avoid: ["prison cell", "mobile phone", "battery cell"],
    visual_tags: ["microscope cell biology", "cell membrane", "neuron dendrite", "tissue stain"]

═══════════════════════════════════════
DURATION RULES
═══════════════════════════════════════

Duration is derived from the word count of voiceover_line, never from clip type ceiling.

| Words in VO line      | Duration     |
|-----------------------|--------------|
| List item, 1 word     | 0.3–0.4s     |
| List item, 2–3 words  | 0.5–0.7s     |
| List item, 3–4 words  | 0.8–1.0s     |
| Non-list, 4–6 words   | 1.0–1.5s     |
| Non-list, 7–10 words  | 2.0–2.5s     |
| Non-list, 11–14 words | 3.0–3.5s     |
| 15+ words             | Split into two scenes |

- Non-list scene minimum: 1.0s. List item minimum: 0.7s (except single-word items).
- HARD MAXIMUM: still_with_motion scenes must not exceed 5.0s. Video (hard_cut/animated)
  scenes must not exceed 10.0s. If the voiceover line would push a still past 5.0s, split
  it into two scenes at the nearest clause boundary.

If WORD TIMESTAMPS are provided, use them authoritatively:
  duration_s = (end_ms of last VO word − start_ms of first VO word) / 1000 + up to 0.3s tail
  Never use the word-count table when timestamps are present.
  If a timestamp-derived duration would exceed the hard maximum above, split the scene.

═══════════════════════════════════════
CLIP TYPE RULES
═══════════════════════════════════════

- hard_cut: emphasis, shock, list items. motion_effect: null.
- still_with_motion: single frame + movement. motion_effect is mandatory:
  one of ken_burns_in | ken_burns_out | pan_left | pan_right.
- animated: concept requires change or sequence. motion_effect: null.

COMMA-LIST RULE: each list item → its own hard_cut scene, labelled 03a / 03b / 03c.
Bridge phrases ("Others enjoy activities like") belong to the first item's voiceover_line.

═══════════════════════════════════════
COVERAGE RULE — CRITICAL
═══════════════════════════════════════

Every word in the input script must appear verbatim in exactly one scene's voiceover_line.
After writing all scenes, verify: read the script left to right — each word maps to exactly
one voiceover_line.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

Output ONLY the JSON object below. No prose. No markdown fences. No extra keys.

{
  "global_context": {
    "topic": "...",
    "domain": "...",
    "subtopics": ["...", "..."],
    "avoid_globally": ["...", "..."],
    "tone": "evidence-based documentary"
  },
  "global": {
    "subtitle_style": "...",
    "bg_music": "...",
    "visual_style": "..."
  },
  "scenes": [
    {
      "scene": "1",
      "clip_type": "still_with_motion",
      "duration_s": 2.5,
      "voiceover_line": "...",
      "segment_type": "B-roll",
      "primary_stk": "house exterior repair workers",
      "context_stk": "house renovation",
      "concept_stk": "housing",
      "semantic_context": {
        "primary_concept": "residential construction and renovation",
        "domain_qualifier": "housing maintenance, not tool or hardware store",
        "avoid": ["tool shop", "hardware store", "workshop interior"],
        "visual_tags": ["house renovation exterior", "construction workers housing", "residential repair"],
        "entity_type": null
      },
      "on_screen_text": null,
      "on_screen_text_type": null,
      "motion_effect": "ken_burns_in",
      "sfx": "ambient street traffic",
      "sfx_timing": "on cut",
      "person_name": null,
      "person_title": null
    },
    {
      "scene": "2",
      "clip_type": "still_with_motion",
      "duration_s": 2.5,
      "voiceover_line": "...",
      "segment_type": "Character",
      "primary_stk": "Jerome Powell Federal Reserve",
      "context_stk": "Powell",
      "concept_stk": "central bank",
      "semantic_context": {
        "primary_concept": "Federal Reserve chair Jerome Powell",
        "domain_qualifier": "US monetary policy, not generic finance",
        "avoid": ["generic banker", "stock market floor"],
        "visual_tags": ["Jerome Powell portrait", "Federal Reserve"],
        "entity_type": "person"
      },
      "on_screen_text": null,
      "on_screen_text_type": null,
      "motion_effect": "ken_burns_in",
      "sfx": "silence",
      "sfx_timing": "on cut",
      "person_name": "Jerome Powell",
      "person_title": "Chair, Federal Reserve"
    }
  ],
  "summary": {
    "total_scenes": 15,
    "total_duration_s": 32.5,
    "rhythm": "SM / HC / HC / AN / SM"
  }
}
"""

_GENERATE_SYSTEM_PROMPT_V013 = """\
You are a production storyboard generator for a faceless, voiceover-driven YouTube channel.

Format: 16:9 horizontal. Voiceover only. Stock footage + Wikimedia Commons.

PACING_TARGET_PLACEHOLDER

Your job: divide the indexed voiceover word list into scenes. For each scene, output
start_word and end_word integer indices (inclusive) and the visual/audio metadata.
Output ONLY a valid JSON object — no prose, no markdown fences, no extra keys.

═══════════════════════════════════════
INDEXED WORD LIST — HOW TO USE
═══════════════════════════════════════

The voiceover words are provided as a numbered list. Punctuation is preserved —
a period, question mark, or exclamation mark on a word marks the end of a sentence.
For each scene set start_word and end_word to integer indices from this list.

Rules:
- Follow the PACING TARGET above and the exact word budget given in the user
  message (computed from this script's measured speech rate) — count words per
  scene and stay within the hook/body targets given there.
- SENTENCE BOUNDARIES FIRST: strongly prefer ending a scene on a word that carries
  sentence-final punctuation (. ? !). Split inside a sentence ONLY when the whole
  sentence would exceed the budget — and then split at a clause boundary
  (comma, semicolon, "and", "but", "because", "so", "which", or a list item).
- NEVER end a scene mid-thought. A noun must never be separated from its adjective
  or ordinal ("the third | generation" is forbidden — keep "the third generation"
  together in one scene).
- LIST ITEMS GET THEIR OWN SCENE: when the voiceover enumerates items — "first...
  second... third", a comma-separated series of nouns/phrases, or numbered items
  ("way 1", "reason two") — give EACH item its own scene, even if under 1 second
  long. The intro/bridge phrase before the list is its own scene, never merged
  into the first item. Rapid list cuts are intentional — do not merge list items
  together to hit a target duration; going below the body word budget is correct
  here.
  Example: VO "here are three ways to cash in dropshipping affiliate marketing
  and print on demand" → 4 scenes: "here are three ways to cash in" (intro),
  "dropshipping", "affiliate marketing", "and print on demand".
- SECTION OPENERS START NEW SCENES: when the voiceover introduces a numbered section
  ("lesson one", "step 3", "rule two", "habit 4"), that phrase MUST be the FIRST
  words of a new scene — never the tail of the previous scene. Set that scene's
  on_screen_text to the full label.
- Scenes must be contiguous: scene[i].end_word + 1 == scene[i+1].start_word.
- The first scene's start_word must be 0.
- The last scene's end_word must equal (total words − 1).
- Do NOT overlap: each word index must appear in exactly one scene.

═══════════════════════════════════════
SEGMENT TYPE
═══════════════════════════════════════

Every scene has a segment_type. Use exactly one of:

"Character" — the voiceover names a specific real individual (scientist, politician,
  researcher, historical figure, athlete, celebrity). Use this even if the scene is
  about their work or study, OR references them only in passing, comparison, or
  hyperbole — the visual should be their portrait, not generic B-roll. A famous name
  dropped for effect ("you don't need Ronaldo's contract") still triggers Character;
  it does not need to be the scene's main subject.
  MUST set person_name and person_title.
  Acquisition: tries Wikipedia portrait first; falls back to Pexels+Pixabay on miss.

"Event" — the voiceover names a specific historical event, era, or landmark (e.g. London
  Blitz, Great Depression, Letchworth Garden City, postwar housing boom).
  Acquisition: searches Wikimedia Commons for archival imagery first.

"B-roll" — everything else: generic stock video/photo illustrating a concept.
  Acquisition: Pexels + Pixabay concurrent merge+rank.

Rules:
- Never assign "Character" without setting person_name.
- Never assign "Event" for abstract concepts (inflation, demand, equity) — use "B-roll".
- FIRST mention of a named real person — including a passing name-drop, comparison, or
  hyperbole, not just the scene's main subject — → MUST be "Character" with person_name
  set. This is their introduction scene; show their portrait. Resolve an ambiguous
  first name (e.g. "Ronaldo") to the most famous/contextually likely full name.
- SUBSEQUENT mentions of the same person → use "B-roll" with contextual queries about
  their work (e.g. the study, the concept they're associated with). Do not show the
  same portrait twice.
- Never assign "Character" to a scene that is a second or later reference to the same person.

Examples:
  First mention: VO: "Jerome Powell signalled rates would stay high"
    → segment_type: "Character", person_name: "Jerome Powell", person_title: "Chair, Federal Reserve"
  Second mention: VO: "Powell's decision sent mortgage rates to a 20-year high"
    → segment_type: "B-roll", primary_stk: "federal reserve interest rate mortgage"
  First mention: VO: "Kirk Erickson's 2011 study found aerobic exercise grew the hippocampus"
    → segment_type: "Character", person_name: "Kirk Erickson", person_title: "Neuroscientist, University of Pittsburgh"
  Name-drop/comparison (still Character): VO: "you don't need Ronaldo's contract or abs
  to make money off soccer"
    → segment_type: "Character", person_name: "Cristiano Ronaldo", person_title: "Professional Footballer"
  First mention: VO: "Cotman and Berchtold's 2002 review established this link directly"
    → segment_type: "Character", person_name: "Carl Cotman", person_title: "Neuroscientist, UC Irvine"
  The London Blitz destroyed four million homes"
    → segment_type: "Event"
  VO: "Homeownership rates dropped to 1960s lows"
    → segment_type: "B-roll"

═══════════════════════════════════════
THREE-TIER QUERIES
═══════════════════════════════════════

Every scene gets three search queries in priority cascade order.

1. primary_stk — Pexels+Pixabay search string
   - 3–4 concrete nouns only. No adjectives. No verbs. No era labels.
   - Topic-anchored: what B-roll would a documentary filmmaker cut to for THIS line in
     this video's topic domain? ("Repairs" in a housing video = house renovation, not tools.)
   - SEMANTIC RULE: query the CONCEPT being communicated, never the literal words spoken.
     VO "point zero three percent annual growth" → concept is tiny growth rate →
       primary_stk: "economy slow growth graph" NOT "pointing finger".
     VO "inflation eating savings" → concept is purchasing power erosion →
       primary_stk: "money value decline chart" NOT "eating food".
   - For Character: start with person's full name (e.g. "Jerome Powell Federal Reserve")
   - For Event: include the specific proper noun (e.g. "London Blitz 1940 ruins")

2. context_stk — broader Pexels+Pixabay fallback
   - 1–2 words. Core subject only. Broadest noun that still covers the scene.
   - For Character: person's surname only (e.g. "Powell")
   - For Event: event/place name only (e.g. "London Blitz")

3. concept_stk — most abstract fallback
   - Single noun. The most universal term for the scene's concept.
   - Examples: "housing", "interest", "economy", "city", "people", "government"

Example:
  Scene words [12]–[19]: "Rents in major cities rose 30 percent in three years"
  primary_stk: "apartment building city rental"
  context_stk: "apartment"
  concept_stk: "housing"

═══════════════════════════════════════
ON_SCREEN_TEXT TYPE
═══════════════════════════════════════

on_screen_text_type MUST be exactly one of these four string literals (or null):
- "stat" — a data point, percentage, or number (e.g. "38% decline", "$450K median price")
- "date" — a year or date range (e.g. "1970–1990", "March 2022")
- "label" — a structural section title (e.g. "Habit 1: Aerobic Exercise", "Step 3: Recovery")
- "lower_third" — reserved; do NOT use this — the reviewer computes it for Character scenes

Any other string (e.g. "emphasis", "quote", "highlight") is INVALID and will cause a hard error.

Rules:
- When the voiceover_line introduces a numbered section, habit, step, or rule (e.g. "Habit 1", "Step 3", "Rule 2"), set on_screen_text to the full label (e.g. "Habit 1: Aerobic Exercise") and on_screen_text_type: "label". This is MANDATORY — never omit the label for a section-opener scene.
- When on_screen_text contains a stat or figure, set on_screen_text_type: "stat"
- When on_screen_text is a year or date, set on_screen_text_type: "date" — but NEVER use a bare year alone (e.g. "2011" is forbidden). Always pair with context: "2011: Hippocampus Study" or "2002 Nature Review"
- If the text does not fit "stat", "date", or "label", set both on_screen_text and on_screen_text_type to null
- When on_screen_text is null, on_screen_text_type must also be null

═══════════════════════════════════════
RENDER DECISION NOTE
═══════════════════════════════════════

Do NOT set render_options — that field is computed by the storyboard reviewer.
Your job is to set the raw scene fields accurately. The reviewer reads them and writes render_options.

═══════════════════════════════════════
GLOBAL CONTEXT — write this FIRST before any scenes
═══════════════════════════════════════

Before writing scenes, output a top-level "global_context" block that names the
video's knowledge domain and its most specific subtopics. This block guides asset
acquisition so generic words (e.g. "protein", "cell", "market") are never searched
in the wrong domain.

Fields:
- topic: 5–10 word plain-English summary of the full video subject
- domain: single word or short phrase (e.g. "neuroscience", "housing economics",
  "urban planning history", "personal finance")
- subtopics: 4–8 key technical concepts from the script (exact nouns, no verbs)
- avoid_globally: 3–6 terms that stock-photo engines commonly associate with words in
  this script BUT are wrong for this domain. These are added as exclusion signals.
- tone: one of "evidence-based documentary" | "educational explainer" | "investigative"

═══════════════════════════════════════
SEMANTIC CONTEXT — one block per scene
═══════════════════════════════════════

Every scene must include a "semantic_context" block with:
- primary_concept: 3–8 word plain-English label for the visual concept (not the VO words)
- domain_qualifier: how this concept relates to the video domain — prevents wrong-domain
  results when the concept word is ambiguous. Keep to 4–10 words.
- avoid: 2–5 specific stock-photo categories to exclude for THIS scene
- visual_tags: 3–5 search terms in priority order, most specific to broadest.
  Concrete nouns only. Must NOT overlap with avoid list.
- entity_type: "person" | "historic_event" | "location" | "organization" | null

Domain-qualifier example: "protein" in neuroscience →
  domain_qualifier: "neurological protein, not dietary",
  avoid: ["food", "cooking", "protein powder"],
  visual_tags: ["neuron microscopy", "synaptic protein", "brain cell growth"]

═══════════════════════════════════════
COVERAGE RULE — CRITICAL
═══════════════════════════════════════

Every word index in the list must be covered by exactly one scene.
Constraints:
- First scene: start_word = 0
- Last scene: end_word = (total word count − 1)
- No gaps: scene[i].end_word + 1 == scene[i+1].start_word for all adjacent scenes
- No overlaps: each index appears in exactly one scene

After writing all scenes, verify: first.start_word=0, last.end_word=N-1, all contiguous.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

Output ONLY the JSON object below. No prose. No markdown fences. No extra keys.

{
  "global_context": {
    "topic": "...",
    "domain": "...",
    "subtopics": ["...", "..."],
    "avoid_globally": ["...", "..."],
    "tone": "evidence-based documentary"
  },
  "global": {
    "subtitle_style": "...",
    "bg_music": "...",
    "visual_style": "..."
  },
  "scenes": [
    {
      "scene": "1",
      "start_word": 0,
      "end_word": 12,
      "segment_type": "B-roll",
      "primary_stk": "house exterior repair workers",
      "context_stk": "house renovation",
      "concept_stk": "housing",
      "semantic_context": {
        "primary_concept": "residential construction and renovation",
        "domain_qualifier": "housing maintenance, not tool or hardware store",
        "avoid": ["tool shop", "hardware store", "workshop interior"],
        "visual_tags": ["house renovation exterior", "construction workers housing", "residential repair"],
        "entity_type": null
      },
      "on_screen_text": null,
      "on_screen_text_type": null,
      "sfx": "ambient street traffic",
      "sfx_timing": "on cut",
      "person_name": null,
      "person_title": null
    },
    {
      "scene": "2",
      "start_word": 13,
      "end_word": 22,
      "segment_type": "Character",
      "primary_stk": "Jerome Powell Federal Reserve",
      "context_stk": "Powell",
      "concept_stk": "central bank",
      "semantic_context": {
        "primary_concept": "Federal Reserve chair Jerome Powell",
        "domain_qualifier": "US monetary policy, not generic finance",
        "avoid": ["generic banker", "stock market floor"],
        "visual_tags": ["Jerome Powell portrait", "Federal Reserve"],
        "entity_type": "person"
      },
      "on_screen_text": null,
      "on_screen_text_type": null,
      "sfx": "silence",
      "sfx_timing": "on cut",
      "person_name": "Jerome Powell",
      "person_title": "Chair, Federal Reserve"
    }
  ],
  "summary": {
    "total_scenes": 15,
    "total_duration_s": 0,
    "rhythm": "derived"
  }
}
"""

_REVIEW_SYSTEM_PROMPT = """\
You are a storyboard quality reviewer. Given a JSON storyboard and the original script,
check five quality dimensions and return a structured JSON patch list.

Review dimensions:
a. Coverage: every word from the original script must appear verbatim in exactly one
   scene's voiceover_line. Flag missing or duplicated words.
b. segment_type correctness: named real person → must be "Character" (and person_name set);
   named specific historical event/era/landmark → must be "Event"; everything else → "B-roll".
   Correct misclassifications.
c. on_screen_text gaps: if voiceover_line contains a prominent stat (percentage, dollar figure)
   or year/date that would be compelling on-screen but on_screen_text is null, suggest adding
   it. Only suggest when the stat/date is the core point of the scene — not every number.
d. Query domain anchoring: primary_stk should reflect the video topic domain, not literal VO
   words. Flag when queries contain era labels (Victorian, 1880s, medieval) or drift off-topic.
   Suggest a topic-anchored replacement.
e. SFX specificity: sfx must be a concrete, specific noun phrase (e.g. "pen scratching paper",
   "crowd applause in conference room"). Flag vague values like "sound", "noise", "ambient".
   Suggest a specific replacement.

Output ONLY valid JSON. No prose. No markdown fences.

{
  "coverage_ok": true,
  "patches": [
    {"scene_id": "3", "field": "segment_type", "value": "Character"},
    {"scene_id": "3", "field": "person_name", "value": "Jerome Powell"},
    {"scene_id": "5", "field": "sfx", "value": "crowd applause in conference hall"}
  ],
  "issues": [
    "Scene 3: Jerome Powell named in VO but segment_type was B-roll"
  ]
}

Rules:
- Only include patches for genuine problems. An empty patches list is valid and encouraged.
- patches[].field must be one of: segment_type, person_name, person_title, primary_stk,
  context_stk, concept_stk, on_screen_text, on_screen_text_type, sfx, sfx_timing
- Do NOT patch render_options — that is computed after your review.
- coverage_ok is true only when every script word appears in exactly one voiceover_line.
- Limit patches to the most impactful corrections. Do not over-patch.
"""


# ── Artifact schema ───────────────────────────────────────────────────────────


class VerifiedStoryboardArtifact(BaseModel):
    """Terminal artifact of the StoryboardWorker.

    storyboard is the full Storyboard model serialised to a dict with render_options
    populated on every scene. Callers deserialise via Storyboard.model_validate(artifact.storyboard).
    """

    prompt_version: str
    scene_count: int
    storyboard: dict  # Storyboard.model_dump(by_alias=True, mode="json")
    generated_at: datetime


# ── Helper functions ──────────────────────────────────────────────────────────


def _format_voice_timestamps(words: list[VoiceWordTimestamp]) -> str:
    """Format word timestamps as a compact block for the v0.12 fallback prompt."""
    return "\n".join(f'[{w.start_ms}ms–{w.end_ms}ms] "{w.word}"' for w in words)


_TERMINAL_PUNCT = '.,!?;:"""'

def _normalize_deepgram_words_with_display(
    raw: list[dict],
) -> tuple[list[VoiceWordTimestamp], list[str]]:
    """Normalise Deepgram word list and keep punctuated display forms in parallel.

    Strips terminal punctuation (period, comma, etc.) from the canonical word but
    preserves apostrophes so contraction tokens like "'s" remain intact when merged.
    Contiguous tokens with identical start_ms (Deepgram contraction splits) are
    merged into one word. The returned display list holds the ORIGINAL punctuated
    text at the same indices — used in the generate prompt so Claude can see
    sentence boundaries when choosing scene breaks.

    Returns (normalized_words, display_words), both 0-indexed and same length.
    """
    stripped: list[dict] = []
    for item in raw:
        word = item.get("word", "")
        clean = word.strip(_TERMINAL_PUNCT)
        if not clean:
            clean = word  # keep as-is when stripping empties the token (e.g. "—")
        stripped.append({
            "word": clean,
            "display": word,
            "start_ms": int(item.get("start_ms", 0)),
            "end_ms": int(item.get("end_ms", 0)),
            "confidence": float(item.get("confidence", 1.0)),
        })

    collapsed: list[dict] = []
    for item in stripped:
        if collapsed and collapsed[-1]["start_ms"] == item["start_ms"]:
            prev = collapsed[-1]
            collapsed[-1] = {
                "word": prev["word"] + item["word"],
                "display": prev["display"] + item["display"],
                "start_ms": prev["start_ms"],
                "end_ms": max(prev["end_ms"], item["end_ms"]),
                "confidence": min(prev["confidence"], item["confidence"]),
            }
        else:
            collapsed.append(item)

    display = [item.pop("display") for item in collapsed]
    return [VoiceWordTimestamp(**item) for item in collapsed], display


def _normalize_deepgram_words(raw: list[dict]) -> list[VoiceWordTimestamp]:
    """Normalise Deepgram word list (see _normalize_deepgram_words_with_display)."""
    return _normalize_deepgram_words_with_display(raw)[0]


_WORD_LIST_MAX_ENTRIES = 350


def _format_indexed_timestamps(
    words: list[VoiceWordTimestamp],
    display: Optional[list[str]] = None,
) -> str:
    """Format indexed word list for the v0.13 generate prompt.

    Displays the punctuated token (display list) so Claude can see sentence
    boundaries when choosing scene breaks. For ≤350 words, per-word timestamps
    are included; for larger scripts they are dropped (Python owns timing via
    _reify_scene) and scene length is governed by the word budget in the
    user message instead.
    """
    n = len(words)
    tokens = display if display is not None and len(display) == n else [w.word for w in words]
    if n <= _WORD_LIST_MAX_ENTRIES:
        return "\n".join(
            f'[{idx}]  "{tok}"    ({w.start_ms / 1000:.2f}s–{w.end_ms / 1000:.2f}s)'
            for idx, (w, tok) in enumerate(zip(words, tokens))
        )
    return "\n".join(f'[{idx}]  "{tok}"' for idx, tok in enumerate(tokens))


def _assign_asset_tier(duration_s: float) -> Literal["still", "still_motion", "video"]:
    """Assign asset tier from scene duration (P9-S9 policy).

    < 3.0s   → still        (single frame + scale motion)
    3.0–6.0s → still_motion (single frame + ken_burns motion)
    ≥ 6.0s   → video        (motion footage; ≥ 10s logs WARNING)
    """
    if duration_s < 3.0:
        return "still"
    elif duration_s < 6.0:
        return "still_motion"
    else:
        return "video"


def _asset_tier_to_clip_type(tier: str) -> Literal["hard_cut", "still_with_motion"]:
    """Derive clip_type from asset tier for backward compatibility with the render worker."""
    if tier == "video":
        return "hard_cut"
    return "still_with_motion"


def _derive_motion_effect(tier: str, scene_index: int) -> Optional[str]:
    """Derive motion_effect deterministically from asset_tier and scene index.

    still        → scale
    still_motion → ken_burns_in (even index) / ken_burns_out (odd index)
    video        → None
    """
    if tier == "still":
        return "scale"
    elif tier == "still_motion":
        return "ken_burns_in" if scene_index % 2 == 0 else "ken_burns_out"
    return None


def _reify_scene(raw: dict, words: list[VoiceWordTimestamp], scene_index: int) -> dict:
    """Reconstruct Python-owned fields from a Deepgram word span (P9-S9).

    Reads start_word/end_word from raw, extracts the matching word span, then
    fills voiceover_line, duration_s, scene_start_ms, scene_end_ms, asset_tier,
    clip_type, and motion_effect. Mutates raw in-place and returns it.
    """
    n = len(words)
    start = max(0, min(int(raw.get("start_word", 0)), n - 1))
    end = max(start, min(int(raw.get("end_word", start)), n - 1))

    span = words[start : end + 1]
    if span:
        raw["voiceover_line"] = " ".join(w.word for w in span)
        raw["scene_start_ms"] = span[0].start_ms
        raw["scene_end_ms"] = span[-1].end_ms
        raw["duration_s"] = round((span[-1].end_ms - span[0].start_ms) / 1000, 3)
    else:
        raw["voiceover_line"] = ""
        raw["scene_start_ms"] = 0
        raw["scene_end_ms"] = 0
        raw["duration_s"] = 0.0

    if raw["duration_s"] >= 7.0:
        logger.warning(
            "Scene %s has duration %.1fs ≥ 7s — will be split downstream if over %ss",
            raw.get("scene", "?"), raw["duration_s"], _MAX_SCENE_DURATION_S,
        )

    tier = _assign_asset_tier(raw["duration_s"])
    # Character scenes always use a portrait photo — cap at still_motion regardless of
    # duration so acquisition never searches for video clips of a named person.
    if raw.get("segment_type") == "Character":
        tier = "still_motion"
    raw["asset_tier"] = tier
    raw["clip_type"] = _asset_tier_to_clip_type(tier)
    raw["motion_effect"] = _derive_motion_effect(tier, scene_index)
    return raw


_MAX_SCENE_DURATION_S = 10.0

# Python-level hard backstop per format — tighter than the prompt's own target so a
# format_track="portrait" run never ends up with 8-10s scenes if Claude ignores pacing.
_MAX_SCENE_DURATION_BY_FORMAT: dict[str, float] = {
    "portrait": 6.0,
    "landscape": 10.0,
}

_DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
}


def _ost_overlap_score(ost_text: str, vo_line: str) -> int:
    """Count content-token overlap between on-screen text and a VO line.

    Digits are mapped to number words ("1" → "one") so labels like "Lesson 1"
    match spoken VO like "lesson one".
    """
    def tokens(s: str) -> set[str]:
        raw = re.findall(r"[a-z0-9']+", s.lower())
        mapped = {_DIGIT_WORDS.get(t, t) for t in raw}
        return {t for t in mapped if len(t) >= 3}
    return len(tokens(ost_text) & tokens(vo_line))


def _find_pause_split(
    words: list[VoiceWordTimestamp],
    ideal_end: int,
    range_start: int,
    range_end: int,
) -> int:
    """Return the word index within [range_start, range_end] that has the longest
    gap to the next word — a natural speech pause, preferring clause/sentence breaks.
    Falls back to ideal_end if no better candidate found.
    """
    best_idx = ideal_end
    best_gap = -1
    for i in range(max(range_start, 0), min(range_end, len(words) - 2) + 1):
        gap = words[i + 1].start_ms - words[i].end_ms
        if gap > best_gap:
            best_gap = gap
            best_idx = i
    return best_idx


def _split_long_scenes(
    storyboard: "Storyboard",
    words: list[VoiceWordTimestamp],
    max_s: float = _MAX_SCENE_DURATION_S,
) -> "Storyboard":
    """Split any scene whose VO span exceeds max_s into sub-scenes.

    Split points are chosen at the largest speech pause near each ideal
    equal-duration boundary, preferring natural clause breaks over mechanical
    midpoints. Visual metadata is copied to every sub-scene; the parent's
    on_screen_text is re-attached to the sub-scene whose VO best matches it.
    """
    result: list = []
    for scene in storyboard.scenes:
        if (
            scene.duration_s <= max_s
            or scene.start_word is None
            or scene.end_word is None
            or scene.start_word >= scene.end_word
        ):
            result.append(scene)
            continue

        n_splits = math.ceil(scene.duration_s / max_s)
        total_words = scene.end_word - scene.start_word + 1
        words_per_split = math.ceil(total_words / n_splits)
        search_radius = max(2, words_per_split // 4)

        base = scene.model_dump(by_alias=True, mode="json")
        logger.info(
            "StoryboardWorker: splitting scene %s (%.1fs) into %d sub-scenes",
            scene.scene, scene.duration_s, n_splits,
        )

        # Build split boundaries using pause-detection
        boundaries: list[int] = []  # end indices for each sub-scene except the last
        current_start = scene.start_word
        for j in range(n_splits - 1):
            ideal_end = current_start + words_per_split - 1
            split_end = _find_pause_split(
                words,
                ideal_end=min(ideal_end, scene.end_word - 1),
                range_start=max(current_start, ideal_end - search_radius),
                range_end=min(scene.end_word - 1, ideal_end + search_radius),
            )
            boundaries.append(split_end)
            current_start = split_end + 1
        boundaries.append(scene.end_word)

        sub_starts = [scene.start_word] + [b + 1 for b in boundaries[:-1]]
        subs: list[dict] = []
        for j, (sub_start, sub_end) in enumerate(zip(sub_starts, boundaries)):
            sub = dict(base)
            sub["start_word"] = sub_start
            sub["end_word"] = sub_end
            sub["on_screen_text"] = None
            sub["on_screen_text_type"] = None
            if sub.get("render_options") and isinstance(sub["render_options"], dict):
                sub["render_options"] = dict(sub["render_options"])
                sub["render_options"]["on_screen_text_overlay"] = None
            if j > 0:
                sub["scene"] = f"{scene.scene}_p{j + 1}"

            # Clear reified fields so _reify_scene starts fresh
            for field in ("voiceover_line", "duration_s", "scene_start_ms", "scene_end_ms",
                          "asset_tier", "clip_type", "motion_effect"):
                sub.pop(field, None)

            _reify_scene(sub, words, len(result) + j)
            subs.append(sub)

        # Re-attach the parent's on_screen_text to the sub-scene whose VO actually
        # contains it (token overlap; digits matched against number words). Falls
        # back to the first sub-scene when nothing matches.
        if scene.on_screen_text:
            scores = [
                _ost_overlap_score(scene.on_screen_text, sub.get("voiceover_line", ""))
                for sub in subs
            ]
            best = max(range(len(subs)), key=lambda k: scores[k])
            subs[best]["on_screen_text"] = scene.on_screen_text
            subs[best]["on_screen_text_type"] = scene.on_screen_text_type

        for sub in subs:
            result.append(StoryboardScene.model_validate(sub))

    total_dur = sum(s.duration_s for s in result)
    clip_abbrs = {"hard_cut": "HC", "still_with_motion": "SM", "animated": "AN"}
    rhythm_parts = [clip_abbrs.get(s.clip_type, "?") for s in result[:8]]
    rhythm = " / ".join(rhythm_parts) + (" …" if len(result) > 8 else "")
    new_summary = storyboard.summary.model_copy(update={
        "total_scenes": len(result),
        "total_duration_s": round(total_dur, 3),
        "rhythm": rhythm,
    })
    return storyboard.model_copy(update={"scenes": result, "summary": new_summary})


def _extract_json_object(text: str) -> dict:
    """Extract and parse a JSON object from a Claude response, stripping markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _parse_review_response(text: str) -> tuple[list[dict], bool, list[str]]:
    """Parse Haiku's review JSON. Returns (patches, coverage_ok, issues).

    Gracefully returns ([], True, []) on any parse failure so a bad review
    response never blocks the pipeline.
    """
    try:
        data = _extract_json_object(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("StoryboardWorker: could not parse review response — skipping patches")
        return [], True, []
    patches = [p for p in data.get("patches", []) if isinstance(p, dict)]
    coverage_ok = bool(data.get("coverage_ok", True))
    issues = [str(i) for i in data.get("issues", [])]
    return patches, coverage_ok, issues


def _apply_patches_and_render_options(
    storyboard: Storyboard,
    patches: list[dict],
) -> Storyboard:
    """Apply review patches then compute render_options for every scene.

    Patch step (deterministic):
    1. Apply field-level patches from the review.
    2. For each scene, compute render_options based on segment_type / on_screen_text:
       - Character + person_name → lower_third overlay; on_screen_text nulled out
       - Event → film_look = True
       - on_screen_text present (stat/date) → on_screen_text_overlay with enable_expr
         computed from cumulative scene duration offsets
    3. lower_third always carries caption_y_override=1540 so subtitles shift up.
    """
    # Index scenes by ID for O(1) patch application
    scenes_by_id: dict[str, StoryboardScene] = {s.scene: s for s in storyboard.scenes}
    original_order = [s.scene for s in storyboard.scenes]

    _PATCHABLE_FIELDS = {
        "segment_type", "person_name", "person_title",
        "primary_stk", "context_stk", "concept_stk",
        "on_screen_text", "on_screen_text_type", "sfx", "sfx_timing",
    }

    for patch in patches:
        scene_id = str(patch.get("scene_id", ""))
        field = str(patch.get("field", ""))
        value = patch.get("value")
        if scene_id not in scenes_by_id or field not in _PATCHABLE_FIELDS:
            continue
        scenes_by_id[scene_id] = scenes_by_id[scene_id].model_copy(update={field: value})

    # Compute render_options using cumulative scene start times
    cumulative_t = 0.0
    patched_scenes: list[StoryboardScene] = []

    for scene_id in original_order:
        scene = scenes_by_id[scene_id]
        scene_start = cumulative_t
        render_kwargs: dict = {}

        # Character + person_name → person name as centre OST overlay (not lower_third).
        # lower_third banners were removed in P10-S1; person name now appears at the
        # standard OST position so the acquisition layer can still show who is on screen.
        if scene.segment_type == "Character" and scene.person_name:
            scene = scene.model_copy(update={
                "on_screen_text": scene.person_name,
                "on_screen_text_type": "person",
            })

        # Event → film_look
        if scene.segment_type == "Event":
            render_kwargs["film_look"] = True

        # on_screen_text → timed on_screen_text_overlay; type defaults to "stat"
        if scene.on_screen_text:
            end_t = scene_start + scene.duration_s
            enable_expr = f"between(t,{scene_start:.3f},{end_t:.3f})"
            ost_type = scene.on_screen_text_type if scene.on_screen_text_type in ("stat", "date", "person", "label") else "stat"
            render_kwargs["on_screen_text_overlay"] = OnScreenTextOverlay(
                text=scene.on_screen_text,
                type=ost_type,
                enable_expr=enable_expr,
            )

        if render_kwargs:
            scene = scene.model_copy(update={"render_options": SceneRenderOptions(**render_kwargs)})

        cumulative_t += scene.duration_s
        patched_scenes.append(scene)

    return storyboard.model_copy(update={"scenes": patched_scenes})


# ── API call helpers ──────────────────────────────────────────────────────────

_VALID_OST_TYPES = {"stat", "date", "lower_third", "person", "label"}

# Normalise segment_type casing from Claude (model occasionally outputs lowercase).
_SEGMENT_TYPE_MAP = {
    "character": "Character",
    "event": "Event",
    "b-roll": "B-roll",
    "broll": "B-roll",
}


def _sanitize_storyboard_data(data: dict) -> dict:
    """Clamp invalid enum values before Pydantic validation.

    Nulls out unrecognised on_screen_text_type values. Normalises segment_type
    casing so "character" → "Character" etc. (Claude occasionally outputs lowercase).
    """
    for scene in data.get("scenes", []):
        ost_type = scene.get("on_screen_text_type")
        if ost_type is not None and ost_type not in _VALID_OST_TYPES:
            logger.warning(
                "StoryboardWorker: scene %s has invalid on_screen_text_type %r — nulling out",
                scene.get("scene", "?"),
                ost_type,
            )
            scene["on_screen_text_type"] = None
            scene["on_screen_text"] = None
        # Strip bare year-only on_screen_text (e.g. "2011") — adds no value.
        ost = scene.get("on_screen_text")
        if ost and str(ost).strip().isdigit() and len(str(ost).strip()) == 4:
            logger.warning(
                "StoryboardWorker: scene %s has bare year on_screen_text %r — nulling out",
                scene.get("scene", "?"), ost,
            )
            scene["on_screen_text"] = None
            scene["on_screen_text_type"] = None

        seg = scene.get("segment_type")
        if seg and seg not in ("Character", "Event", "B-roll"):
            normalised = _SEGMENT_TYPE_MAP.get(seg.lower())
            if normalised:
                logger.warning(
                    "StoryboardWorker: scene %s segment_type %r normalised to %r",
                    scene.get("scene", "?"), seg, normalised,
                )
                scene["segment_type"] = normalised
    return data


async def _generate(
    script: str,
    voice_timestamps: list[VoiceWordTimestamp],
    api_key: str,
    format_track: str = "portrait",
) -> Storyboard:
    """Call Sonnet to generate the raw storyboard JSON.

    When voice_timestamps are present, uses prompt v0.13 (indexed word list — Claude
    outputs start_word/end_word; Python derives duration_s, clip_type, voiceover_line,
    motion_effect, asset_tier via _reify_scene). When absent, falls back to v0.12
    behaviour (Claude outputs the full scene schema; Python estimates duration_s from
    word count and logs a WARNING).
    """
    format_line = _FORMAT_LINE_LANDSCAPE if format_track == "landscape" else _FORMAT_LINE_PORTRAIT
    pacing_line = _PACING_LINE_LANDSCAPE if format_track == "landscape" else _PACING_LINE_PORTRAIT
    lo_s, hi_s, hard_s = _BODY_PACING_SECONDS.get(format_track, _BODY_PACING_SECONDS["landscape"])

    if voice_timestamps:
        # v0.13 path — indexed word list with punctuation preserved so Claude can
        # see sentence boundaries; Claude only decides scene boundaries + visual metadata
        normalized_words, display_words = _normalize_deepgram_words_with_display(
            [w.model_dump() for w in voice_timestamps]
        )
        ts_block = _format_indexed_timestamps(normalized_words, display_words)
        n_words = len(normalized_words)
        system_prompt = _GENERATE_SYSTEM_PROMPT_V013.replace(_FORMAT_LINE_SENTINEL, format_line)
        system_prompt = system_prompt.replace(_PACING_LINE_SENTINEL, pacing_line)

        # Convert the prompt's seconds targets into a word budget from the measured
        # speech rate — for large scripts the list carries no timestamps, so word
        # counts are the only length signal Claude can act on. Two tiers: a fast
        # hook window (first ~4s) and the format-conditional body target.
        total_s = max(normalized_words[-1].end_ms / 1000.0, 1.0) if normalized_words else 1.0
        wps = n_words / total_s
        hook_words = max(2, round(_HOOK_WINDOW_S * wps))
        hook_scene_words = max(1, round(_HOOK_TARGET_S * wps))
        body_lo = max(2, round(lo_s * wps))
        body_hi = max(body_lo + 2, round(hi_s * wps))
        hard_max_words = max(body_hi + 2, round(hard_s * wps))
        budget_note = (
            f"Measured speech rate: {wps:.1f} words/sec.\n"
            f"HOOK — first ~{hook_words} words (~{_HOOK_WINDOW_S:.0f}s of narration): "
            f"target ~{hook_scene_words} words per scene (~1s each); sub-{hook_scene_words}-word "
            f"scenes are fine here. Cut fast to hook the viewer.\n"
            f"BODY — after the hook: aim {body_lo}–{body_hi} words per scene; "
            f"HARD MAXIMUM {hard_max_words} words. Count words per scene and stay under it.\n"
            f"LIST ITEMS always get their own scene regardless of these targets, even 1–2 words."
        )
        user_content = (
            f"INDEXED WORD LIST ({n_words} words — use start_word/end_word indices; "
            f"punctuation marks sentence boundaries):\n"
            f"{ts_block}\n\n"
            f"{budget_note}\n\n"
            f"VOICEOVER SCRIPT (for reference only — use word indices for boundaries):\n{script}"
        )
    else:
        # v0.12 fallback — no Deepgram timestamps available
        logger.warning("StoryboardWorker: voice_alignment absent — using v0.12 word-count durations")
        normalized_words = []
        system_prompt = _GENERATE_SYSTEM_PROMPT.replace(_FORMAT_LINE_SENTINEL, format_line)
        user_content = script

    # Background task — no Railway HTTP timeout; single attempt, generous wall-clock budget.
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=600.0, max_retries=0)
    message = await client.messages.create(
        model=_SONNET_MODEL,
        max_tokens=32000,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    raw_text = message.content[0].text
    try:
        data = _extract_json_object(raw_text)
        data = _sanitize_storyboard_data(data)

        if normalized_words:
            # Enforce contiguity deterministically: sort by start_word, pin the first
            # scene to word 0 and the last to N-1, and close every gap/overlap so no
            # word is dropped or duplicated regardless of what Claude returned.
            scenes_list = sorted(
                data.get("scenes", []),
                key=lambda s: int(s.get("start_word", 0) or 0),
            )
            if scenes_list:
                scenes_list[0]["start_word"] = 0
                for i in range(len(scenes_list) - 1):
                    scenes_list[i]["end_word"] = int(scenes_list[i + 1].get("start_word", 0)) - 1
                scenes_list[-1]["end_word"] = len(normalized_words) - 1
                # Drop degenerate scenes created by duplicate start_words
                scenes_list = [
                    s for s in scenes_list
                    if int(s.get("end_word", 0)) >= int(s.get("start_word", 0))
                ]
                data["scenes"] = scenes_list

            # v0.13: reify each scene — fills voiceover_line, duration_s, clip_type, motion_effect
            for i, scene_dict in enumerate(data.get("scenes", [])):
                _reify_scene(scene_dict, normalized_words, i)
            # Recompute summary fields that Claude cannot know (duration, rhythm)
            scenes_data = data.get("scenes", [])
            total_dur = sum(s.get("duration_s", 0.0) for s in scenes_data)
            clip_abbrs = {"hard_cut": "HC", "still_with_motion": "SM", "animated": "AN"}
            rhythm_parts = [clip_abbrs.get(s.get("clip_type", ""), "?") for s in scenes_data[:8]]
            rhythm = " / ".join(rhythm_parts) + (" …" if len(scenes_data) > 8 else "")
            if "summary" in data:
                data["summary"]["total_duration_s"] = round(total_dur, 3)
                data["summary"]["rhythm"] = rhythm
        else:
            # v0.12 fallback: estimate duration_s from word count when missing or zero
            for scene_dict in data.get("scenes", []):
                if not scene_dict.get("duration_s"):
                    wc = len(scene_dict.get("voiceover_line", "").split())
                    scene_dict["duration_s"] = round(wc / 2.5, 3)
                tier = _assign_asset_tier(scene_dict.get("duration_s", 0.0))
                if scene_dict.get("segment_type") == "Character":
                    tier = "still_motion"
                scene_dict["asset_tier"] = tier

        return Storyboard.model_validate(data)
    except Exception as exc:
        raise ValueError(f"StoryboardWorker: failed to parse generate response: {exc}") from exc


_REVIEW_SCENE_KEYS = frozenset({
    "scene", "voiceover_line", "segment_type", "person_name", "person_title",
    "primary_stk", "context_stk", "concept_stk",
    "on_screen_text", "on_screen_text_type", "sfx", "sfx_timing",
})


def _slim_for_review(storyboard: "Storyboard") -> str:
    """Serialise only the fields the reviewer reads, dropping render_options, timing, etc."""
    slim_scenes = []
    for scene in storyboard.scenes:
        raw = scene.model_dump(mode="json")
        slim = {k: v for k, v in raw.items() if k in _REVIEW_SCENE_KEYS and v not in (None, "", [])}
        slim_scenes.append(slim)
    return json.dumps({"scenes": slim_scenes}, separators=(",", ":"))


async def _review(
    script: str,
    storyboard: Storyboard,
    api_key: str,
) -> tuple[list[dict], bool, list[str]]:
    """Call Haiku to review the storyboard across 5 quality dimensions.

    Returns (patches, coverage_ok, issues).
    """
    storyboard_json = _slim_for_review(storyboard)
    user_content = (
        f"ORIGINAL SCRIPT:\n{script}\n\n"
        f"STORYBOARD JSON:\n{storyboard_json}"
    )

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=120.0, max_retries=0)
    message = await client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": _REVIEW_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    raw_text = message.content[0].text
    return _parse_review_response(raw_text)


# ── Event OST synthesis (Bug 4) ───────────────────────────────────────────────

_MAX_EVENT_OST_CALLS = 5


async def _synthesize_event_ost(
    storyboard: Storyboard,
    api_key: str,
) -> Storyboard:
    """Fill missing on_screen_text for Event scenes in a single batched Haiku call.

    Collects all scenes where segment_type == "Event" and on_screen_text is absent
    (up to _MAX_EVENT_OST_CALLS), sends them in one request, and applies results.
    """
    gaps = [
        (i, scene) for i, scene in enumerate(storyboard.scenes)
        if scene.segment_type == "Event" and not scene.on_screen_text
    ][:_MAX_EVENT_OST_CALLS]

    if not gaps:
        return storyboard

    items = "\n".join(
        f'{scene.scene}: "{scene.voiceover_line}"'
        for _, scene in gaps
    )
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0, max_retries=0)
    try:
        message = await client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    "For each scene below write a 2–5 word chapter title (on-screen text overlay). "
                    "Return ONLY valid JSON: {\"<scene_id>\": \"TITLE\", ...}. "
                    "Uppercase. Max 30 chars each.\n\n" + items
                ),
            }],
        )
        ost_map: dict = json.loads(message.content[0].text.strip())
    except Exception as exc:
        logger.warning("StoryboardWorker: batched OST synthesis failed: %s", exc)
        return storyboard

    scenes = list(storyboard.scenes)
    for i, scene in gaps:
        ost = str(ost_map.get(scene.scene, "")).strip().upper()[:30]
        if ost:
            logger.info("StoryboardWorker: Event scene %s OST synthesised: %r", scene.scene, ost)
            scenes[i] = scene.model_copy(update={"on_screen_text": ost, "on_screen_text_type": "date"})

    return storyboard.model_copy(update={"scenes": scenes})


# ── Worker factory ────────────────────────────────────────────────────────────


def build_storyboard_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Build the storyboard worker node.

    Reads state.artifacts['script'] and optionally state.artifacts['voice_alignment'].
    Internal cycle: generate (Sonnet) → review (Haiku) → patch (deterministic).
    Emits a single VerifiedStoryboardArtifact with render_options populated per scene.
    """

    async def _worker(state: StageState) -> WorkerOutput:
        """Run generate→review→patch and return VerifiedStoryboardArtifact."""
        # Read script
        script_key = state.artifacts["script"]
        _, script_body = await read_artifact(storage, script_key)
        script_artifact = ScriptArtifact.model_validate(script_body)
        script_text = script_artifact.script

        # Read voice alignment timestamps (optional — absent for standalone endpoint calls)
        voice_timestamps: list[VoiceWordTimestamp] = []
        timestamps_are_real: bool = False  # True only for actual Deepgram timestamps
        if "voice_alignment" in state.artifacts:
            try:
                _, va_body = await read_artifact(storage, state.artifacts["voice_alignment"])
                va = VoiceAlignmentArtifact.model_validate(va_body)
                voice_timestamps = va.word_timestamps
                timestamps_are_real = va.alignment_method != "proportional_fallback"
            except Exception:
                logger.warning("StoryboardWorker: could not read voice_alignment — using word-count durations")

        # Step 1: Generate raw storyboard (v0.13 when timestamps present, v0.12 fallback)
        format_track: str = state.inputs.get("format_track", "portrait")
        storyboard = await _generate(script_text, voice_timestamps, anthropic_api_key, format_track=format_track)
        logger.info("StoryboardWorker: generated %d scenes (prompt %s)", len(storyboard.scenes), STORYBOARD_PROMPT_VERSION)

        # Step 2: Review — 5 quality dimensions (Haiku, structured JSON)
        patches, coverage_ok, issues = await _review(script_text, storyboard, anthropic_api_key)
        if not coverage_ok:
            logger.warning("StoryboardWorker: coverage check failed — %s", "; ".join(issues))
        if patches:
            logger.info("StoryboardWorker: applying %d review patches", len(patches))

        # Step 3: Patch — apply corrections + compute render_options (deterministic)
        storyboard = _apply_patches_and_render_options(storyboard, patches)

        # Step 4: Enforce hard scene-duration cap (tighter for portrait Shorts).
        # Real Deepgram timestamps → split long scenes so word boundaries stay accurate.
        # Proportional fallback → clamp duration_s (boundaries are estimated anyway).
        if timestamps_are_real and voice_timestamps:
            normalized_words = _normalize_deepgram_words([w.model_dump() for w in voice_timestamps])
            max_scene_s = _MAX_SCENE_DURATION_BY_FORMAT.get(format_track, _MAX_SCENE_DURATION_S)
            storyboard = _split_long_scenes(storyboard, normalized_words, max_s=max_scene_s)
            logger.info("StoryboardWorker: after split — %d scenes", len(storyboard.scenes))
        else:
            _STILL_MAX_S = 5.0
            _VIDEO_MAX_S = 8.0
            capped = []
            for scene in storyboard.scenes:
                if scene.clip_type == "still_with_motion" and scene.duration_s > _STILL_MAX_S:
                    scene = scene.model_copy(update={"duration_s": _STILL_MAX_S})
                elif scene.clip_type in ("hard_cut", "animated") and scene.duration_s > _VIDEO_MAX_S:
                    scene = scene.model_copy(update={"duration_s": _VIDEO_MAX_S})
                capped.append(scene)
            storyboard = storyboard.model_copy(update={"scenes": capped})

        # Step 5: Synthesise OST — runs AFTER splitting so it assigns text to the
        # correct sub-scene (the one whose VO actually contains the event/stat).
        storyboard = await _synthesize_event_ost(storyboard, anthropic_api_key)
        storyboard = _apply_patches_and_render_options(storyboard, [])

        artifact = VerifiedStoryboardArtifact(
            prompt_version=STORYBOARD_PROMPT_VERSION,
            scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
