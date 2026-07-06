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

STORYBOARD_PROMPT_VERSION = "v0.15"

_SONNET_MODEL = "claude-sonnet-4-6"
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

STORYBOARD_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version=STORYBOARD_PROMPT_VERSION,
    prompt="",
    model=_SONNET_MODEL,
    sampling_params={"max_tokens": 16000},
)

# Format lines substituted into _GENERATE_SYSTEM_PROMPT per-run based on format_track.
_FORMAT_LINE_SENTINEL = "Format: 16:9 horizontal. Voiceover only. Stock footage + Wikimedia Commons."
_FORMAT_LINE_PORTRAIT = "Format: 9:16 vertical, 30–60 second YouTube Short. Voiceover only. Stock footage + Wikimedia Commons."
_FORMAT_LINE_LANDSCAPE = "Format: 16:9 horizontal, 30–180 second YouTube video. Voiceover only. Stock footage + Wikimedia Commons."

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

"Character" — the voiceover mentions a specific named real individual (scientist,
  politician, researcher, historical figure). Use this even if the scene is about their
  work or study — the visual should be their portrait, not generic B-roll.
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
- FIRST mention of a named real person (scientist, researcher, politician) in the script
  → MUST be "Character" with person_name set. This is their introduction scene; show their portrait.
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

Your job: divide the indexed voiceover word list into scenes. For each scene, output
start_word and end_word integer indices (inclusive) and the visual/audio metadata.
Output ONLY a valid JSON object — no prose, no markdown fences, no extra keys.

═══════════════════════════════════════
INDEXED WORD LIST — HOW TO USE
═══════════════════════════════════════

The voiceover words are provided as a numbered list with timestamps.
For each scene set start_word and end_word to integer indices from this list.

Rules:
- Target 2–5 seconds per scene. Hard maximum: 7 seconds.
- If a span would exceed 7 seconds, split it at the nearest clause boundary
  (comma, semicolon, "and", "but", "because", "so", "which", topic shift, or list item).
- Do NOT split mid-phrase or at arbitrary word counts.
- Scenes must be contiguous: scene[i].end_word + 1 == scene[i+1].start_word.
- The first scene's start_word must be 0.
- The last scene's end_word must equal (total words − 1).
- Do NOT overlap: each word index must appear in exactly one scene.

═══════════════════════════════════════
SEGMENT TYPE
═══════════════════════════════════════

Every scene has a segment_type. Use exactly one of:

"Character" — the voiceover mentions a specific named real individual (scientist,
  politician, researcher, historical figure). Use this even if the scene is about their
  work or study — the visual should be their portrait, not generic B-roll.
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
- FIRST mention of a named real person (scientist, researcher, politician) in the script
  → MUST be "Character" with person_name set. This is their introduction scene; show their portrait.
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

