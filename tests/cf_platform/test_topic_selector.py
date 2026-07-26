"""Tests for the topic selector worker (P4-S3).

Covers:
- Happy path: scored_topics artifact → ranked_ideas with correct selected/alternatives
- Single topic: selected set, alternatives empty
- Empty topics list: ValueError raised
- Missing scored_topics key in state: KeyError raised
- Sorting: highest final_score becomes selected; ties broken by title ascending
- mode read from state (default "single", custom via getattr)
- Niche propagated into RankedIdeasArtifact from source artifact
- Registration pins: model="none", worker_version, prompt_version
- build_topic_selector_worker returns a callable
"""

from datetime import UTC, datetime

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.opportunity_scorer import ScoredTopicsArtifact, TopicScore
from cf_platform.workers.topic_selector import (
    TOPIC_SELECTOR_REGISTRATION,
    RankedIdeasArtifact,
    build_topic_selector_worker,
)


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="opportunity_scorer",
        worker_version="1.0.0",
        prompt_version="v1",
        model="claude-sonnet-4-6",
        created_at=datetime.now(UTC),
    )


def _make_topic(title: str, final_score: float, **kwargs) -> TopicScore:
    defaults = dict(
        angle=f"Angle for {title}",
        novelty=5.0,
        audience_relevance=5.0,
        emotional_trigger=5.0,
        search_demand=5.0,
        competition=5.0,
        evergreen_potential=5.0,
        monetization_relevance=5.0,
    )
    defaults.update(kwargs)
    return TopicScore(title=title, final_score=final_score, **defaults)


async def _seed_scored_topics(
    storage: InMemoryArtifactStorage,
    topics: list[TopicScore],
    niche: str = "starter homes",
    run_id: str = "run-1",
    user_id: str = "user-1",
) -> str:
    """Write a ScoredTopicsArtifact to storage and return its r2_key."""
    artifact_body = ScoredTopicsArtifact(
        niche=niche,
        generated_at=datetime.now(UTC),
        scored_topics=topics,
    )
    artifact = await write_artifact(
        storage,
        artifact_body,
        name="scored_topics",
        stage="scored_topics",
        run_id=run_id,
        user_id=user_id,
        lineage=_lineage(run_id),
    )
    return artifact.r2_key


def _state(artifacts: dict, **extra) -> StageState:
    """Build a StageState with optional extra attributes (e.g. mode) via subclass."""
    if extra:

        class _ExtendedState(StageState):
            pass

        obj = _ExtendedState(
            run_id="run-1",
            user_id="user-1",
            inputs={},
            artifacts=artifacts,
        )
        for k, v in extra.items():
            object.__setattr__(obj, k, v)
        return obj

    return StageState(
        run_id="run-1",
        user_id="user-1",
        inputs={},
        artifacts=artifacts,
    )


@pytest.mark.asyncio
async def test_happy_path_selects_highest_final_score():
    """Top-scored topic becomes selected; rest become alternatives in score order."""
    storage = InMemoryArtifactStorage()
    topics = [
        _make_topic("Second Best", final_score=7.0),
        _make_topic("Best Topic", final_score=9.0),
        _make_topic("Third Place", final_score=5.5),
    ]
    key = await _seed_scored_topics(storage, topics)
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.selected.title == "Best Topic"
    assert result.selected.final_score == 9.0
    assert len(result.alternatives) == 2
    assert result.alternatives[0].title == "Second Best"
    assert result.alternatives[1].title == "Third Place"


@pytest.mark.asyncio
async def test_single_topic_alternatives_empty():
    """When only one topic exists, selected is set and alternatives is empty."""
    storage = InMemoryArtifactStorage()
    topics = [_make_topic("Only Topic", final_score=8.0)]
    key = await _seed_scored_topics(storage, topics)
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.selected.title == "Only Topic"
    assert result.alternatives == []


@pytest.mark.asyncio
async def test_missing_scored_topics_key_raises_key_error():
    """KeyError raised when scored_topics is absent from state.artifacts."""
    storage = InMemoryArtifactStorage()
    worker = build_topic_selector_worker(storage)

    with pytest.raises(KeyError, match="scored_topics"):
        await worker(_state({}))


@pytest.mark.asyncio
async def test_empty_topics_list_raises_value_error():
    """ValueError raised when scored_topics artifact contains no topics."""
    storage = InMemoryArtifactStorage()
    key = await _seed_scored_topics(storage, topics=[])
    worker = build_topic_selector_worker(storage)

    with pytest.raises(ValueError, match="no topics"):
        await worker(_state({"scored_topics": key}))


@pytest.mark.asyncio
async def test_tie_broken_by_title_ascending():
    """When final_scores are equal, topics are ordered by title ascending."""
    storage = InMemoryArtifactStorage()
    topics = [
        _make_topic("Zebra Topic", final_score=7.0),
        _make_topic("Alpha Topic", final_score=7.0),
        _make_topic("Middle Topic", final_score=7.0),
    ]
    key = await _seed_scored_topics(storage, topics)
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.selected.title == "Alpha Topic"
    assert result.alternatives[0].title == "Middle Topic"
    assert result.alternatives[1].title == "Zebra Topic"


@pytest.mark.asyncio
async def test_mode_defaults_to_single():
    """mode in artifact defaults to 'single' when not on state."""
    storage = InMemoryArtifactStorage()
    key = await _seed_scored_topics(storage, [_make_topic("T", final_score=8.0)])
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.mode == "single"


@pytest.mark.asyncio
async def test_mode_read_from_state():
    """mode is read from state when present (e.g. NicheToIdeasState.mode)."""
    storage = InMemoryArtifactStorage()
    key = await _seed_scored_topics(storage, [_make_topic("T", final_score=8.0)])
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}, mode="top_n"))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.mode == "top_n"


@pytest.mark.asyncio
async def test_niche_propagated_from_source_artifact():
    """niche from ScoredTopicsArtifact is carried into RankedIdeasArtifact."""
    storage = InMemoryArtifactStorage()
    key = await _seed_scored_topics(
        storage,
        [_make_topic("Topic", final_score=7.0)],
        niche="luxury condos",
    )
    worker = build_topic_selector_worker(storage)

    output = await worker(_state({"scored_topics": key}))

    result = RankedIdeasArtifact.model_validate(output.artifact.model_dump())
    assert result.niche == "luxury condos"


def test_registration_pins():
    """Registration has model='none', worker_version='1.0.0', prompt_version='v1'."""
    assert TOPIC_SELECTOR_REGISTRATION.model == "none"
    assert TOPIC_SELECTOR_REGISTRATION.worker_version == "1.0.0"
    assert TOPIC_SELECTOR_REGISTRATION.prompt_version == "v1"


def test_build_returns_callable():
    """build_topic_selector_worker returns a callable WorkerNode."""
    storage = InMemoryArtifactStorage()
    worker = build_topic_selector_worker(storage)
    assert callable(worker)
