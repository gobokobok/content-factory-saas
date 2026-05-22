"""Pydantic schemas for all pipeline data structures."""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator


PIPELINE_STEPS = (
    "storyboard",
    "asset_manifest",
    "asset_acquisition",
    "ffmpeg_script",
    "render",
)


class StepStatus(str, Enum):
    """Possible states for a single pipeline step in run_log.json."""

    pending = "pending"
    complete = "complete"
    failed = "failed"


class StepLog(BaseModel):
    """State record for one pipeline step."""

    status: StepStatus = StepStatus.pending
    completed_at: Optional[str] = None
    error: Optional[str] = None
    output_url: Optional[str] = None


class RunLog(BaseModel):
    """Top-level run_log.json schema persisted to Drive after each step."""

    run_id: str
    created_at: str
    steps: dict[str, StepLog]


class RunCreateRequest(BaseModel):
    """Request body for POST /runs."""

    slug: str

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Slug must be lowercase letters, digits, and hyphens with no leading/trailing hyphens."""
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", v):
            raise ValueError(
                "slug must contain only lowercase letters, digits, and hyphens, "
                "and must not start or end with a hyphen"
            )
        return v


class RunCreateResponse(BaseModel):
    """Response body for POST /runs."""

    run_id: str
    storage_prefix: str
