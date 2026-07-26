"""Hook Selector worker (P5-S6) — `hook_variants + merged_blueprint → selected_hook`.

Node [5] in the Blueprint IR pipeline (D058). Single Haiku call that picks the
best hook variant based on the blueprint's hook_angle and signal_summary.

Pure worker per D040/D056.
"""

import json
from datetime import UTC, datetime

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, HookVariantsArtifact, SelectedHookArtifact
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_HOOK_SELECTOR_PROMPT_V1 = """\
You are an expert short-form video editor evaluating opening hooks.

Given a list of hook candidates and the blueprint context, choose the single best hook \
that is most likely to stop a viewer mid-scroll. Evaluate on: tension, specificity, \
and alignment with the video's core angle.

Return ONLY a JSON object with the key "hook" containing the selected hook string. \
No preamble, no markdown fences. Example:
{"hook": "The chosen hook text."}\
"""

HOOK_SELECTOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_HOOK_SELECTOR_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


def build_hook_selector_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a hook selector WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['hook_variants']   → HookVariantsArtifact
      state.artifacts['merged_blueprint'] → Blueprint

    Makes one Haiku call; falls back to hooks[0] if response is unparseable.
    Raises KeyError if either artifact reference is absent.
    """

    async def hook_selector(state: StageState) -> WorkerOutput:
        """Read hook_variants + merged_blueprint, pick best hook via Haiku."""
        hooks_key = state.artifacts.get("hook_variants")
        if not hooks_key:
            raise KeyError(
                "state.artifacts['hook_variants'] missing — "
                "hook_generation must run before hook_selection"
            )
        bp_key = state.artifacts.get("merged_blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['merged_blueprint'] missing — "
                "blueprint_merge must run before hook_selection"
            )

        _, hooks_body = await read_artifact(storage, hooks_key)
        hooks_artifact = HookVariantsArtifact.model_validate(hooks_body)

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        if not hooks_artifact.hooks:
            raise ValueError("hook_variants.hooks is empty — hook_generator produced no hooks")

        # Single-hook fast path: skip LLM call
        if len(hooks_artifact.hooks) == 1:
            selected = hooks_artifact.hooks[0]
        else:
            selected = await _select_via_llm(
                hooks_artifact.hooks, blueprint, anthropic_api_key
            )

        artifact = SelectedHookArtifact(
            hook=selected,
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact)

    return hook_selector


async def _select_via_llm(
    hooks: list[str],
    blueprint: Blueprint,
    anthropic_api_key: str,
) -> str:
    """Call Haiku to pick the best hook; fall back to hooks[0] on parse failure."""
    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(hooks))
    user_message = (
        f"Hook angle: {blueprint.hook_angle}\n"
        f"Signal summary: {blueprint.signal_summary}\n\n"
        f"Hook candidates:\n{numbered}\n\n"
        "Pick the single best hook and return the JSON."
    )

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=60.0)
    response = await client.messages.create(
        model=HOOK_SELECTOR_REGISTRATION.model,
        max_tokens=256,
        system=_HOOK_SELECTOR_PROMPT_V1,
        messages=[{"role": "user", "content": user_message}],
    )

    try:
        raw = extract_json_object(response.content[0].text)
        result = json.loads(raw)
        selected = str(result.get("hook", "")).strip()
        if selected:
            return selected
    except (ValueError, json.JSONDecodeError, KeyError):
        pass

    # Graceful fallback: return first hook
    return hooks[0]