def _normalize_deepgram_words(raw: list[dict]) -> list[VoiceWordTimestamp]:
    """Normalise Deepgram word list: strip terminal punctuation, collapse same-start_ms duplicates.

    Strips terminal punctuation (period, comma, etc.) but preserves apostrophes so that
    contraction tokens like "'s" remain intact when merged. Contiguous tokens with
    identical start_ms (Deepgram contraction splits) are merged into one word.
    Returns a flat, clean, 0-indexed list.
    """
    stripped: list[dict] = []
    for item in raw:
        word = item.get("word", "")
        clean = word.strip(_TERMINAL_PUNCT)
        if not clean:
            clean = word  # keep as-is when stripping empties the token (e.g. "—")
        stripped.append({
            "word": clean,
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
                "start_ms": prev["start_ms"],
                "end_ms": max(prev["end_ms"], item["end_ms"]),
                "confidence": min(prev["confidence"], item["confidence"]),
            }
        else:
            collapsed.append(item)

    return [VoiceWordTimestamp(**item) for item in collapsed]


_WORD_LIST_MAX_ENTRIES = 350


def _format_indexed_timestamps(words: list[VoiceWordTimestamp]) -> tuple[str, int]:
    """Format indexed word list for the v0.13 generate prompt.

    For ≤350 words: full list with timestamps, one entry per word.
    For >350 words: strided list (every Nth word, no timestamps).
    Timestamps are stripped for large scripts because Python derives timing
    from the full word array via _reify_scene — Claude only needs indices.

    Returns (formatted_block, stride) where stride=1 means no striding.
    """
    n = len(words)
    if n <= _WORD_LIST_MAX_ENTRIES:
        block = "\n".join(
            f'[{idx}]  "{w.word}"    ({w.start_ms / 1000:.2f}s–{w.end_ms / 1000:.2f}s)'
            for idx, w in enumerate(words)
        )
        return block, 1
    stride = math.ceil(n / _WORD_LIST_MAX_ENTRIES)
    block = "\n".join(
        f'[{idx}]  "{w.word}"'
        for idx, w in enumerate(words)
        if idx % stride == 0
    )
    return block, stride


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
            "Scene %s has duration %.1fs ≥ 10s — consider splitting at a clause boundary",
            raw.get("scene", "?"), raw["duration_s"],
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


def _split_long_scenes(
    storyboard: "Storyboard",
    words: list[VoiceWordTimestamp],
    max_s: float = _MAX_SCENE_DURATION_S,
) -> "Storyboard":
    """Split any scene whose VO span exceeds max_s into equal-word-count sub-scenes.

    Visual metadata (queries, segment_type, person fields, render_options) is
    copied to every sub-scene. on_screen_text is kept only on the first sub-scene
    so overlays don't repeat. _reify_scene is called on each sub-scene to derive
    fresh timing, voiceover_line, asset_tier, clip_type, and motion_effect.
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

        base = scene.model_dump(by_alias=True, mode="json")
        logger.info(
            "StoryboardWorker: splitting scene %s (%.1fs) into %d sub-scenes",
            scene.scene, scene.duration_s, n_splits,
        )

        for j in range(n_splits):
            sub_start = scene.start_word + j * words_per_split
            sub_end = min(scene.start_word + (j + 1) * words_per_split - 1, scene.end_word)

            sub = dict(base)
            sub["start_word"] = sub_start
            sub["end_word"] = sub_end
            # on_screen_text only on first sub-scene
            if j > 0:
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

            _reify_scene(sub, words, len(result))
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

    if voice_timestamps:
        # v0.13 path — indexed timestamps; Claude only decides scene boundaries + visual metadata
        normalized_words = _normalize_deepgram_words([w.model_dump() for w in voice_timestamps])
        ts_block, stride = _format_indexed_timestamps(normalized_words)
        n_words = len(normalized_words)
        system_prompt = _GENERATE_SYSTEM_PROMPT_V013.replace(_FORMAT_LINE_SENTINEL, format_line)
        if stride > 1:
            stride_note = (
                f"every {stride}th word shown — use any integer index 0–{n_words - 1} "
                "for scene boundaries, not just the listed indices"
            )
        else:
            stride_note = "use start_word/end_word indices"
        user_content = (
            f"INDEXED WORD LIST ({n_words} words — {stride_note}):\n"
            f"{ts_block}\n\n"
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

        # Step 3b: Synthesise OST for any Event scenes that still lack on_screen_text (Bug 4).
        # Run AFTER the initial patch so we only fill genuine gaps, not ones the reviewer fixed.
        # Re-apply render_options afterwards so the new OST text gets an enable_expr.
        storyboard = await _synthesize_event_ost(storyboard, anthropic_api_key)
        storyboard = _apply_patches_and_render_options(storyboard, [])

        # Step 4: Enforce hard 10s scene cap.
        # Real Deepgram timestamps → split long scenes so word boundaries stay accurate.
        # Proportional fallback → clamp duration_s (boundaries are estimated anyway).
        if timestamps_are_real and voice_timestamps:
            normalized_words = _normalize_deepgram_words([w.model_dump() for w in voice_timestamps])
            storyboard = _split_long_scenes(storyboard, normalized_words)
            # Re-derive render_options for any new sub-scenes.
            storyboard = _apply_patches_and_render_options(storyboard, [])
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

        artifact = VerifiedStoryboardArtifact(
            prompt_version=STORYBOARD_PROMPT_VERSION,
            scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
