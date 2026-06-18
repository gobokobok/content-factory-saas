"""Hook Generator worker (P5-S6) — `merged_blueprint → hook_variants`.

Node [4] in the Blueprint IR pipeline (D058). Single Haiku call that produces
three distinct hook variants drawn from the blueprint's hook_angle. The hook
is the first 5–15 words of the script — the phrase that keeps the viewer watching.

Pure worker per D040/D056.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, HookVariantsArtifact, NarrativeLens
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_HOOK_GENERATOR_PROMPT_V1 = """\
You are a short-form video hook writer. A hook is the opening 5–15 words that make \
a viewer stop scrolling and watch.

Given a blueprint, write exactly 3 distinct hook variants that capture the video's \
core tension or surprising angle. Each hook must:
- Be 5–15 words long
- Start with a high-tension or counterintuitive statement (never a question)
- Be immediately gripping — no buildup

Return ONLY a JSON array of 3 strings. No preamble, no markdown fences. Example:
["Hook A text here.", "Hook B text here.", "Hook C text here."]\
"""

HOOK_GENERATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_HOOK_GENERATOR_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


def build_hook_generator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a hook generator WorkerNode bound to storage and the Anthropic API key.

    Reads state.artifacts['merged_blueprint'] → Blueprint.
    Makes one Haiku call; raises ValueError on JSON parse failure.
    """

    async def hook_generator(state: StageState) -> WorkerOutput:
        """Read merged_blueprint + optional narrative_lens, call Claude Haiku, return HookVariantsArtifact."""
        bp_key = state.artifacts.get("merged_blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['merged_blueprint'] missing — "
                "blueprint_merge must run before hook_generation"
            )
        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        lens: Optional[NarrativeLens] = None
        lens_key = state.artifacts.get("narrative_lens")
        if lens_key:
            _, lens_body = await read_artifact(storage, lens_key)
            lens = NarrativeLens.model_validate(lens_body)

        user_message = _build_user_message(blueprint, lens)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=60.0)
        response = await client.messages.create(
            model=HOOK_GENERATOR_REGISTRATION.model,
            max_tokens=512,
            system=_HOOK_GENERATOR_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        try:
            raw_hooks: list[Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"hook_generator@v1 returned invalid JSON: {exc}\nRaw: {raw_text!r}"
            ) from exc

        hooks = [str(h) for h in raw_hooks]
        artifact = HookVariantsArtifact(
            hooks=hooks,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return hook_generator


def _build_user_message(blueprint: Blueprint, lens: Optional[NarrativeLens] = None) -> str:
    """Compose the Claude user message from the merged blueprint and optional narrative lens."""
    parts = [
        f"Hook angle: {blueprint.hook_angle}",
        f"Signal summary: {blueprint.signal_summary}",
    ]
    if lens:
        parts.append("")
        parts.append("=== NARRATIVE ANGLES (use to make hooks emotionally resonant) ===")
        parts.append(f"Contrarian: {lens.contrarian_angle}")
        parts.append(f"Identity:   {lens.identity_angle}")
        parts.append(f"Emotional:  {lens.emotional_angle}")
    parts.append("")
    parts.append("Generate 3 hook variants for this video.")
    return "\n".join(parts)
