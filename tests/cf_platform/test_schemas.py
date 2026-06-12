"""Schema-validation tests for cf_platform/core/schemas.py (P0-S3). No runtime behavior."""

from datetime import datetime, timezone
from typing import Protocol

import pytest
from pydantic import BaseModel, ValidationError

from cf_platform.core.schemas import (
    Artifact,
    LineageEnvelope,
    RunRecord,
    Signal,
    SourceAdapter,
    StageState,
    TraceEvent,
    WorkerExecution,
    WorkerOutput,
    merge_refs,
)


def _now() -> datetime:
    """Fixed timestamp for test fixtures."""
    return datetime(2026, 6, 12, tzinfo=timezone.utc)


class _DummyArtifactBody(BaseModel):
    """Minimal concrete artifact payload for WorkerOutput tests."""

    value: str = "ok"


class TestLineageEnvelope:
    """LineageEnvelope pins prompt/model/sampling config for reproducibility (D055)."""

    def test_required_fields_and_sampling_params_default(self):
        """sampling_params defaults to an empty dict when not provided."""
        env = LineageEnvelope(
            run_id="run-1",
            worker="topic_generator",
            worker_version="v1",
            prompt_version="p3",
            model="claude-sonnet-4-6",
            created_at=_now(),
        )
        assert env.sampling_params == {}

    def test_sampling_params_round_trip(self):
        """sampling_params accepts arbitrary key/value pairs (D055)."""
        env = LineageEnvelope(
            run_id="run-1",
            worker="topic_generator",
            worker_version="v1",
            prompt_version="p3",
            model="claude-sonnet-4-6",
            sampling_params={"temperature": 0.7, "top_p": 0.9},
            created_at=_now(),
        )
        assert env.sampling_params == {"temperature": 0.7, "top_p": 0.9}


class TestArtifact:
    """Artifact is the immutable, versioned record written per worker execution."""

    def test_defaults_and_lineage_nesting(self):
        """content_type and schema_version default; lineage nests as LineageEnvelope."""
        artifact = Artifact(
            name="signals",
            stage="niche_to_ideas",
            version=1,
            run_id="run-1",
            r2_key="users/u1/runs/run-1/niche_to_ideas/signals@v1.json",
            lineage=LineageEnvelope(
                run_id="run-1",
                worker="discovery",
                worker_version="v1",
                prompt_version="p1",
                model="claude-haiku-4-5-20251001",
                created_at=_now(),
            ),
        )
        assert artifact.content_type == "application/json"
        assert artifact.schema_version == "1"
        assert isinstance(artifact.lineage, LineageEnvelope)


class TestRunRecord:
    """RunRecord tracks the lifecycle status of a platform run."""

    @pytest.mark.parametrize("status", ["created", "running", "complete", "failed"])
    def test_valid_status_values(self, status):
        """Each status in the closed lifecycle set is accepted."""
        run = RunRecord(
            run_id="run-1",
            user_id="user-1",
            block="niche_to_ideas",
            status=status,
            inputs={"niche": "housing"},
            created_at=_now(),
            updated_at=_now(),
        )
        assert run.status == status

    def test_invalid_status_rejected(self):
        """A status outside the closed set raises a validation error."""
        with pytest.raises(ValidationError):
            RunRecord(
                run_id="run-1",
                user_id="user-1",
                block="niche_to_ideas",
                status="paused",
                inputs={},
                created_at=_now(),
                updated_at=_now(),
            )

    def test_error_defaults_to_none(self):
        """error is optional and defaults to None for non-failed runs."""
        run = RunRecord(
            run_id="run-1",
            user_id="user-1",
            block="niche_to_ideas",
            status="created",
            inputs={},
            created_at=_now(),
            updated_at=_now(),
        )
        assert run.error is None


class TestWorkerExecution:
    """WorkerExecution records cost/latency/version lineage per execution (D055)."""

    def test_defaults(self):
        """Token, cost, and latency counters default to zero; sampling_params to {}."""
        execution = WorkerExecution(
            run_id="run-1",
            worker="topic_generator",
            worker_version="v1",
            prompt_version="p3",
            model="claude-sonnet-4-6",
            status="ok",
            started_at=_now(),
            finished_at=_now(),
        )
        assert execution.input_tokens == 0
        assert execution.output_tokens == 0
        assert execution.cost_usd == 0.0
        assert execution.latency_ms == 0
        assert execution.sampling_params == {}
        assert execution.artifact_r2_key is None

    @pytest.mark.parametrize("status", ["ok", "error"])
    def test_valid_status_values(self, status):
        """Both members of the closed status set are accepted."""
        execution = WorkerExecution(
            run_id="run-1",
            worker="topic_generator",
            worker_version="v1",
            prompt_version="p3",
            model="claude-sonnet-4-6",
            status=status,
            started_at=_now(),
            finished_at=_now(),
        )
        assert execution.status == status

    def test_invalid_status_rejected(self):
        """A status outside {"ok", "error"} raises a validation error."""
        with pytest.raises(ValidationError):
            WorkerExecution(
                run_id="run-1",
                worker="topic_generator",
                worker_version="v1",
                prompt_version="p3",
                model="claude-sonnet-4-6",
                status="timeout",
                started_at=_now(),
                finished_at=_now(),
            )


