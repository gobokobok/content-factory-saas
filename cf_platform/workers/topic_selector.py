"""Topic Selector worker (P4-S3) — `scored_topics → ranked_ideas`.

Reads the `scored_topics` artifact produced by the Opportunity Scorer, sorts topics
by `final_score` descending (ties broken by title for determinism), picks the top
result as `selected` and the rest as `alternatives`, then emits a `ranked_ideas`
artifact.

No LLM call — pure deterministic selection. The `mode` routing decision ("single"
vs "top_n") is a conditional edge in the niche_to_ideas StateGraph (P4-S4), not
logic inside this worker (D056). The worker reads `mode` from state only to carry
it into the artifact for downstream consumers.

Pure worker per D040/D056: takes StageState, returns WorkerOutput. All IO is
injected via the `build_topic_selector_worker` factory.
"""

from datetime import datetime, timezone

from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.opportunity_scorer import ScoredTopicsArtifact, TopicScore

TOPIC_SELECTOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",
    model="none",
    sampling_params={},
)


class RankedIdeasArtifact(BaseModel):
    """Artifact body produced by the topic selector worker."""

    niche: str
    generated_at: datetime
    selected: TopicScore
    alternatives: list[TopicScore]
    mode: str


def build_topic_selector_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a topic selector WorkerNode bound to storage.

    Reads `state.artifacts["scored_topics"]` → sorts by `final_score` descending
    (ties by title ascending for determinism) → sets `selected` to the top topic and
    `alternatives` to the rest → returns `RankedIdeasArtifact`.

    Raises KeyError if `state.artifacts["scored_topics"]` is absent (Opportunity
    Scorer must run first). Raises ValueError if `scored_topics` contains no topics.
    """

    async def topic_selector(state: StageState) -> WorkerOutput:
        """Read scored_topics artifact, sort by final_score, emit ranked_ideas artifact."""
        scored_key = state.artifacts.get("scored_topics")
        if not scored_key:
            raise KeyError(
                "state.artifacts['scored_topics'] is missing"
                " — run the Opportunity Scorer worker before Topic Selector"
            )

        _, body = await read_artifact(storage, scored_key)
        scored_artifact = ScoredTopicsArtifact.model_validate(body)

        if not scored_artifact.scored_topics:
            raise ValueError(
                "topic_selector: scored_topics artifact contains no topics to select from"
            )

        sorted_topics: list[TopicScore] = sorted(
            scored_artifact.scored_topics,
            key=lambda t: (-t.final_score, t.title),
        )

        mode: str = getattr(state, "mode", "single")

        artifact = RankedIdeasArtifact(
            niche=scored_artifact.niche,
            generated_at=datetime.now(timezone.utc),
            selected=sorted_topics[0],
            alternatives=sorted_topics[1:],
            mode=mode,
        )
        return WorkerOutput(artifact=artifact)

    return topic_selector
