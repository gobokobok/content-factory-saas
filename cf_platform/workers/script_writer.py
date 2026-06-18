"""DEPRECATED (P5-S6) — replaced by blueprint_generator.py + script_generator.py in the Blueprint IR pipeline (D058).
Kept importable so legacy tests pass; not registered in the active idea_to_script graph.

Script Writer worker (P5-S1) — `ranked_ideas → script_drafts`.

Two entry paths:

  Full pipeline: `state.artifacts["ranked_ideas"]` is present. Title, niche, and
  angle are read from the RankedIdeasArtifact. If `state.artifacts["discovery"]`
  is also present the top-5 signals (by score) are extracted as grounding bullets.

  Direct entry (e.g. Telegram /script command): no `ranked_ideas` artifact.
  `state.inputs["idea_title"]` is required; `state.inputs["niche"]`,
  `state.inputs["angle"]`, and `state.inputs["supporting_points"]` (list[str])
  are optional. This path lets the operator skip the niche→ideas block entirely.

  `state.inputs["supporting_points"]` always takes priority over auto-extracted
  discovery signals, allowing callers to supply curated grounding facts.

Returns all N drafts in a single `ScriptDraftsArtifact`; the scorer (P5-S2)
picks the best one. N defaults to 3 and can be overridden by
`getattr(state, "max_iterations", 3)` so the factory is compatible with
`IdeaToScriptState` when the full idea_to_script graph is assembled in P5-S5.

Pure worker per D040/D056.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact

_SCRIPT_WRITER_PROMPT_V2 = """\
You are a script writer for "The Housing Equation", a data-driven YouTube Shorts \
channel about American housing economics.

Write a narration script for a 60–90 second short-form video (approximately 150–200 \
words). The script must be:
- Written in plain conversational English as if spoken directly to camera
- Grounded in real data or economic patterns (cite at least one specific statistic, \
trend, or historic fact)
- Built around the supplied title and narrative angle (when provided)
- Free of filler phrases ("Hey guys", "Don't forget to like", etc.)
- Structured with a hook in the first 10 seconds, a data-driven middle, and a punchy \
closing line

When source signals are listed, ground at least one specific claim in those sources \
rather than inventing statistics.

You will be asked to produce N draft variants. Each variant should explore the same \
topic and angle but differ in structure, opening hook, or emphasis.

Return ONLY a JSON array of N objects, each with a "draft_number" (1-based integer) \
and "script" (the full narration text). No preamble, no markdown fences. Example:
[
  {
    "draft_number": 1,
    "script": "In 1980, the average American could afford a home after 3 years of saving. \
Today it takes 12. Here is why..."
  }
]\
"""

SCRIPT_WRITER_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version="v2",
    prompt=_SCRIPT_WRITER_PROMPT_V2,
    model="claude-haiku-4-5",
    sampling_params={},
)

_MAX_SIGNALS = 5


class ScriptDraft(BaseModel):
    """One narration script draft produced by the script writer."""

    draft_number: int
    script: str


class ScriptDraftsArtifact(BaseModel):
    """Artifact body produced by the script writer worker."""

    niche: Optional[str]
    idea_title: str
    idea_angle: Optional[str]
    drafts: list[ScriptDraft]
    generated_at: datetime


def _build_user_message(
    idea_title: str,
    niche: Optional[str],
    angle: Optional[str],
    supporting_points: list[str],
    n: int,
) -> str:
    """Compose the Claude user message from available context."""
    parts: list[str] = []
    if niche:
        parts.append(f"Niche: {niche}")
    parts.append(f"Title: {idea_title}")
    if angle:
        parts.append(f"Angle: {angle}")
    if supporting_points:
        bullets = "\n".join(f"- {p}" for p in supporting_points)
        parts.append(f"Source signals (use for grounding):\n{bullets}")
    parts.append(f"\nWrite {n} draft variant(s).")
    return "\n".join(parts)


def build_script_writer_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
    n_drafts: int = 3,
) -> WorkerNode:
    """Return a script writer WorkerNode bound to storage and the Anthropic API key.

    Supports two entry paths (see module docstring). N is resolved as
    `getattr(state, "max_iterations", n_drafts)`.

    Raises KeyError if neither `state.artifacts["ranked_ideas"]` nor
    `state.inputs["idea_title"]` is present.
    Raises ValueError if Claude returns non-JSON or malformed draft objects.
    """

    async def script_writer(state: StageState) -> WorkerOutput:
        """Resolve context from state, call Claude Haiku, return ScriptDraftsArtifact."""
        # ── resolve title / niche / angle ──────────────────────────────────
        ranked_key = state.artifacts.get("ranked_ideas")
        if ranked_key:
            _, body = await read_artifact(storage, ranked_key)
            ranked_artifact = RankedIdeasArtifact.model_validate(body)
            idea_title: str = ranked_artifact.selected.title
            niche: Optional[str] = ranked_artifact.niche
            angle: Optional[str] = ranked_artifact.selected.angle
        else:
            idea_title = state.inputs.get("idea_title")  # type: ignore[assignment]
            if not idea_title:
                raise KeyError(
                    "state.artifacts['ranked_ideas'] or state.inputs['idea_title'] must be provided"
                )
            niche = state.inputs.get("niche")
            angle = state.inputs.get("angle")

        # ── resolve supporting_points ──────────────────────────────────────
        # inputs override takes priority; fall back to discovery signals
        supporting_points: list[str] = list(state.inputs.get("supporting_points") or [])
        if not supporting_points:
            discovery_key = state.artifacts.get("discovery")
            if discovery_key:
                _, disc_body = await read_artifact(storage, discovery_key)
                disc = SignalsArtifact.model_validate(disc_body)
                top = sorted(disc.signals, key=lambda s: s.score, reverse=True)[:_MAX_SIGNALS]
                supporting_points = [f"[{s.source}] {s.title}" for s in top]

        # ── call Claude ────────────────────────────────────────────────────
        effective_n = int(getattr(state, "max_iterations", n_drafts))
        user_message = _build_user_message(idea_title, niche, angle, supporting_points, effective_n)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=SCRIPT_WRITER_REGISTRATION.model,
            max_tokens=2048,
            system=SCRIPT_WRITER_REGISTRATION.prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        try:
            raw_drafts: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"script_writer@v2 returned invalid JSON: {exc}\nRaw response: {raw_text!r}"
            ) from exc

        drafts = [ScriptDraft.model_validate(d) for d in raw_drafts]
        artifact = ScriptDraftsArtifact(
            niche=niche,
            idea_title=idea_title,
            idea_angle=angle,
            drafts=drafts,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return script_writer