class TestWorkerOutput:
    """WorkerOutput is the pure worker-body return type (D056, D057)."""

    def test_control_defaults_to_continue(self):
        """control defaults to 'continue' when not specified."""
        output = WorkerOutput(artifact=_DummyArtifactBody())
        assert output.control == "continue"

    @pytest.mark.parametrize("control", ["continue", "retry", "branch"])
    def test_valid_control_signals(self, control):
        """Each member of the closed ControlSignal set is accepted."""
        output = WorkerOutput(artifact=_DummyArtifactBody(), control=control)
        assert output.control == control

    def test_invalid_control_signal_rejected(self):
        """A control value outside the closed set raises a validation error."""
        with pytest.raises(ValidationError):
            WorkerOutput(artifact=_DummyArtifactBody(), control="abort")

    def test_no_state_delta_field(self):
        """WorkerOutput must never carry a free-form state_delta (D057)."""
        assert "state_delta" not in WorkerOutput.model_fields


class TestMergeRefs:
    """merge_refs is the additive reducer for StageState.artifacts (D057)."""

    def test_merges_without_dropping_existing_keys(self):
        """Keys from both dicts are present; new writes do not erase prior refs."""
        existing = {"discovery": "users/u1/runs/r1/niche_to_ideas/signals@v1.json"}
        new = {"topic_generator": "users/u1/runs/r1/niche_to_ideas/candidate_topics@v1.json"}
        merged = merge_refs(existing, new)
        assert merged == {**existing, **new}

    def test_new_value_overrides_same_key(self):
        """A re-write of the same stage's artifact ref overrides the old version."""
        existing = {"discovery": "users/u1/runs/r1/niche_to_ideas/signals@v1.json"}
        new = {"discovery": "users/u1/runs/r1/niche_to_ideas/signals@v2.json"}
        assert merge_refs(existing, new) == new


class TestStageState:
    """StageState is the base graph state — refs + control only (D057)."""

    def test_artifacts_default_empty_and_holds_refs_only(self):
        """artifacts defaults to {} and stores stage-name -> r2_key string refs."""
        state = StageState(run_id="run-1", user_id="user-1", inputs={"niche": "housing"})
        assert state.artifacts == {}

        state = StageState(
            run_id="run-1",
            user_id="user-1",
            inputs={"niche": "housing"},
            artifacts={"discovery": "users/u1/runs/r1/niche_to_ideas/signals@v1.json"},
        )
        assert state.artifacts == {"discovery": "users/u1/runs/r1/niche_to_ideas/signals@v1.json"}

    def test_artifacts_field_carries_merge_refs_reducer(self):
        """The artifacts field is annotated with merge_refs for LangGraph's reducer system."""
        metadata = StageState.model_fields["artifacts"].metadata
        assert merge_refs in metadata


class TestTraceEvent:
    """TraceEvent is the IO-adapter observability record (D050, D057) — never an artifact."""

    @pytest.mark.parametrize("status", ["ok", "error"])
    def test_valid_status_values(self, status):
        """Both members of the closed status set are accepted."""
        event = TraceEvent(
            run_id="run-1",
            worker="discovery",
            source="reddit",
            op="fetch",
            latency_ms=120,
            status=status,
        )
        assert event.status == status

    def test_cost_usd_optional_defaults_to_none(self):
        """cost_usd is optional — most adapters have no per-call cost."""
        event = TraceEvent(
            run_id="run-1",
            worker="discovery",
            source="reddit",
            op="fetch",
            latency_ms=120,
            status="ok",
        )
        assert event.cost_usd is None
        assert event.meta == {}


class TestSignal:
    """Signal is the normalized payload returned by SourceAdapter.fetch()."""

    def test_defaults(self):
        """url, score, and meta have sensible defaults for a minimal signal."""
        signal = Signal(source="reddit", title="Housing market cools in Q2")
        assert signal.url is None
        assert signal.score == 0.0
        assert signal.meta == {}


class TestSourceAdapter:
    """SourceAdapter is a Protocol — discovery IO emits trace events, not artifacts (D050)."""

    def test_is_a_protocol_with_async_fetch(self):
        """SourceAdapter is structurally typed via Protocol and declares an async fetch method."""
        assert issubclass(SourceAdapter, Protocol)
        assert "fetch" in SourceAdapter.__dict__
