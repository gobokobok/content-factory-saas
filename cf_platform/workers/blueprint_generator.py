"""Blueprint Generator worker (P5-S6) — `normalized_context → blueprint`.

Node [1] in the Blueprint IR pipeline (D058). Single Sonnet call that produces
the Blueprint IR — a structured content plan (hook angle, sections, claims,
evidence requirements) used to constrain single-pass script generation.

Pure worker per D040/D056.
"""

import json
from typing import Optional

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, NormalizedContext, Section
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_BLUEPRINT_GENERATOR_PROMPT_V1 = """\
You are a content strategist for a data-driven short-form video channel.

Given a normalised context for a video idea, produce a Blueprint IR — a structured \
content plan that a script writer can follow exactly. The blueprint defines what to \
say (claims, evidence) and how to say it (hook angle, section structure), so the \
writer never needs to invent facts or structure.

Return ONLY a single JSON object (no markdown fences) matching this schema:
{
  "hook_angle": "one sentence describing the attention-grabbing opening premise",
  "structure": [
    {"title": "Section name", "key_points": ["point 1", "point 2"]}
  ],
  "claims": ["specific factual claim 1", "specific factual claim 2"],
  "monetization_angle": "one sentence on why this topic keeps viewers watching",
  "required_evidence": ["data point or source the script must reference"],
  "signal_summary": "one paragraph summarising the key context signals",
  "direction_alignment_notes": "how the script should align with the stated angle"
}

Rules:
- `structure` must have 3–5 sections (hook, 2–3 body sections, closer)
- `claims` must be factually grounded — state only what is reasonably well known
- `required_evidence` lists specific things the script writer must incorporate
- Keep each field concise; the script writer reads this as a specification
\
"""

BLUEPRINT_GENERATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_BLUEPRINT_GENERATOR_PROMPT_V1,
    model="claude-sonnet-4-6",
    sampling_params={},
)


def build_blueprint_generator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a blueprint generator WorkerNode bound to storage and the Anthropic API key.

    Reads state.artifacts['normalized_context'] → NormalizedContext.
    Makes one Sonnet call; raises ValueError on JSON parse failure.
    """

    async def blueprint_generator(state: StageState) -> WorkerOutput:
        """Read normalized_context, call Claude Sonnet, return Blueprint artifact."""
        ctx_key = state.artifacts.get("normalized_context")
        if not ctx_key:
            raise KeyError(
                "state.artifacts['normalized_context'] missing — "
                "context_normalization must run before blueprint_generation"
            )
        _, ctx_body = await read_artifact(storage, ctx_key)
        ctx = NormalizedContext.model_validate(ctx_body)

        niche: Optional[str] = state.inputs.get("niche")
        idea_title: str = state.inputs.get("idea_title", "Unknown idea")

        user_message = _build_user_message(idea_title, niche, ctx)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=BLUEPRINT_GENERATOR_REGISTRATION.model,
            max_tokens=2048,
            system=_BLUEPRINT_GENERATOR_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = extract_json_object(response.content[0].text)
        try:
            raw_dict = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"blueprint_generator@v1 returned invalid JSON: {exc}\nRaw: {raw_text!r}"
            ) from exc

        # Parse sections
        raw_sections = raw_dict.get("structure", [])
        sections = [Section.model_validate(s) for s in raw_sections]

        artifact = Blueprint(
            hook_angle=raw_dict.get("hook_angle", ""),
            structure=sections,
            claims=raw_dict.get("claims", []),
            monetization_angle=raw_dict.get("monetization_angle", ""),
            required_evidence=raw_dict.get("required_evidence", []),
            signal_summary=raw_dict.get("signal_summary", ""),
            direction_alignment_notes=raw_dict.get("direction_alignment_notes", ""),
        )
        return WorkerOutput(artifact=artifact)

    return blueprint_generator


def _build_user_message(
    idea_title: str,
    niche: Optional[str],
    ctx: NormalizedContext,
) -> str:
    """Compose the Claude user message from the normalised context."""
    parts = []
    if niche:
        parts.append(f"Channel niche: {niche}")
    else:
        parts.append("Channel niche: not specified — infer from idea title")
    parts.append(f"Idea title: {idea_title}")
    parts.append(f"Primary angle: {ctx.primary_angle}")
    parts.append(f"Hook bias: {ctx.hook_bias}")
    if ctx.evidence_summary and ctx.evidence_summary != "No prior evidence provided.":
        parts.append(f"Available evidence: {ctx.evidence_summary}")
    if ctx.top_signals:
        bullets = "\n".join(f"  - {s}" for s in ctx.top_signals)
        parts.append(f"Key signals:\n{bullets}")
    if ctx.controversies:
        parts.append(f"Avoid or handle carefully: {', '.join(ctx.controversies)}")
    parts.append("\nProduce the Blueprint IR JSON.")
    return "\n".join(parts)
