"""Script Writer worker (P5-S1) — `ranked_ideas → script_drafts`.

Reads the `ranked_ideas` artifact produced by the Topic Selector, extracts the
selected topic (title + angle + niche), and calls Claude Sonnet to produce N
narration script drafts for a 60–90s YouTube Short.

Returns all N drafts in a single `ScriptDraftsArtifact`; the scorer (P5-S2)
picks the best one. N defaults to 3 and can be overridden by `getattr(state,
"max_iterations", 3)` so the factory is compatible with `IdeaToScriptState`
when the full idea_to_script graph is assembled in P5-S4/P5-S5.

Pure worker per D040/D056: takes StageState, returns WorkerOutput. All IO
(reading the ranked_ideas artifact from R2, calling the Anthropic API) is
injected via the `build_script_writer_worker` factory — the worker body carries
no hidden state.
"""

import json
from datetime import datetime, timezone
from typing import Any

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.topic_selector import RankedIdeasArtifact

_SCRIPT_WRITER_PROMPT_V1 = """\
You are a script writer for "The Housing Equation", a data-driven YouTube Shorts \
channel about American housing economics.

Write a narration script for a 60–90 second short-form video (approximately 150–200 \
words). The script must be:
- Written in plain conversational English as if spoken directly to camera
- Grounded in real data or economic patterns (cite at least one specific statistic, \
trend, or historic fact)
- Built around the supplied title and narrative angle
- Free of filler phrases ("Hey guys", "Don't forget to like", etc.)
- Structured with a hook in the first 10 seconds, a data-driven middle, and a punchy \
closing line

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
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_SCRIPT_WRITER_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


class ScriptDraft(BaseModel):
    """One narration script draft produced by the script writer."""

    draft_number: int
    script: str


class ScriptDraftsArtifact(BaseModel):
    """Artifact body produced by the script writer worker."""

    niche: str
    idea_title: str
    idea_angle: str
    drafts: list[ScriptDraft]
    generated_at: datetime


def build_script_writer_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
    n_drafts: int = 3,
) -> WorkerNode:
    """Return a script writer WorkerNode bound to storage and the Anthropic API key.

    Reads `state.artifacts["ranked_ideas"]` → extracts selected topic (title + angle +
    niche) → calls Claude Sonnet (script_writer@v1) for N draft scripts → returns
    `ScriptDraftsArtifact`.

    N is resolved as `getattr(state, "max_iterations", n_drafts)` so the factory works
    both standalone (uses the `n_drafts` default) and inside `IdeaToScriptState` graphs
    (uses `state.max_iterations` set by the graph builder).

    Raises KeyError if `state.artifacts["ranked_ideas"]` is absent (Topic Selector must
    run first). Raises ValueError if Claude returns non-JSON or malformed draft objects.
    """

    async def script_writer(state: StageState) -> WorkerOutput:
        """Read ranked_ideas artifact, call Claude Sonnet, return ScriptDraftsArtifact."""
        ranked_key = state.artifacts.get("ranked_ideas")
        if not ranked_key:
            raise KeyError(
                "state.artifacts['ranked_ideas'] is missing"
                " — run the Topic Selector worker before Script Writer"
            )

        _, body = await read_artifact(storage, ranked_key)
        ranked_artifact = RankedIdeasArtifact.model_validate(body)

        effective_n = int(getattr(state, "max_iterations", n_drafts))

        user_message = (
            f"Niche: {ranked_artifact.niche}\n"
            f"Title: {ranked_artifact.selected.title}\n"
            f"Angle: {ranked_artifact.selected.angle}\n\n"
            f"Write {effective_n} draft variant(s)."
        )

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
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
                f"script_writer@v1 returned invalid JSON: {exc}\nRaw response: {raw_text!r}"
            ) from exc

        drafts = [ScriptDraft.model_validate(d) for d in raw_drafts]
        artifact = ScriptDraftsArtifact(
            niche=ranked_artifact.niche,
            idea_title=ranked_artifact.selected.title,
            idea_angle=ranked_artifact.selected.angle,
            drafts=drafts,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return script_writer
