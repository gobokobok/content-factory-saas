"""Pydantic models for the visual_treatment artifact (P11-S1).

Produced by VisualDirectorWorker; consumed by AcquisitionWorker.
R2 path: runs/{run_id}/visual_treatment@v1.json
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Controlled vocabulary for shot types — used in prompt and validation.
SHOT_TYPE_VOCABULARY = frozenset([
    "portrait",
    "wide",
    "macro_science",
    "diagram",
    "archive",
    "drone",
    "lifestyle",
    "screen_recording",
    "animation",
    "infographic",
])

ShotType = Literal[
    "portrait",
    "wide",
    "macro_science",
    "diagram",
    "archive",
    "drone",
    "lifestyle",
    "screen_recording",
    "animation",
    "infographic",
]

AssetClass = Literal["person_photo", "stock", "archive_image", "diagram", "animation"]

PreferredSource = Literal["wikimedia", "pexels", "pixabay", "any"]

MotionPreset = Literal["ken_burns_in", "ken_burns_out", "slow_push", "static", "none"]

TransitionType = Literal["cut", "dissolve", "fade"]


class SceneVisualPlan(BaseModel):
    """Visual specification for one scene — produced by the Visual Director."""

    scene: int = Field(..., description="Scene number (1-indexed, matches storyboard scene order).")
    visual_intent: str = Field(..., description="One-sentence direction: what the visual should communicate.")
    shot_type: ShotType
    era: str = Field(default="contemporary", description="Era label, e.g. 'contemporary', '1930s', 'timeless'.")
    asset_class: AssetClass = Field(default="stock")
    preferred_source: PreferredSource = Field(default="any")
    search_terms: list[str] = Field(
        default_factory=list,
        description="Ordered search queries. AcquisitionWorker tries these before storyboard STK queries.",
    )
    avoid: list[str] = Field(
        default_factory=list,
        description="Visual concepts to exclude — passed as context to acquisition logging; not enforced by the search API.",
    )
    motion: MotionPreset = Field(default="none")
    transition_from_prev: TransitionType = Field(default="cut")


class DiversityPlan(BaseModel):
    """Shot-type diversity guidance for the run."""

    shot_type_sequence: list[str] = Field(
        default_factory=list,
        description="Planned high-level sequence of shot types across the run.",
    )
    notes: str = Field(default="", description="Free-text diversity notes from the Visual Director.")


class VisualTreatment(BaseModel):
    """Full visual treatment artifact for a run — output of VisualDirectorWorker."""

    global_style: str = Field(default="", description="One-line stylistic direction for the whole run.")
    shot_sequence_plan: str = Field(default="", description="Macro shot-type arc, e.g. 'wide → close → archive → portrait'.")
    scenes: list[SceneVisualPlan] = Field(default_factory=list)
    diversity_plan: DiversityPlan = Field(default_factory=DiversityPlan)
    prompt_version: str = Field(default="v0.1")
    diversity_score: Optional[float] = Field(
        default=None,
        description="unique_shot_types / total_scenes — computed post-validation.",
    )
