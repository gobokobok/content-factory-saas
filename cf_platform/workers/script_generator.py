"""Script Generator worker (P5-S6) — `merged_blueprint + selected_hook → generated_script`.

Node [6] in the Blueprint IR pipeline (D058). Single Sonnet call — the script is
written EXACTLY ONCE from the finalised blueprint and selected hook. No retries,
no variants, no loop. This is the only LLM call that produces script text.

Pure worker per D040/D056.
"""

from datetime import datetime, timezone
from typing import Optional

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    GeneratedScriptArtifact,
    NarrativeLens,
    SelectedHookArtifact,
)
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_SCRIPT_GENERATOR_PROMPT_V1 = """\
You are a narration script writer for a data-driven YouTube Shorts channel.

You will receive a Blueprint IR (structured content plan) and a selected opening hook. \
Write the final narration script following the blueprint exactly:

- Open with the provided hook verbatim (do not modify it)
- Follow the blueprint sections in order; include all required evidence items
- Write in plain conversational English as if spoken directly to camera
- No filler phrases ("Hey guys", "Subscribe", etc.)
- Ground every claim in the blueprint's claim list; do not invent new statistics
- If COMPUTED FIGURES are provided, use those exact numbers verbatim — never round or \
  substitute different values

CRITICAL — WORD COUNT:
The target word count is a RANGE specified in the user message. You must hit the minimum. \
- If your draft is UNDER the minimum: expand with more depth, concrete examples, \
  additional context, or elaboration on existing points until you reach the minimum. \
  Do not add filler — add substance. \
- If your draft is OVER the maximum: cut or compress the least essential body points. \
Never submit a script below the minimum word count. \
Prioritise: hook → core claim → evidence → CTA.

Return ONLY the narration script text. No JSON, no labels, no preamble.\
"""

SCRIPT_GENERATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_SCRIPT_GENERATOR_PROMPT_V1,
    model="claude-sonnet-4-6",
    sampling_params={},
)

_WORDS_PER_SECOND = 120 / 60  # 2.0 words/sec — Gemini TTS measured pace (505 words = 4:12)


def build_script_generator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a script generator WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['merged_blueprint'] → Blueprint
      state.artifacts['selected_hook']    → SelectedHookArtifact

    target_duration_seconds read via getattr(state, 'target_duration_seconds', 60).
    niche read via state.inputs.get('niche') — used in the user message for framing.

    Makes exactly one Sonnet call. Raises KeyError on missing artifact refs.
    """

    async def script_generator(state: StageState) -> WorkerOutput:
        """Read blueprint + hook, call Claude Sonnet once, return GeneratedScriptArtifact."""
        bp_key = state.artifacts.get("merged_blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['merged_blueprint'] missing — "
                "blueprint_merge must run before script_generation"
            )
        hook_key = state.artifacts.get("selected_hook")
        if not hook_key:
            raise KeyError(
                "state.artifacts['selected_hook'] missing — "
                "hook_selection must run before script_generation"
            )

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        _, hook_body = await read_artifact(storage, hook_key)
        hook_artifact = SelectedHookArtifact.model_validate(hook_body)

        lens: Optional[NarrativeLens] = None
        lens_key = state.artifacts.get("narrative_lens")
        if lens_key:
            _, lens_body = await read_artifact(storage, lens_key)
            lens = NarrativeLens.model_validate(lens_body)

        target_duration: int = int(getattr(state, "target_duration_seconds", 60))
        target_words = round(target_duration * _WORDS_PER_SECOND)
        niche: Optional[str] = state.inputs.get("niche")
        idea_title: str = state.inputs.get("idea_title", "Unknown idea")

        user_message = _build_user_message(
            idea_title=idea_title,
            niche=niche,
            blueprint=blueprint,
            hook=hook_artifact.hook,
            target_words=target_words,
            target_duration=target_duration,
            lens=lens,
        )

        # Scale max_tokens: ~1.3 tokens/word plus 20% headroom, minimum 1024
        script_max_tokens = max(1024, min(8192, round(target_words * 1.3 * 1.2)))

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=120.0)
        response = await client.messages.create(
            model=SCRIPT_GENERATOR_REGISTRATION.model,
            max_tokens=script_max_tokens,
            system=_SCRIPT_GENERATOR_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        script_text = response.content[0].text.strip()
        word_count = len(script_text.split())

        artifact = GeneratedScriptArtifact(
            idea_title=idea_title,
            niche=niche,
            script=script_text,
            word_count=word_count,
            target_duration_seconds=target_duration,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return script_generator


def _build_user_message(
    idea_title: str,
    niche: Optional[str],
    blueprint: Blueprint,
    hook: str,
    target_words: int,
    target_duration: int,
    lens: Optional[NarrativeLens] = None,
) -> str:
    """Compose the Claude user message from the blueprint, hook, and optional narrative lens."""
    max_words = round(target_words * 1.10)
    min_words = round(target_words * 0.85)
    parts = []
    if niche:
        parts.append(f"Channel niche: {niche}")
    else:
        parts.append("Channel niche: not specified — write for a general data-driven audience")
    parts.append(f"Video idea: {idea_title}")
    parts.append(
        f"⚠️ WORD COUNT — YOU MUST HIT THIS RANGE: {min_words}–{max_words} words "
        f"(target {target_words} words = {target_duration}s at 160 wpm). "
        f"Minimum: {min_words} words — expand with depth/examples if under. "
        f"Maximum: {max_words} words — cut if over. Never submit below {min_words} words."
    )
    parts.append("")
    parts.append(f"=== SELECTED HOOK (use verbatim as the opening) ===\n{hook}")
    parts.append("")
    parts.append("=== BLUEPRINT STRUCTURE ===")
    for i, section in enumerate(blueprint.structure, start=1):
        key_points = "\n".join(f"  - {kp}" for kp in section.key_points)
        parts.append(f"{i}. {section.title}\n{key_points}")
    parts.append("")
    parts.append("=== CLAIMS (include in script) ===")
    for claim in blueprint.claims:
        parts.append(f"  - {claim}")
    parts.append("")
    parts.append("=== REQUIRED EVIDENCE (must appear in script) ===")
    for evidence in blueprint.required_evidence:
        parts.append(f"  - {evidence}")
    if blueprint.math_derivations:
        parts.append("")
        parts.append(
            "=== COMPUTED FIGURES (use these exact numbers — do not substitute or round) ==="
        )
        for derivation in blueprint.math_derivations:
            parts.append(f"  - {derivation}")
    parts.append("")
    parts.append(f"Direction: {blueprint.direction_alignment_notes}")
    if lens:
        parts.append("")
        parts.append(
            "=== NARRATIVE ANGLES (aim for 70% rational / 30% emotional — use these to "
            "add identity, surprise, and feeling to the rational content above) ==="
        )
        parts.append(f"Identity:     {lens.identity_angle}")
        parts.append(f"Contrarian:   {lens.contrarian_angle}")
        parts.append(f"Philosophical: {lens.philosophical_angle}")
        parts.append(f"Emotional:    {lens.emotional_angle}")
        if lens.story_devices:
            parts.append(f"Story devices: {', '.join(lens.story_devices)}")
        parts.append(
            "Weave these angles into the prose — do not invent new facts to support them."
        )
    parts.append("")
    parts.append("Write the full narration script now.")
    return "\n".join(parts)
