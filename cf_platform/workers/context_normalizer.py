"""Context Normalizer worker (P5-S6) — `state.inputs → normalized_context`.

Node [0] in the Blueprint IR pipeline (D058). Pure deterministic function —
zero LLM calls. Reads idea_title, niche, angle, supporting_points, and any
DirectionContext from state.inputs; emits a NormalizedContext artifact.

Pure worker per D040/D056.
"""

from cf_platform.core.idea_to_script_schemas import DirectionContext, NormalizedContext, Signal
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

CONTEXT_NORMALIZER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",  # no LLM prompt — deterministic node
    model="none",
    sampling_params={},
)


def build_context_normalizer_worker() -> WorkerNode:
    """Return a context normalizer WorkerNode (no external bindings required).

    Reads from state.inputs:
      - idea_title (str, required)
      - niche (str | None)
      - angle (str | None)
      - supporting_points (list[str] | None)
      - direction_context (dict | None — DirectionContext-shaped)
      - signals (list[dict] | None — Signal-shaped stubs)

    Raises KeyError if idea_title is absent.
    """

    async def context_normalizer(state: StageState) -> WorkerOutput:
        """Normalize idea inputs into a structured NormalizedContext artifact."""
        idea_title: str = state.inputs.get("idea_title")  # type: ignore[assignment]
        if not idea_title:
            raise KeyError(
                "state.inputs['idea_title'] is required for context_normalization"
            )

        niche: str | None = state.inputs.get("niche")
        angle: str | None = state.inputs.get("angle")
        supporting_points: list[str] = list(state.inputs.get("supporting_points") or [])

        # Parse optional DirectionContext
        raw_direction = state.inputs.get("direction_context")
        direction_context: DirectionContext | None = None
        if raw_direction:
            direction_context = DirectionContext.model_validate(raw_direction)

        # Parse optional signal stubs
        raw_signals: list[dict] = list(state.inputs.get("signals") or [])
        signals = [Signal.model_validate(s) for s in raw_signals]

        # Build primary_angle: prefer angle → direction_context.angle → idea_title
        if angle:
            primary_angle = angle
        elif direction_context and direction_context.angle:
            primary_angle = direction_context.angle
        else:
            primary_angle = idea_title

        # evidence_summary: combine supporting_points + signal content
        evidence_parts = list(supporting_points)
        for sig in signals:
            if sig.content not in evidence_parts:
                evidence_parts.append(sig.content)
        evidence_summary = "; ".join(evidence_parts) if evidence_parts else "No prior evidence provided."

        # top_signals: high-weight signals first
        sorted_signals = sorted(signals, key=lambda s: s.weight, reverse=True)
        top_signals = [s.content for s in sorted_signals[:5]]

        # controversies: direction_context.do_not_focus_on as contrarian angles
        controversies: list[str] = []
        if direction_context and direction_context.do_not_focus_on:
            controversies = list(direction_context.do_not_focus_on)

        # hook_bias: prefer explicit hook direction, else niche-derived
        if direction_context and direction_context.hook_direction:
            hook_bias = direction_context.hook_direction
        elif direction_context and direction_context.narrative_bias:
            hook_bias = direction_context.narrative_bias
        elif niche:
            hook_bias = f"Data-driven angle relevant to {niche}"
        else:
            hook_bias = "Surprising data or counterintuitive insight"

        artifact = NormalizedContext(
            primary_angle=primary_angle,
            evidence_summary=evidence_summary,
            top_signals=top_signals,
            controversies=controversies,
            hook_bias=hook_bias,
        )
        return WorkerOutput(artifact=artifact)

    return context_normalizer
