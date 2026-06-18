"""Topic Generator worker (P4-S1) — `signals → candidate_topics`.

Reads the `signals` artifact produced by the Discovery worker, formats the
trending signals into a structured user message, and calls Claude Sonnet
(topic_generator@v1) to produce a list of narrative-worthy candidate video
topics for the niche.

Pure worker per D040/D056: takes StageState, returns WorkerOutput. All IO
(reading the signals artifact from R2, calling the Anthropic API) is injected
via the `build_topic_generator_worker` factory — the worker body carries no
hidden state.
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
from cf_platform.workers.discovery import SignalsArtifact

_TOPIC_GENERATOR_PROMPT_V2 = """\
You are a content strategist for a data-driven short-form video channel.

Given the channel niche and trending signals (social posts, videos, search trends), \
identify 5-10 narrative-worthy topics for 60-90 second short-form videos.

For each topic return:
- "title": a specific, clear title (not clickbait)
- "angle": one sentence describing the narrative hook and why this topic is uniquely \
interesting for viewers of this niche

Return ONLY a JSON array. No preamble, no markdown fences. Example:
[
  {
    "title": "Why Starter Homes Disappeared",
    "angle": "Show how 1980s builder incentives shifted from entry-level to luxury, \
creating today's supply gap using real price-tier data."
  }
]\
"""

TOPIC_GENERATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version="v2",
    prompt=_TOPIC_GENERATOR_PROMPT_V2,
    model="claude-sonnet-4-6",
    sampling_params={},
)


class CandidateTopic(BaseModel):
    """One narrative-worthy topic candidate produced by the topic generator."""

    title: str
    angle: str


class CandidateTopicsArtifact(BaseModel):
    """Artifact body produced by the topic generator worker."""

    niche: str
    generated_at: datetime
    topics: list[CandidateTopic]


def _format_signals(signals_artifact: SignalsArtifact) -> str:
    """Format signals into a numbered list for the Claude user message."""
    if not signals_artifact.signals:
        return "(no signals)"
    lines = [
        f"- [{s.source}] {s.title} (score {s.score:,.0f})"
        for s in signals_artifact.signals
    ]
    return "\n".join(lines)


def build_topic_generator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a topic generator WorkerNode bound to storage and the Anthropic API key.

    Reads `state.artifacts["discovery"]` → formats signals → calls Claude Sonnet
    (topic_generator@v1) → returns `CandidateTopicsArtifact` with 5-10 topics.

    Raises KeyError if `state.artifacts["discovery"]` is absent (Discovery worker must
    run first). Raises ValueError if Claude returns non-JSON or malformed topic objects.
    """

    async def topic_generator(state: StageState) -> WorkerOutput:
        """Read signals artifact, call Claude Sonnet, return CandidateTopicsArtifact."""
        signals_key = state.artifacts.get("discovery")
        if not signals_key:
            raise KeyError(
                "state.artifacts['discovery'] is missing — run the Discovery worker before Topic Generator"
            )

        _, body = await read_artifact(storage, signals_key)
        signals_artifact = SignalsArtifact.model_validate(body)

        user_message = (
            f"Niche: {signals_artifact.niche}\n\n"
            f"Signals ({len(signals_artifact.signals)} found):\n"
            f"{_format_signals(signals_artifact)}"
        )

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        response = await client.messages.create(
            model=TOPIC_GENERATOR_REGISTRATION.model,
            max_tokens=1024,
            system=TOPIC_GENERATOR_REGISTRATION.prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        try:
            raw_topics: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"topic_generator@v1 returned invalid JSON: {exc}\nRaw response: {raw_text!r}"
            ) from exc

        topics = [CandidateTopic.model_validate(t) for t in raw_topics]
        artifact = CandidateTopicsArtifact(
            niche=signals_artifact.niche,
            generated_at=datetime.now(timezone.utc),
            topics=topics,
        )
        return WorkerOutput(artifact=artifact)

    return topic_generator
