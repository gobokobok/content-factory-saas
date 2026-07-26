"""Blueprint IR schemas for the idea→script block rearchitecture (P5-S6, D058).

Domain-specific schemas kept separate from the core platform contracts in schemas.py
(D056/D057). All types here are pure Pydantic models — no runtime behaviour.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# ── Input schemas ──────────────────────────────────────────────────────


class Signal(BaseModel):
    """A content signal stub — upstream from the discovery stage (not yet wired in P5)."""

    source: str
    content: str
    signal_type: str = "general"
    weight: float = 1.0
    url: str | None = None


class DirectionContext(BaseModel):
    """Optional creative direction supplied by the operator at run time."""

    angle: str
    narrative_bias: str
    hook_direction: str | None = None
    do_not_focus_on: list[str] = []


class IdeaToScriptInput(BaseModel):
    """Typed entry point for the idea→script pipeline."""

    idea_title: str
    signals: list[Signal] = []
    direction_context: DirectionContext | None = None


# ── Intermediate IR schemas ─────────────────────────────────────────────


class NormalizedContext(BaseModel):
    """Output of context_normalization — structured framing ready for blueprint generation."""

    primary_angle: str
    evidence_summary: str
    top_signals: list[str]
    controversies: list[str]
    hook_bias: str


class Section(BaseModel):
    """One content section within a Blueprint structure."""

    title: str
    key_points: list[str]


class Blueprint(BaseModel):
    """Blueprint IR — the structured content plan produced before any script text is written.

    The blueprint constrains the generation space so the single-pass script writer
    has a clear structure to follow, reducing first-pass failures (D058).

    `math_derivations` holds step-by-step computations for every numerical claim
    (e.g. compound-interest formulas, scaling calculations). The script generator
    must use these exact figures rather than recalling numbers from training data.
    """

    hook_angle: str
    structure: list[Section]
    claims: list[str]
    monetization_angle: str
    required_evidence: list[str]
    signal_summary: str
    direction_alignment_notes: str
    math_derivations: list[str] = []


class EvaluationArtifact(BaseModel):
    """Output of the evaluation node — combined fact-check + score + alignment in one call."""

    score: float  # 0–10 overall blueprint quality
    factual_corrections: list[str]  # corrections to blueprint.claims
    alignment_notes: str  # replacement for blueprint.direction_alignment_notes
    evidence_additions: list[str]  # additional items to append to blueprint.required_evidence
    passed: bool  # True when score >= 7.0 (informational — no hard gate on this node)
    notes: str


class HookVariantsArtifact(BaseModel):
    """Three hook variants produced by hook_generation."""

    hooks: list[str]
    generated_at: datetime


class SelectedHookArtifact(BaseModel):
    """The single hook chosen by hook_selection."""

    hook: str
    generated_at: datetime


class GeneratedScriptArtifact(BaseModel):
    """Artifact body from script_generation (and apply_patch after repair)."""

    idea_title: str
    niche: str | None
    script: str
    word_count: int
    target_duration_seconds: int
    generated_at: datetime


# ── Integrity repair schemas ────────────────────────────────────────────


class IntegrityIssue(BaseModel):
    """One identified hallucination, inconsistency, or structure violation."""

    description: str
    span: str | None = None  # verbatim text excerpt containing the issue
    severity: Literal["low", "medium", "high"] = "medium"


class IntegrityReport(BaseModel):
    """Output of integrity_check — hallucination / consistency / structure assessment."""

    passed: bool
    issues: list[IntegrityIssue]


class Patch(BaseModel):
    """A targeted, machine-applicable edit instruction for apply_patch.

    `target` must be verbatim text found in the script. `replacement` is required
    for 'replace' and 'insert'; omit (or None) for 'delete'.
    """

    operation: Literal["replace", "insert", "delete"]
    target: str
    replacement: str | None = None


class PatchSetArtifact(BaseModel):
    """Artifact body from patch_generator — list of targeted script edits."""

    patches: list[Patch]
    generated_at: datetime


# ── Narrative lens schemas ──────────────────────────────────────────────


class NarrativeLens(BaseModel):
    """Output of the narrative_lens node — storytelling reframings of verified blueprint facts.

    The Narrative Lens Worker owns storytelling; it MUST NOT create facts (D059).
    Every angle must be derivable solely from the blueprint claims and evaluation
    corrections passed to it. No new entities, numbers, studies, or comparisons allowed.
    """

    identity_angle: str
    contrarian_angle: str
    philosophical_angle: str
    emotional_angle: str
    story_devices: list[str]


# ── Terminal output schema ──────────────────────────────────────────────


class IdeaToScriptOutput(BaseModel):
    """High-level summary of a completed idea→script run (for external consumers)."""

    script: str
    blueprint: Blueprint
    integrity_report: IntegrityReport
    cost_meta: dict
    version: str
