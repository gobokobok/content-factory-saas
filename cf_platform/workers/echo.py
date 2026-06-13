"""Echo worker (P1-S6) — trivial worker proving the full Worker=Node spine end-to-end.

Used by `POST /platform/echo` (Sprint P1 human touchpoint): the worker body is pure
(D040/D056) and never sees its own r2_key — the observability wrapper (P1-S5) persists
its output and records the WorkerExecution.
"""

from pydantic import BaseModel

from cf_platform.core.schemas import StageState, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration


class EchoArtifact(BaseModel):
    """Artifact body produced by the echo worker."""

    message: str


async def echo_worker(state: StageState) -> WorkerOutput:
    """Pure worker — echoes state.inputs['message'] back as an EchoArtifact."""
    return WorkerOutput(artifact=EchoArtifact(message=state.inputs["message"]))


ECHO_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="echo prompt v1",
    model="none",
    sampling_params={},
)
