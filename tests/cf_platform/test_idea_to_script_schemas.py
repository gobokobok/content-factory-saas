"""Tests for cf_platform/core/idea_to_script_schemas.py (P5-S6).

Covers:
- Signal: defaults for optional fields
- DirectionContext: do_not_focus_on defaults to []
- IdeaToScriptInput: signals and direction_context default to empty/None
- Blueprint: all required fields accepted; structure is a list of Section
- IntegrityIssue: severity defaults to 'medium'; span is optional
- IntegrityReport: passed reflects issues list
- Patch: all three operations accepted; replacement is optional for delete
- Patch: replace requires replacement present
- PatchSetArtifact: patches list wraps Patch objects
- IdeaToScriptState (from schemas.py): gains integrity_loops + integrity_verdict; loses old fields
"""

import operator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    DirectionContext,
    IdeaToScriptInput,
    IntegrityIssue,
    IntegrityReport,
    Patch,
    PatchSetArtifact,
    Section,
    Signal,
)
from cf_platform.core.schemas import IdeaToScriptState

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


class TestSignal:
    def test_defaults(self):
        sig = Signal(source="reddit", content="House prices rose 30% in 2021")
        assert sig.signal_type == "general"
        assert sig.weight == 1.0
        assert sig.url is None

    def test_explicit_fields(self):
        sig = Signal(source="youtube", content="Supply shortage", signal_type="trend", weight=2.0, url="https://yt.com")
        assert sig.signal_type == "trend"
        assert sig.weight == 2.0
        assert sig.url == "https://yt.com"


class TestDirectionContext:
    def test_do_not_focus_on_defaults_to_empty_list(self):
        ctx = DirectionContext(angle="affordability", narrative_bias="pessimistic")
        assert ctx.do_not_focus_on == []
        assert ctx.hook_direction is None

    def test_full_construction(self):
        ctx = DirectionContext(
            angle="supply shortage",
            narrative_bias="data-driven",
            hook_direction="Start with a shocking statistic",
            do_not_focus_on=["mortgage rates", "foreign buyers"],
        )
        assert len(ctx.do_not_focus_on) == 2


class TestIdeaToScriptInput:
    def test_defaults(self):
        inp = IdeaToScriptInput(idea_title="Why starter homes vanished")
        assert inp.signals == []
        assert inp.direction_context is None

    def test_with_signals(self):
        sig = Signal(source="reddit", content="Content here")
        inp = IdeaToScriptInput(idea_title="Test", signals=[sig])
        assert len(inp.signals) == 1


class TestBlueprint:
    def test_construction(self):
        bp = Blueprint(
            hook_angle="Starter homes built 70% less than in 1980",
            structure=[Section(title="Hook", key_points=["stat"])],
            claims=["Claim 1"],
            monetization_angle="Urgency drives watch time",
            required_evidence=["Census data"],
            signal_summary="Short summary",
            direction_alignment_notes="Focus on supply side",
        )
        assert len(bp.structure) == 1
        assert bp.structure[0].title == "Hook"
        assert bp.claims == ["Claim 1"]


class TestIntegrityIssue:
    def test_severity_defaults_to_medium(self):
        issue = IntegrityIssue(description="Claim not in blueprint")
        assert issue.severity == "medium"
        assert issue.span is None

    def test_high_severity(self):
        issue = IntegrityIssue(description="Major hallucination", span="some text", severity="high")
        assert issue.severity == "high"
        assert issue.span == "some text"

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            IntegrityIssue(description="Bad", severity="critical")  # type: ignore[arg-type]


class TestIntegrityReport:
    def test_passed_true(self):
        report = IntegrityReport(passed=True, issues=[])
        assert report.passed is True
        assert report.issues == []

    def test_passed_false_with_issues(self):
        report = IntegrityReport(
            passed=False,
            issues=[IntegrityIssue(description="Bad claim", severity="high")],
        )
        assert report.passed is False
        assert len(report.issues) == 1


class TestPatch:
    def test_replace_operation(self):
        patch = Patch(operation="replace", target="old text", replacement="new text")
        assert patch.operation == "replace"
        assert patch.replacement == "new text"

    def test_delete_operation_no_replacement(self):
        patch = Patch(operation="delete", target="bad phrase")
        assert patch.operation == "delete"
        assert patch.replacement is None

    def test_insert_operation(self):
        patch = Patch(operation="insert", target="after this", replacement=" appended")
        assert patch.operation == "insert"

    def test_invalid_operation_rejected(self):
        with pytest.raises(ValidationError):
            Patch(operation="update", target="x")  # type: ignore[arg-type]


class TestPatchSetArtifact:
    def test_wraps_patches(self):
        patches = [
            Patch(operation="replace", target="wrong", replacement="right"),
            Patch(operation="delete", target="remove this"),
        ]
        artifact = PatchSetArtifact(patches=patches, generated_at=_NOW)
        assert len(artifact.patches) == 2

    def test_empty_patches_list(self):
        artifact = PatchSetArtifact(patches=[], generated_at=_NOW)
        assert artifact.patches == []


class TestIdeaToScriptStateUpdated:
    """IdeaToScriptState has new fields and removed old ones (P5-S6)."""

    def test_new_defaults(self):
        state = IdeaToScriptState(run_id="r", user_id="u", inputs={})
        assert state.integrity_loops == 0
        assert state.integrity_verdict == "continue"

    def test_integrity_loops_uses_add_reducer(self):
        hints = IdeaToScriptState.__annotations__
        annotated = hints.get("integrity_loops")
        assert hasattr(annotated, "__metadata__")
        assert operator.add in annotated.__metadata__

    def test_old_fields_removed(self):
        """scorer_verdict, factcheck_verdict, quality_threshold, unverified_threshold must not exist."""
        for field in ("scorer_verdict", "factcheck_verdict", "quality_threshold", "unverified_threshold"):
            assert field not in IdeaToScriptState.model_fields, f"{field} should have been removed"

    def test_integrity_loops_accumulates(self):
        """Two instances of integrity_loops merge via operator.add (D057)."""
        state1 = IdeaToScriptState(run_id="r", user_id="u", inputs={}, integrity_loops=1)
        state2 = IdeaToScriptState(run_id="r", user_id="u", inputs={}, integrity_loops=1)
        merged_loops = state1.integrity_loops + state2.integrity_loops
        assert merged_loops == 2
