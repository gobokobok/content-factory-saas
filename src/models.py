"""Pydantic schemas for all pipeline data structures."""

import re
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


PIPELINE_STEPS = (
    "alignment",
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
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


class RunLog(BaseModel):
    """Top-level run_log.json schema persisted to Drive after each step."""

    run_id: str
    created_at: str
    project_name: Optional[str] = None
    steps: dict[str, StepLog]


class RunCreateRequest(BaseModel):
    """Request body for POST /runs."""

    project_name: str

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, v: str) -> str:
        """Project name must be non-empty and at most 120 characters."""
        v = v.strip()
        if not v:
            raise ValueError("project_name must not be empty")
        if len(v) > 120:
            raise ValueError("project_name must be at most 120 characters")
        return v


class RunCreateResponse(BaseModel):
    """Response body for POST /runs."""

    run_id: str
    project_name: str
    storage_prefix: str


class RunSummary(BaseModel):
    """Summary of a single run returned by GET /runs."""

    run_id: str
    created_at: str
    project_name: Optional[str] = None
    steps: dict[str, str]


class RunListResponse(BaseModel):
    """Response body for GET /runs."""

    runs: list[RunSummary]


class ArtifactResponse(BaseModel):
    """Response body for GET /runs/{run_id}/artifact/{step}."""

    step: str
    content_type: str
    content: Optional[Any] = None
    url: Optional[str] = None


# ── Storyboard schemas ────────────────────────────────────────────────────────


class VisualPrompts(BaseModel):
    """Three-tier visual prompt hierarchy for a storyboard scene."""

    primary_stk: str
    fallback_stk: str
    ai_generate: str


class StoryboardScene(BaseModel):
    """A single scene in the production storyboard."""

    scene: str
    clip_type: Literal["hard_cut", "still_with_motion", "animated"]
    duration_s: float
    voiceover_line: str
    visual_prompts: VisualPrompts
    motion_effect: Optional[str] = None
    on_screen_text: Optional[str] = None
    sfx: str
    sfx_timing: str


class StoryboardGlobal(BaseModel):
    """Global production settings applying to the full video."""

    subtitle_style: str
    bg_music: str
    visual_style: str


class StoryboardSummary(BaseModel):
    """Aggregate statistics at the end of the storyboard."""

    total_scenes: int
    total_duration_s: float
    rhythm: str


class Storyboard(BaseModel):
    """Full storyboard.json structure — top-level schema for the pipeline."""

    model_config = ConfigDict(populate_by_name=True)

    global_: StoryboardGlobal = Field(alias="global")
    scenes: list[StoryboardScene]
    summary: StoryboardSummary


# ── Asset manifest schemas ─────────────────────────────────────────────────────


class ManifestEntry(BaseModel):
    """Asset requirements for a single storyboard scene."""

    scene_id: str
    clip_type: Literal["hard_cut", "still_with_motion", "animated"]
    primary_query: str
    fallback_query: str
    ai_generate_prompt: str
    status: str = "pending"
    source: Optional[str] = None
    file_key: Optional[str] = None


class AssetManifest(BaseModel):
    """Full asset_manifest.json structure — one entry per storyboard scene."""

    run_id: str
    entries: list[ManifestEntry]


class ManifestResponse(BaseModel):
    """Response body for POST /runs/{run_id}/manifest."""

    status: str
    manifest_key: str
    scene_count: int
    clip_type_breakdown: dict[str, int]


class PexelsAcquireResult(BaseModel):
    """Result of a successful Pexels asset acquisition for one scene."""

    scene_id: str
    source: Literal["pexels"]
    file_key: str
    status: str = "acquired"


class ReplicateAcquireResult(BaseModel):
    """Result of a successful Replicate/Flux image generation for one scene."""

    scene_id: str
    source: Literal["replicate"] = "replicate"
    file_key: str
    status: str = "acquired"


class AcquisitionResponse(BaseModel):
    """Response body for POST /runs/{run_id}/assets."""

    status: str
    acquired: int
    failed: int
    sources: dict[str, int]
    manifest_key: str


class StoryboardRequest(BaseModel):
    """Request body for POST /runs/{run_id}/storyboard."""

    script: str = ""


class DraftRequest(BaseModel):
    """Request body for POST /runs/{run_id}/draft."""

    project_name: str
    script: str


class DraftResponse(BaseModel):
    """Response body for POST/GET /runs/{run_id}/draft."""

    status: str
    project_name: str
    script: str
    vo_filename: Optional[str] = None


class StoryboardResponse(BaseModel):
    """Response body for POST /runs/{run_id}/storyboard."""

    status: str
    storyboard_key: str


class FFmpegScriptResponse(BaseModel):
    """Response body for POST /runs/{run_id}/ffmpeg-script."""

    status: str
    script_key: str


class RenderResponse(BaseModel):
    """Response body for POST /runs/{run_id}/render."""

    status: str
    output_key: str
    duration_seconds: float
    exit_code: int


class WordTimestamp(BaseModel):
    """Word-level timestamp entry produced by Deepgram alignment or proportional fallback."""

    word: str
    start_ms: int
    end_ms: int
    confidence: float


class AlignmentResponse(BaseModel):
    """Response body for POST /runs/{run_id}/alignment."""

    status: str
    alignment_key: str
    word_count: int
    used_fallback: bool


class ValidationResult(BaseModel):
    """Result of Haiku schema validation for storyboard.json."""

    valid: bool
    errors: list[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float


class VoiceoverUploadUrlRequest(BaseModel):
    """Request body for POST /runs/{run_id}/voiceover-upload-url."""

    filename: str


class VoiceoverUploadUrlResponse(BaseModel):
    """Response body for POST /runs/{run_id}/voiceover-upload-url."""

    upload_url: str
    key: str


class RunLogTxtResponse(BaseModel):
    """Response body for GET /runs/{run_id}/run-log-txt."""

    content: str
    available: bool
