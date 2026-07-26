"""Pydantic schemas for all pipeline data structures."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PIPELINE_STEPS = (
    "alignment",
    "storyboard",
    "asset_manifest",
    "asset_acquisition",
    "ffmpeg_script",
    "render",
    "metadata",
)


class StepStatus(str, Enum):  # noqa: UP042 — StrEnum changes str() output; run_log.json serialization relies on current behavior
    """Possible states for a single pipeline step in run_log.json."""

    pending = "pending"
    complete = "complete"
    failed = "failed"


class StepLog(BaseModel):
    """State record for one pipeline step."""

    status: StepStatus = StepStatus.pending
    completed_at: str | None = None
    error: str | None = None
    output_url: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class RunLog(BaseModel):
    """Top-level run_log.json schema persisted to Drive after each step."""

    run_id: str
    created_at: str
    project_name: str | None = None
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
    project_name: str | None = None
    steps: dict[str, str]


class RunListResponse(BaseModel):
    """Response body for GET /runs."""

    runs: list[RunSummary]


class ArtifactResponse(BaseModel):
    """Response body for GET /runs/{run_id}/artifact/{step}."""

    step: str
    content_type: str
    content: Any | None = None
    url: str | None = None


# ── Storyboard schemas ────────────────────────────────────────────────────────


class GlobalContext(BaseModel):
    """Top-level semantic context for the full video — guides acquisition domain filtering."""

    topic: str
    domain: str
    subtopics: list[str] = []
    avoid_globally: list[str] = []
    tone: str = ""


class SemanticContext(BaseModel):
    """Per-scene semantic enrichment — provides domain-qualified acquisition signals."""

    primary_concept: str = ""
    domain_qualifier: str = ""
    avoid: list[str] = []
    visual_tags: list[str] = []
    entity_type: Literal["person", "historic_event", "location", "organization"] | None = None


class VisualPrompts(BaseModel):
    """Three-tier visual prompt hierarchy for a storyboard scene (v1 — deprecated alias)."""

    primary_stk: str
    fallback_stk: str
    ai_generate: str


class LowerThirdSpec(BaseModel):
    """Specification for a lower-third name/title overlay on a Character scene."""

    name: str
    title: str | None = None
    # Shifts caption baseline up so subtitles don't overlap the lower-third band.
    caption_y_override: int = 1540


class OnScreenTextOverlay(BaseModel):
    """A timed text overlay (stat, date, or lower-third label) rendered over the scene."""

    text: str
    type: Literal["stat", "date", "lower_third", "person", "label"]
    # FFmpeg between(t,{offset},{offset+duration}) expression controlling display window.
    enable_expr: str


class SceneRenderOptions(BaseModel):
    """Render decisions computed by the storyboard reviewer and consumed by RenderWorker."""

    film_look: bool = False
    lower_third: LowerThirdSpec | None = None
    on_screen_text_overlay: OnScreenTextOverlay | None = None


class StoryboardScene(BaseModel):
    """A single scene in the production storyboard."""

    scene: str
    clip_type: Literal["hard_cut", "still_with_motion", "animated"]
    duration_s: float
    voiceover_line: str
    # v2 flat query fields (P9-S1). Populated from visual_prompts by validator when loading v1 JSON.
    primary_stk: str = ""
    context_stk: str = ""
    concept_stk: str = ""
    # v1 nested struct — kept Optional for backward compat with existing R2 storyboards.
    visual_prompts: VisualPrompts | None = None
    motion_effect: str | None = None
    on_screen_text: str | None = None
    # v2 text overlay type; paired with on_screen_text.
    on_screen_text_type: Literal["stat", "date", "lower_third", "person", "label"] | None = None
    sfx: str = ""
    sfx_timing: str = ""

    @field_validator("sfx", "sfx_timing", mode="before")
    @classmethod
    def _coerce_sfx_none(cls, v: Any) -> str:
        return v if v is not None else ""
    # Segment classification (v2). "Character" = named real person; "Event" = named
    # historical event; "B-roll" = everything else.
    segment_type: Literal["Character", "Event", "B-roll"] = "B-roll"
    # Render decisions written by the storyboard reviewer (P9-S2).
    render_options: SceneRenderOptions | None = None
    # Operator-set acquisition strategy — persisted in storyboard so it survives
    # before the manifest exists.  None means "derive from clip_type at manifest build".
    asset_mode: Literal["stock", "ai_generated"] | None = None
    # Deprecated alias — segment_type=Event is the v2 signal. Kept for R2 backward compat.
    historic: bool = False
    # Set by the storyboard prompt (v0.10) when scene depicts a named real person.
    # Routes acquisition to wikimedia_client.fetch_person_photo first (P8-S3).
    person_name: str | None = None
    person_title: str | None = None
    # v0.13 timestamp-first fields — Claude outputs word indices; Python derives these (P9-S9).
    start_word: int | None = None
    end_word: int | None = None
    scene_start_ms: int | None = None
    scene_end_ms: int | None = None
    asset_tier: Literal["still", "still_motion", "video"] | None = None
    # Semantic enrichment (P10-S3) — per-scene domain-qualified acquisition signals.
    semantic_context: SemanticContext | None = None

    @model_validator(mode="after")
    def _backfill_flat_queries_from_visual_prompts(self) -> "StoryboardScene":
        """Populate v2 flat query fields from v1 visual_prompts when loading old storyboards."""
        if self.visual_prompts is not None:
            if not self.primary_stk:
                self.primary_stk = self.visual_prompts.primary_stk
            if not self.context_stk:
                self.context_stk = self.visual_prompts.fallback_stk
        return self


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
    # Semantic enrichment (P10-S3) — top-level domain context for the full video.
    global_context: GlobalContext | None = None


# ── Asset manifest schemas ─────────────────────────────────────────────────────


class ManifestEntry(BaseModel):
    """Asset requirements for a single storyboard scene."""

    scene_id: str
    clip_type: Literal["hard_cut", "still_with_motion", "animated"]
    # v1 query fields — Optional for backward compat; populated by build_manifest (legacy path).
    primary_query: str | None = None
    fallback_query: str | None = None
    ai_generate_prompt: str | None = None
    # v2 flat query fields (P9-S1) — used by native AcquisitionWorker (P9-S3).
    segment_type: str = "B-roll"
    primary_stk: str = ""
    context_stk: str = ""
    concept_stk: str = ""
    # Deprecated alias — segment_type=Event is the v2 signal. Kept for R2 backward compat.
    historic: bool = False
    status: str = "pending"
    source: str | None = None
    file_key: str | None = None
    asset_mode: Literal["stock", "ai_generated"] | None = None
    # Wikimedia CC/public-domain attribution text to store alongside the asset.
    attribution: str | None = None
    # Propagated from StoryboardScene (v0.10) — set when scene depicts a named individual.
    # Acquisition routes to wikimedia_client.fetch_person_photo first (P8-S3).
    person_name: str | None = None
    person_title: str | None = None
    # Scene duration propagated from StoryboardScene — used for video duration QA (P8-S4).
    duration_s: float = 0.0
    # QA gate results written by acquisition (P8-S4).
    qa_passed: bool | None = None
    qa_resolution_ok: bool | None = None
    qa_duration_ok: bool | None = None
    qa_clip_score: float | None = None
    fallback_used: bool = False
    # Asset tier propagated from StoryboardScene (P9-S9) — guides image-first vs video-first routing.
    asset_tier: Literal["still", "still_motion", "video"] | None = None
    # Set to True when acquisition skipped a duplicate source URL (P10-S1 deduplication).
    duplicate_avoided: bool = False
    # Semantic enrichment propagated from StoryboardScene (P10-S3).
    semantic_context: SemanticContext | None = None


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


class ManifestPatchRequest(BaseModel):
    """Request body for PATCH /runs/{run_id}/manifest."""

    scene_id: str
    field: str
    value: str


class ManifestPatchResponse(BaseModel):
    """Response body for PATCH /runs/{run_id}/manifest."""

    status: str
    scene_id: str
    field: str


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


class AcquisitionAcceptedResponse(BaseModel):
    """202 response body for POST /runs/{run_id}/assets (background task started)."""

    status: str  # always "running"
    poll_url: str


class AcquisitionStatusResponse(BaseModel):
    """Response body for GET /runs/{run_id}/assets/status."""

    status: str  # "running" | "complete" | "failed"
    acquired: int = 0
    failed: int = 0
    sources: dict[str, int] = {}
    manifest_key: str | None = None
    error: str | None = None


class AssetLinkResponse(BaseModel):
    """Response body for GET /runs/{run_id}/asset-link."""

    url: str
    expires_in: int


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
    vo_filename: str | None = None
    music_filename: str | None = None


class StoryboardResponse(BaseModel):
    """Response body for POST /runs/{run_id}/storyboard."""

    status: str
    storyboard_key: str


class StoryboardPatchRequest(BaseModel):
    """Request body for PATCH /runs/{run_id}/storyboard."""

    scene_id: str
    field: str
    value: str


class StoryboardPatchResponse(BaseModel):
    """Response body for PATCH /runs/{run_id}/storyboard."""

    status: str
    scene_id: str
    field: str


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


class RenderAcceptedResponse(BaseModel):
    """202 response body for POST /runs/{run_id}/render."""

    status: str  # always "running"
    poll_url: str


class RenderStatusResponse(BaseModel):
    """Response body for GET /runs/{run_id}/render/status."""

    status: str  # "running" | "complete" | "failed"
    progress_pct: int
    output_key: str | None = None
    error: str | None = None


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


class MusicUploadUrlRequest(BaseModel):
    """Request body for POST /runs/{run_id}/music-upload-url."""

    filename: str


class MusicUploadUrlResponse(BaseModel):
    """Response body for POST /runs/{run_id}/music-upload-url."""

    upload_url: str
    key: str


class RunLogTxtResponse(BaseModel):
    """Response body for GET /runs/{run_id}/run-log-txt."""

    content: str
    available: bool


class TTSResponse(BaseModel):
    """Response body for POST /runs/{run_id}/tts."""

    status: str
    key: str
    chunk_count: int
    duration_s: float


# ── Video settings schemas ────────────────────────────────────────────────────


class AudioSettings(BaseModel):
    """Audio mixing controls stored within settings.json — wired into ffmpeg in S11-S3."""

    music_volume: int = Field(default=15, ge=0, le=100)
    ducking_enabled: bool = False
    playback_mode: Literal["loop", "fit"] = "fit"


class VideoSettings(BaseModel):
    """Video production settings stored in settings.json and wired into the render pipeline."""

    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "16:9"
    visual_style: Literal[
        "Realistic", "Cinematic", "Cartoonish", "Documentary", "Minimalist"
    ] = "Realistic"
    subtitles: Literal["none", "TikTok", "Classic"] = "TikTok"
    audio: AudioSettings = Field(default_factory=AudioSettings)
    subject: str = ""


class VideoSettingsResponse(BaseModel):
    """Response body for GET/POST /runs/{run_id}/settings."""

    status: str
    settings: VideoSettings


# ── Publishing metadata schemas ───────────────────────────────────────────────


class PublishingMetadata(BaseModel):
    """Publishing metadata generated by Claude Haiku after render."""

    title: str
    alt_titles: list[str]
    youtube_description: str
    instagram_description: str
    hashtags: list[str]
    seo_tags: list[str]


class MetadataResponse(BaseModel):
    """Response body for POST /runs/{run_id}/metadata."""

    status: str
    metadata_key: str
