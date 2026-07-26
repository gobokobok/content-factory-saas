"""Blueprint Generator worker (P5-S6) — `normalized_context → blueprint`.

Node [1] in the Blueprint IR pipeline (D058). Single Sonnet call that produces
the Blueprint IR — a structured content plan (hook angle, sections, claims,
evidence requirements) used to constrain single-pass script generation.

Pure worker per D040/D056.
"""

import json

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, NormalizedContext, Section
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_BLUEPRINT_GENERATOR_PROMPT_V1 = """\
You are a content strategist for a data-driven video channel covering topics from \
short YouTube Shorts (60 s) to long-form essays (10+ min).

Given a normalised context and a target video duration, produce a Blueprint IR — a \
structured content plan that a script writer can follow exactly. The blueprint defines \
what to say (claims, evidence) and how to say it (hook angle, section structure), so \
the writer never needs to invent facts or structure.

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
  "direction_alignment_notes": "how the script should align with the stated angle",
  "math_derivations": ["formula and result for each numerical claim"]
}

SCALING RULES — base structure on the target word count supplied in the user message:

| Target words  | Sections | Key points / section | Claims | Required evidence |
|---------------|----------|----------------------|--------|-------------------|
| ≤ 160         | 3        | 1–2                  | 2–3    | 1–2               |
| 161 – 320     | 4–5      | 2–3                  | 3–5    | 2–3               |
| 321 – 800     | 5–8      | 2–4                  | 4–8    | 3–6               |
| 801 – 1600    | 8–12     | 3–5                  | 8–12   | 6–10              |
| 1601+         | 12–16    | 4–6                  | 12–16  | 10–14             |

The first section is always the hook; the last is always the CTA / closer. \
Intermediate sections are the substantive body — fill them with distinct angles, \
data points, and narrative beats proportional to the available word budget. \
A longer video must earn its runtime: more sections, deeper evidence, multiple \
supporting angles, not just repetition.

Additional rules:
- `claims` must be factually grounded — state only what is reasonably well known
- `required_evidence` lists specific things the script writer must incorporate
- Keep each field concise; the script writer reads this as a specification
- `math_derivations`: for EVERY claim that contains a specific number derived from \
calculation (compound interest, percentage change, multiplier, scaling), show the \
formula and exact computed result. Example: \
"$10k at 6% net for 30y: 10000*(1.06)^30 = $57,435". \
Omit entries for claims with no calculation. \
CRITICAL: claims must cite the exact figures from math_derivations — never round or \
adjust for dramatic effect. The hook number must appear in math_derivations if it is \
a calculated figure.
\
"""

_WORDS_PER_SECOND = 160 / 60  # standard narration pace — mirrors script_generator

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
        """Read normalized_context + target_duration, call Claude Sonnet, return Blueprint."""
        ctx_key = state.artifacts.get("normalized_context")
        if not ctx_key:
            raise KeyError(
                "state.artifacts['normalized_context'] missing — "
                "context_normalization must run before blueprint_generation"
            )
        _, ctx_body = await read_artifact(storage, ctx_key)
        ctx = NormalizedContext.model_validate(ctx_body)

        niche: str | None = state.inputs.get("niche")
        idea_title: str = state.inputs.get("idea_title", "Unknown idea")
        target_duration: int = int(getattr(state, "target_duration_seconds", 60))
        target_words: int = round(target_duration * _WORDS_PER_SECOND)

        user_message = _build_user_message(idea_title, niche, ctx, target_words)

        # Scale max_tokens with blueprint size: ~200 tokens base + 100 per 100 target words
        bp_max_tokens = max(2048, min(8192, 200 + target_words * 6))

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=BLUEPRINT_GENERATOR_REGISTRATION.model,
            max_tokens=bp_max_tokens,
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
            math_derivations=raw_dict.get("math_derivations", []),
        )
        return WorkerOutput(artifact=artifact)

    return blueprint_generator


def _build_user_message(
    idea_title: str,
    niche: str | None,
    ctx: NormalizedContext,
    target_words: int,
) -> str:
    """Compose the Claude user message from the normalised context and target word count."""
    parts = []
    if niche:
        parts.append(f"Channel niche: {niche}")
    else:
        parts.append("Channel niche: not specified — infer from idea title")
    parts.append(f"Idea title: {idea_title}")
    parts.append(f"Target word count: {target_words} words (use the scaling table to size the blueprint)")
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
