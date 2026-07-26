"""Tests for P11-S1 — VisualDirectorWorker and related helpers."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.models.visual_treatment import (
    SHOT_TYPE_VOCABULARY,
    SceneVisualPlan,
    VisualTreatment,
)
from cf_platform.workers.visual_director_worker import (
    VISUAL_DIRECTOR_PROMPT_VERSION,
    _build_storyboard_user_message,
    _compute_diversity_score,
    _detect_diversity_violations,
    _extract_json_object,
    _parse_treatment,
    build_visual_director_worker,
)

# ── VisualTreatment model tests ───────────────────────────────────────────────

class TestVisualTreatmentModels:
    def test_scene_visual_plan_defaults(self):
        plan = SceneVisualPlan(scene=1, visual_intent="test", shot_type="wide")
        assert plan.asset_class == "stock"
        assert plan.preferred_source == "any"
        assert plan.search_terms == []
        assert plan.avoid == []
        assert plan.motion == "none"
        assert plan.transition_from_prev == "cut"

    def test_visual_treatment_defaults(self):
        vt = VisualTreatment()
        assert vt.scenes == []
        assert vt.prompt_version == VISUAL_DIRECTOR_PROMPT_VERSION
        assert vt.diversity_score is None

    def test_shot_type_vocabulary_is_non_empty(self):
        assert len(SHOT_TYPE_VOCABULARY) >= 10

    def test_visual_treatment_round_trip(self):
        plan = SceneVisualPlan(
            scene=1,
            visual_intent="Establish the setting",
            shot_type="wide",
            search_terms=["city skyline", "urban landscape"],
            avoid=["crowded market"],
        )
        vt = VisualTreatment(
            global_style="documentary",
            scenes=[plan],
            diversity_score=0.5,
        )
        data = vt.model_dump()
        restored = VisualTreatment.model_validate(data)
        assert restored.scenes[0].search_terms == ["city skyline", "urban landscape"]
        assert restored.diversity_score == 0.5


# ── _detect_diversity_violations ─────────────────────────────────────────────

def _make_scenes(shot_types: list[str]) -> list[SceneVisualPlan]:
    return [
        SceneVisualPlan(scene=i + 1, visual_intent="", shot_type=t)  # type: ignore[arg-type]
        for i, t in enumerate(shot_types)
    ]


class TestDetectDiversityViolations:
    def test_no_violation_when_all_different(self):
        scenes = _make_scenes(["wide", "portrait", "macro_science", "archive"])
        assert _detect_diversity_violations(scenes) == []

    def test_no_violation_when_two_consecutive(self):
        scenes = _make_scenes(["wide", "wide", "portrait", "macro_science"])
        assert _detect_diversity_violations(scenes) == []

    def test_violation_when_three_consecutive(self):
        scenes = _make_scenes(["wide", "wide", "wide", "portrait"])
        violations = _detect_diversity_violations(scenes)
        assert len(violations) == 1
        assert "wide" in violations[0]

    def test_violation_reports_correct_scene_range(self):
        scenes = _make_scenes(["portrait", "wide", "wide", "wide", "macro_science"])
        violations = _detect_diversity_violations(scenes)
        assert len(violations) == 1
        assert "2–4" in violations[0]

    def test_no_violation_for_fewer_than_threshold_scenes(self):
        scenes = _make_scenes(["wide", "wide"])
        assert _detect_diversity_violations(scenes) == []

    def test_multiple_violations_detected(self):
        scenes = _make_scenes(["wide", "wide", "wide", "portrait", "portrait", "portrait"])
        violations = _detect_diversity_violations(scenes)
        assert len(violations) == 2


# ── _compute_diversity_score ──────────────────────────────────────────────────

class TestComputeDiversityScore:
    def test_all_same_type(self):
        scenes = _make_scenes(["wide", "wide", "wide"])
        assert _compute_diversity_score(scenes) == round(1 / 3, 3)

    def test_all_different_types(self):
        scenes = _make_scenes(["wide", "portrait", "macro_science"])
        assert _compute_diversity_score(scenes) == 1.0

    def test_empty_scenes(self):
        assert _compute_diversity_score([]) == 0.0

    def test_single_scene(self):
        scenes = _make_scenes(["archive"])
        assert _compute_diversity_score(scenes) == 1.0


# ── _parse_treatment ──────────────────────────────────────────────────────────

class TestParseTreatment:
    def _raw(self, n: int, shot_type: str = "wide") -> dict:
        return {
            "global_style": "documentary",
            "shot_sequence_plan": "wide → close",
            "scenes": [
                {
                    "scene": i + 1,
                    "visual_intent": f"Scene {i + 1}",
                    "shot_type": shot_type,
                    "era": "contemporary",
                    "asset_class": "stock",
                    "preferred_source": "pexels",
                    "search_terms": [f"query {i + 1}"],
                    "avoid": [],
                    "motion": "none",
                    "transition_from_prev": "cut",
                }
                for i in range(n)
            ],
            "diversity_plan": {
                "shot_type_sequence": ["wide"],
                "notes": "test note",
            },
        }

    def test_parses_all_scenes(self):
        treatment = _parse_treatment(self._raw(5), scene_count=5)
        assert len(treatment.scenes) == 5

    def test_unknown_shot_type_normalised_to_wide(self):
        raw = self._raw(1)
        raw["scenes"][0]["shot_type"] = "unknown_type"
        treatment = _parse_treatment(raw, scene_count=1)
        assert treatment.scenes[0].shot_type == "wide"

    def test_pads_missing_scenes(self):
        treatment = _parse_treatment(self._raw(2), scene_count=4)
        assert len(treatment.scenes) == 4
        assert treatment.scenes[3].shot_type == "wide"
        assert treatment.scenes[3].asset_class == "stock"

    def test_prompt_version_set(self):
        treatment = _parse_treatment(self._raw(1), scene_count=1)
        assert treatment.prompt_version == VISUAL_DIRECTOR_PROMPT_VERSION

    def test_diversity_plan_parsed(self):
        treatment = _parse_treatment(self._raw(1), scene_count=1)
        assert treatment.diversity_plan.notes == "test note"


# ── _build_storyboard_user_message ───────────────────────────────────────────

class TestBuildStoryboardUserMessage:
    def _make_storyboard(self, person_name: str = "") -> MagicMock:
        scene = MagicMock()
        scene.scene = "01"
        scene.segment_type = "Character" if person_name else "B-roll"
        scene.voiceover_line = "test voiceover"
        scene.primary_stk = "economy growth"
        scene.person_name = person_name
        scene.person_title = "Researcher" if person_name else ""
        scene.semantic_context = None

        sb = MagicMock()
        sb.scenes = [scene]
        sb.global_context = None
        return sb

    def test_includes_voiceover_line(self):
        sb = self._make_storyboard()
        msg = _build_storyboard_user_message(sb)
        assert "test voiceover" in msg

    def test_includes_person_name_for_character_scene(self):
        sb = self._make_storyboard(person_name="Jane Doe")
        msg = _build_storyboard_user_message(sb)
        assert "Jane Doe" in msg

    def test_valid_json(self):
        sb = self._make_storyboard()
        msg = _build_storyboard_user_message(sb)
        parsed = json.loads(msg)
        assert "scenes" in parsed


# ── _extract_json_object ──────────────────────────────────────────────────────

class TestExtractJsonObject:
    def test_plain_json(self):
        result = _extract_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_strips_markdown_fences(self):
        result = _extract_json_object('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}


# ── build_visual_director_worker (integration) ────────────────────────────────

class TestBuildVisualDirectorWorker:
    def _make_storage(self, storyboard_artifact: dict) -> AsyncMock:
        storage = AsyncMock()
        storage.get_json = AsyncMock(return_value=storyboard_artifact)
        storage.put_json = AsyncMock()
        return storage

    def _make_state(self, run_id: str = "test-run-001") -> MagicMock:
        state = MagicMock()
        state.run_id = run_id
        state.user_id = "user-1"
        state.artifacts = {"verified_storyboard": f"runs/{run_id}/verified_storyboard.json"}
        return state

    def _storyboard_artifact(self, n_scenes: int = 3) -> dict:
        return {
            "artifact_type": "verified_storyboard",
            "worker_version": "1.1.0",
            "prompt_version": "v0.15",
            "created_at": datetime.now(UTC).isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "run_id": "test-run-001",
            "scene_count": n_scenes,
            "storyboard": {
                "global_context": {
                    "topic": "neuroscience",
                    "domain": "neuroscience",
                    "subtopics": ["exercise", "BDNF"],
                    "avoid_globally": ["food"],
                    "tone": "authoritative",
                },
                "scenes": [
                    {
                        "scene": str(i + 1).zfill(2),
                        "voiceover_line": f"word {i}",
                        "segment_type": "B-roll",
                        "primary_stk": f"brain neuron {i}",
                        "context_stk": "brain",
                        "concept_stk": "neuroscience",
                        "duration_s": 5.0,
                        "clip_type": "still_with_motion",
                        "sfx": "",
                        "sfx_timing": "start",
                        "on_screen_text": None,
                        "on_screen_text_type": None,
                        "render_options": None,
                    }
                    for i in range(n_scenes)
                ],
                "global": {
                    "subtitle_style": "bottom",
                    "bg_music": "none",
                    "visual_style": "documentary",
                },
                "summary": {
                    "total_scenes": n_scenes,
                    "total_duration_s": n_scenes * 5.0,
                    "rhythm": "medium",
                },
            },
        }

    @pytest.mark.asyncio
    async def test_worker_writes_visual_treatment_artifact(self):
        sb_artifact = self._storyboard_artifact(3)
        storage = self._make_storage(sb_artifact)

        claude_response_json = {
            "global_style": "evidence-based documentary",
            "shot_sequence_plan": "wide → macro_science → wide",
            "scenes": [
                {
                    "scene": i + 1,
                    "visual_intent": f"Scene {i + 1} intent",
                    "shot_type": ["wide", "macro_science", "archive"][i],
                    "era": "contemporary",
                    "asset_class": "stock",
                    "preferred_source": "pexels",
                    "search_terms": [f"neuron brain {i}", f"brain cell {i}"],
                    "avoid": ["food", "protein shake"],
                    "motion": "none",
                    "transition_from_prev": "cut",
                }
                for i in range(3)
            ],
            "diversity_plan": {
                "shot_type_sequence": ["wide", "macro_science", "archive"],
                "notes": "varied",
            },
        }

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(claude_response_json))]

        with patch("cf_platform.workers.visual_director_worker.read_artifact") as mock_read_artifact, \
             patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_read_artifact.return_value = (sb_artifact, sb_artifact)
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_message)
            mock_anthropic_cls.return_value = mock_client

            worker = build_visual_director_worker(storage=storage, anthropic_api_key="test-key")
            state = self._make_state()
            output = await worker(state)

        assert output.artifact is not None
        assert output.artifact.scene_count == 3
        assert len(output.artifact.visual_treatment["scenes"]) == 3
        assert output.artifact.prompt_version == VISUAL_DIRECTOR_PROMPT_VERSION

    @pytest.mark.asyncio
    async def test_worker_retries_on_diversity_violation(self):
        """When first response has 3+ consecutive same shot_type, worker retries."""
        sb_artifact = self._storyboard_artifact(4)
        storage = self._make_storage(sb_artifact)

        def _make_response(shot_types: list[str]) -> MagicMock:
            raw = {
                "global_style": "doc",
                "shot_sequence_plan": "",
                "scenes": [
                    {
                        "scene": i + 1,
                        "visual_intent": "",
                        "shot_type": t,
                        "era": "contemporary",
                        "asset_class": "stock",
                        "preferred_source": "any",
                        "search_terms": [],
                        "avoid": [],
                        "motion": "none",
                        "transition_from_prev": "cut",
                    }
                    for i, t in enumerate(shot_types)
                ],
                "diversity_plan": {"shot_type_sequence": [], "notes": ""},
            }
            m = MagicMock()
            m.content = [MagicMock(text=json.dumps(raw))]
            return m

        # First call: violation (4 consecutive "wide")
        # Second call: no violation
        call_responses = [
            _make_response(["wide", "wide", "wide", "wide"]),
            _make_response(["wide", "portrait", "macro_science", "archive"]),
        ]

        with patch("cf_platform.workers.visual_director_worker.read_artifact") as mock_read, \
             patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_read.return_value = (sb_artifact, sb_artifact)
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(side_effect=call_responses)
            mock_cls.return_value = mock_client

            worker = build_visual_director_worker(storage=storage, anthropic_api_key="test-key")
            state = self._make_state()
            output = await worker(state)

        assert mock_client.messages.create.call_count == 2
        assert output.artifact is not None
        # Second response has no violations — diversity_score should be 1.0
        assert output.artifact.visual_treatment["diversity_score"] == 1.0


# ── AcquisitionWorker visual_treatment preference ────────────────────────────

class TestAcquisitionWorkerTreatmentPreference:
    """Tests for _build_treatment_queries and acquisition_worker visual_treatment integration."""

    def _make_entry(self, primary_stk: str = "economy", visual_tags=None) -> MagicMock:
        from src.models import SemanticContext
        sc = SemanticContext(
            primary_concept="economy",
            domain_qualifier="economic",
            avoid=["food"],
            visual_tags=visual_tags or [],
            entity_type="organization",
        ) if visual_tags is not None else None
        entry = MagicMock()
        entry.scene_id = "01"
        entry.segment_type = "B-roll"
        entry.person_name = None
        entry.primary_stk = primary_stk
        entry.context_stk = "economy"
        entry.concept_stk = "finance"
        entry.semantic_context = sc
        return entry

    def test_treatment_queries_prepend_search_terms(self):
        from cf_platform.workers.acquisition_worker import _build_treatment_queries
        entry = self._make_entry(primary_stk="economy growth")
        plan = SceneVisualPlan(
            scene=1,
            visual_intent="",
            shot_type="wide",
            search_terms=["GDP chart economic data", "stock market graph"],
        )
        queries = _build_treatment_queries(entry, plan)
        assert queries[0] == "GDP chart economic data"
        assert queries[1] == "stock market graph"
        # STK queries follow
        assert "economy growth" in queries

    def test_treatment_queries_fallback_when_no_plan(self):
        from cf_platform.workers.acquisition_worker import _build_treatment_queries
        entry = self._make_entry(primary_stk="economy growth", visual_tags=["growth chart"])
        queries = _build_treatment_queries(entry, scene_plan=None)
        # Without a plan, falls back to enriched queries (visual_tags first)
        assert "growth chart" in queries
        assert "economy growth" in queries

    def test_treatment_queries_deduplicates(self):
        from cf_platform.workers.acquisition_worker import _build_treatment_queries
        entry = self._make_entry(primary_stk="economy growth")
        plan = SceneVisualPlan(
            scene=1,
            visual_intent="",
            shot_type="wide",
            search_terms=["economy growth"],  # same as primary_stk
        )
        queries = _build_treatment_queries(entry, plan)
        assert queries.count("economy growth") == 1

    def test_treatment_queries_empty_search_terms_falls_back(self):
        from cf_platform.workers.acquisition_worker import _build_treatment_queries
        entry = self._make_entry(primary_stk="economy growth")
        plan = SceneVisualPlan(scene=1, visual_intent="", shot_type="wide", search_terms=[])
        queries = _build_treatment_queries(entry, plan)
        assert "economy growth" in queries
