"""Opportunity Scoring worker (P4-S2) — `candidate_topics → scored_topics`.

Reads the `candidate_topics` artifact produced by the Topic Generator, then calls
Claude Sonnet 4.6 with adaptive thinking to score each topic across 7 axes plus
a final composite score.

Adaptive thinking (thinking: {type: "adaptive"}) is required here because the
subjective axes (emotional_trigger, evergreen_potential) need internal CoT before
scoring — flat LLM scoring without reasoning produces sycophantic, uncalibrated
scores that degrade everything downstream (P4 model rationale).

Pure worker per D040/D056: takes StageState, returns WorkerOutput. All IO is
injected via the `build_opportunity_scorer_worker` factory.
"""

import json
from datetime import UTC, datetime
from typing import Any

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.topic_generator import CandidateTopicsArtifact

_OPPORTUNITY_SCORER_PROMPT_V2 = """\
You are an opportunity scorer for a data-driven short-form video channel.

You will be given the channel niche and a list of candidate video topics. Score each \
topic on the following axes from 1.0 to 10.0. Think carefully before assigning each \
score — avoid clustering scores near 7–8; use the full range.

Axes:
1. novelty — How fresh and underreported is this angle? \
1 = stale/overdone, 10 = original insight not yet covered
2. audience_relevance — How relevant is this to viewers of the stated niche? \
1 = peripheral, 10 = core concern
3. emotional_trigger — How strongly does this topic provoke a visceral reaction \
(anxiety, hope, anger, curiosity)? 1 = flat/neutral, 10 = high emotional charge
4. search_demand — How much active search interest does this topic have right now? \
1 = niche/obscure, 10 = mass search volume
5. competition — How saturated is YouTube with similar content? \
1 = extremely saturated (avoid), 10 = very little competition (opportunity)
6. evergreen_potential — Will this topic remain relevant 6–12 months from now? \
1 = ephemeral/news-driven, 10 = timeless principle
7. monetization_relevance — How likely is this to attract relevant ad spend for the \
niche? 1 = low advertiser appeal, 10 = very high
8. final_score — Weighted overall opportunity score. \
Apply these weights: audience_relevance ×2, emotional_trigger ×1.5, \
competition ×1.5, novelty ×1, search_demand ×1, evergreen_potential ×1, \
monetization_relevance ×0.5. Normalize the result to a 1–10 scale.

Return ONLY a JSON array with one object per input topic, preserving the original \
title and angle fields. No preamble, no markdown fences, no commentary. Example:
[
  {
    "title": "Why Starter Homes Disappeared",
    "angle": "Show how 1980s builder incentives shifted from entry-level to luxury.",
    "novelty": 8.5,
    "audience_relevance": 9.0,
    "emotional_trigger": 7.5,
    "search_demand": 8.0,
    "competition": 5.0,
    "evergreen_potential": 7.0,
    "monetization_relevance": 6.0,
    "final_score": 7.8
  }
]\
"""

OPPORTUNITY_SCORER_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version="v2",
    prompt=_OPPORTUNITY_SCORER_PROMPT_V2,
    model="claude-sonnet-4-6",
    sampling_params={"thinking": {"type": "adaptive"}, "max_tokens": 16384},
)


class TopicScore(BaseModel):
    """One scored topic — original title/angle preserved alongside all 7 axis scores."""

    title: str
    angle: str
    novelty: float
    audience_relevance: float
    emotional_trigger: float
    search_demand: float
    competition: float
    evergreen_potential: float
    monetization_relevance: float
    final_score: float


class ScoredTopicsArtifact(BaseModel):
    """Artifact body produced by the opportunity scorer worker."""

    niche: str
    generated_at: datetime
    scored_topics: list[TopicScore]


def _extract_text_block(content: list[Any]) -> str:
    """Return the text from the first TextBlock in a response content list.

    Adaptive thinking prepends a ThinkingBlock; this filters to the TextBlock
    that contains the JSON output.
    """
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise ValueError(
        "opportunity_scorer@v1: no text block found in Claude response content"
    )



def build_opportunity_scorer_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return an opportunity scorer WorkerNode bound to storage and the Anthropic API key.

    Reads `state.artifacts["candidate_topics"]` → calls Claude Sonnet 4.6 with
    adaptive thinking → filters TextBlock from response.content → parses JSON →
    returns `ScoredTopicsArtifact` with all 7 axis scores + final_score per topic.

    Raises KeyError if `state.artifacts["candidate_topics"]` is absent (Topic
    Generator must run first). Raises ValueError if Claude returns no text block or
    non-JSON / malformed score objects.
    """

    async def opportunity_scorer(state: StageState) -> WorkerOutput:
        """Read candidate_topics artifact, call Claude Sonnet, return ScoredTopicsArtifact."""
        topics_key = state.artifacts.get("candidate_topics")
        if not topics_key:
            raise KeyError(
                "state.artifacts['candidate_topics'] is missing"
                " — run the Topic Generator worker before Opportunity Scorer"
            )

        _, body = await read_artifact(storage, topics_key)
        topics_artifact = CandidateTopicsArtifact.model_validate(body)

        topics_lines = "\n".join(
            f'{i + 1}. "{t.title}" — {t.angle}'
            for i, t in enumerate(topics_artifact.topics)
        )
        user_message = (
            f"Niche: {topics_artifact.niche}\n\n"
            f"Candidate topics ({len(topics_artifact.topics)}):\n"
            f"{topics_lines}"
        )

        # max_tokens covers thinking + output combined. Adaptive thinking can consume
        # 6000–12000 tokens; 16384 ensures enough headroom for the JSON output.
        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=120.0)
        response = await client.messages.create(
            model=OPPORTUNITY_SCORER_REGISTRATION.model,
            max_tokens=16384,
            thinking={"type": "adaptive"},
            system=OPPORTUNITY_SCORER_REGISTRATION.prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(_extract_text_block(response.content))
        try:
            raw_scores: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"opportunity_scorer@v1 returned invalid JSON: {exc}"
                f"\nRaw response: {raw_text!r}"
            ) from exc

        scored_topics = [TopicScore.model_validate(s) for s in raw_scores]
        artifact = ScoredTopicsArtifact(
            niche=topics_artifact.niche,
            generated_at=datetime.now(UTC),
            scored_topics=scored_topics,
        )
        return WorkerOutput(artifact=artifact)

    return opportunity_scorer
