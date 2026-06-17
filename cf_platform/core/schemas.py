"""Universal platform contracts (P0-S3) — interfaces only, no runtime behavior.

Canonical spec: docs/v2_platform_plan.md §4-5. Enforces D055 (sampling params pinned
for reproducibility), D056 (worker = LangGraph node), and D057 (artifacts are truth;
state is a message bus, refs + control only — no `state_delta`).
"""

import operator
from datetime import datetime
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional, Protocol

from pydantic import BaseModel


# ── Lineage & artifacts ────────────────────────────────────────────────


class LineageEnvelope(BaseModel):
    """Pins the exact prompt/model/sampling configuration that produced an artifact (D055)."""

    run_id: str
    worker: str
    worker_version: str
    prompt_version: str
    model: str
    sampling_params: dict[str, Any] = {}
    created_at: datetime


class Artifact(BaseModel):
    """An immutable, versioned output written to R2 and indexed in Postgres."""

    name: str
    stage: str
    version: int
    run_id: str
    content_type: str = "application/json"
    r2_key: str
    lineage: LineageEnvelope
    schema_version: str = "1"


# ── Run & execution records ────────────────────────────────────────────


class RunRecord(BaseModel):
    """Top-level lifecycle record for a single platform run."""

    run_id: str
    user_id: str
    block: str
    status: Literal["created", "running", "complete", "failed"]
    inputs: dict[str, Any]
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WorkerExecution(BaseModel):
    """One row per worker execution — cost, latency, and version lineage for a run."""

    run_id: str
    worker: str
    worker_version: str
    prompt_version: str
    model: str
    sampling_params: dict[str, Any] = {}
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    status: Literal["ok", "error"]
    artifact_r2_key: Optional[str] = None
    started_at: datetime
    finished_at: datetime


# ── Worker / node contract (D056) ──────────────────────────────────────

ControlSignal = Literal["continue", "retry", "branch"]
"""Closed set of outgoing-edge routing signals; extend only via a new decision."""


class WorkerOutput(BaseModel):
    """Returned by a worker BODY. Pure — no storage knowledge, no `state_delta` (D057).

    The observability wrapper persists `artifact` and assigns the `r2_key`; the
    worker body never knows its own storage location.
    """

    artifact: BaseModel
    control: ControlSignal = "continue"


WorkerNode = Callable[["StageState"], Awaitable["WorkerOutput"]]
"""A worker IS this callable — it receives the stage state and returns a `WorkerOutput`."""


# ── State base (D057): message bus, refs + control only ────────────────


def merge_refs(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    """Additive reducer for `StageState.artifacts` — later writes are merged in, never dropped."""
    return {**a, **b}


class StageState(BaseModel):
    """Base graph state. Carries only artifact references and inputs — never artifact bodies.

    Per-stage subclasses add typed control channels (e.g. `iteration: int`) — never a
    free-form dict.
    """

    run_id: str
    user_id: str
    inputs: dict[str, Any]
    artifacts: Annotated[dict[str, str], merge_refs] = {}


# ── IO adapters (NOT workers) ───────────────────────────────────────────


class TraceEvent(BaseModel):
    """An observability record emitted by an IO adapter (D050, D057) — never an artifact."""

    run_id: str
    worker: str
    source: str
    op: str
    latency_ms: int
    cost_usd: Optional[float] = None
    status: Literal["ok", "error"]
    meta: dict[str, Any] = {}


class Signal(BaseModel):
    """A single normalized discovery signal returned by `SourceAdapter.fetch()`.

    Minimal placeholder shape — full fields designed alongside the Discovery worker (P3-S2).
    """

    source: str
    title: str
    url: Optional[str] = None
    score: float = 0.0
    meta: dict[str, Any] = {}


class SourceAdapter(Protocol):
    """Discovery IO contract (D050). Implementations emit `TraceEvent`s, never artifacts."""

    async def fetch(self, niche: str, params: dict[str, Any]) -> list[Signal]:
        """Fetch raw signals for `niche` from this source."""
        ...


# ── Per-stage StageState contracts (plan §5, P4-S4) ───────────────────


class NicheToIdeasState(StageState):
    """Stage state for the niche→ideas block (plan §5).

    Typed control channels only — no artifact bodies (D057). Artifact refs populated
    across nodes: discovery → "discovery", topic_generator → "candidate_topics",
    opportunity_scorer → "scored_topics", topic_selector → "ranked_ideas" (terminal).
    """

    mode: Literal["single", "top_n"] = "single"
    top_n: int = 3


class IdeaToScriptState(StageState):
    """Stage state for the idea→script block (plan §5, P5-S4).

    Typed control channels only — no artifact bodies (D057).

    `iteration` uses `operator.add` as its reducer so any node returning
    `{"iteration": 1}` increments the counter without overwriting the
    accumulated value. The graph (not any worker) owns this counter (D057).

    Artifact refs populated across nodes:
      script_writer    → "script_drafts"
      script_scorer    → "script_scores"
      fact_checker     → "factcheck_report"
      script_refiner   → "script_drafts"  (new version each retry)
      (terminal P5-S5) → "script"
    """

    iteration: Annotated[int, operator.add] = 0
    max_iterations: int = 3
    quality_threshold: float = 0.8
    unverified_threshold: float = 0.3
    scorer_verdict: ControlSignal = "continue"
    factcheck_verdict: ControlSignal = "continue"
