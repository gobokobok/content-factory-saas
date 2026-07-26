"""Tests for P4-S5: POST /platform/blocks/niche-to-ideas and format_ranked_ideas (P4-S5).

Covers:
- format_ranked_ideas: niche/run_id/artifact_key present, selected title+angle+scores,
  alternatives listed (capped at 3), empty alternatives, score labels in output
- POST /platform/blocks/niche-to-ideas: 200 response shape (run_id, artifact_key,
  selected, alternatives), mode default, audience field stored in run inputs
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.schemas import Signal, WorkerOutput
from cf_platform.interfaces.api import get_artifact_storage, get_discovery_adapters
from cf_platform.interfaces.telegram import format_ranked_ideas
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.opportunity_scorer import ScoredTopicsArtifact, TopicScore
from cf_platform.workers.topic_generator import CandidateTopic, CandidateTopicsArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from src.config import Settings, get_settings
from src.main import app

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)

_VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}

_PLATFORM_SETTINGS_BASE = {
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
}


def _make_topic(title: str = "Test Topic", final_score: float = 8.0) -> TopicScore:
    """Return a TopicScore fixture with all axes set."""
    return TopicScore(
        title=title,
        angle=f"The angle for {title}",
        novelty=8.5,
        audience_relevance=9.0,
        emotional_trigger=7.5,
        search_demand=8.0,
        competition=5.5,
        evergreen_potential=7.0,
        monetization_relevance=8.0,
        final_score=final_score,
    )


def _make_ranked_ideas(
    niche: str = "starter homes",
    selected_title: str = "Why Starter Homes Vanished",
    alternatives: list[TopicScore] | None = None,
) -> RankedIdeasArtifact:
    """Return a RankedIdeasArtifact fixture."""
    return RankedIdeasArtifact(
        niche=niche,
        generated_at=_NOW,
        selected=_make_topic(selected_title, 8.5),
        alternatives=alternatives or [],
        mode="single",
    )


@contextmanager
def _stub_niche_to_ideas_workers(niche: str = "starter homes"):
    """Patch all 4 niche_to_ideas worker builders with stubs that return canned artifacts."""
    selected = _make_topic("Why Starter Homes Vanished", 8.5)
    alt1 = _make_topic("Hidden Costs First-Time Buyers Miss", 7.80)
    alt2 = _make_topic("Rates vs Starter Homes", 7.20)

    async def _disc(state):
        return WorkerOutput(artifact=SignalsArtifact(
            niche=niche, generated_at=_NOW,
            signals=[Signal(source="youtube", title="Stub signal", score=100.0)],
        ))

    async def _tgen(state):
        return WorkerOutput(artifact=CandidateTopicsArtifact(
            niche=niche, generated_at=_NOW,
            topics=[CandidateTopic(title="Why Starter Homes Vanished", angle="Economics")],
        ))

    async def _scorer(state):
        return WorkerOutput(artifact=ScoredTopicsArtifact(
            niche=niche, generated_at=_NOW,
            scored_topics=[selected, alt1, alt2],
        ))

    async def _sel(state):
        return WorkerOutput(artifact=RankedIdeasArtifact(
            niche=niche, generated_at=_NOW,
            selected=selected,
            alternatives=[alt1, alt2],
            mode=getattr(state, "mode", "single"),
        ))

    with (
        patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_disc),
        patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen),
        patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer),
        patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel),
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Remove dependency overrides after each test."""
    yield
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_platform_settings, None)
    app.dependency_overrides.pop(get_discovery_adapters, None)
    app.dependency_overrides.pop(get_artifact_storage, None)


def _make_client() -> TestClient:
    """Return a TestClient with in-memory storage and a fake platform settings."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
    app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(**_PLATFORM_SETTINGS_BASE)
    app.dependency_overrides[get_artifact_storage] = lambda: InMemoryArtifactStorage()
    app.dependency_overrides[get_discovery_adapters] = lambda: []
    return TestClient(app)


# ── format_ranked_ideas ────────────────────────────────────────────────────────


class TestFormatRankedIdeas:
    """format_ranked_ideas produces a D049-compliant plain-string reply."""

    def test_contains_niche_and_run_id(self):
        """Reply contains the niche string and run_id (needed for /pick CTA, P7-S1)."""
        ranked = _make_ranked_ideas("starter homes")
        reply = format_ranked_ideas("starter homes", "run-abc", "some/key@v1.json", ranked)
        assert "starter homes" in reply
        assert "run-abc" in reply

    def test_selected_title_in_output(self):
        """Selected idea title appears prominently in the reply."""
        ranked = _make_ranked_ideas(selected_title="Why Starter Homes Vanished")
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        assert "Why Starter Homes Vanished" in reply

    def test_numbered_ideas_and_pick_cta_present(self):
        """Reply shows numbered ideas 1–N and a /pick call-to-action (P7-S1)."""
        ranked = _make_ranked_ideas()
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        assert "1." in reply
        assert "/pick" in reply
        assert "Score:" in reply

    def test_final_score_in_output(self):
        """The final composite score is included in the reply."""
        ranked = _make_ranked_ideas()
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        assert "8.50" in reply

    def test_alternatives_listed(self):
        """Alternatives appear below the selected idea."""
        alts = [_make_topic("Alt One", 7.5), _make_topic("Alt Two", 7.0)]
        ranked = _make_ranked_ideas(alternatives=alts)
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        assert "Alt One" in reply
        assert "Alt Two" in reply

    def test_no_alternatives_omits_section(self):
        """When alternatives is empty, the Runner-ups section is not emitted."""
        ranked = _make_ranked_ideas(alternatives=[])
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        assert "Runner-ups" not in reply

    def test_at_most_five_ideas_shown(self):
        """At most 5 ideas shown (selected + up to 4 alternatives) even if more exist (P7-S1)."""
        alts = [_make_topic(f"Alt {i}", float(7 - i * 0.1)) for i in range(6)]
        ranked = _make_ranked_ideas(alternatives=alts)
        reply = format_ranked_ideas("housing", "run-1", "key@v1.json", ranked)
        # selected=1, alts 0-3 = positions 2-5 → 5 total shown
        assert "Alt 0" in reply
        assert "Alt 1" in reply
        assert "Alt 2" in reply
        assert "Alt 3" in reply
        # Alt 4 and Alt 5 should not appear (beyond top 5)
        assert "Alt 4" not in reply.split("Pick")[0]
        assert "Alt 5" not in reply.split("Pick")[0]

    def test_artifact_key_not_in_output(self):
        """The artifact key is intentionally omitted from the reply (internal storage path)."""
        ranked = _make_ranked_ideas()
        reply = format_ranked_ideas("housing", "run-1", "users/op/ranked@v1.json", ranked)
        assert "users/op/ranked@v1.json" not in reply


# ── POST /platform/blocks/niche-to-ideas ──────────────────────────────────────


class TestNicheToIdeasRoute:
    """POST /platform/blocks/niche-to-ideas — REST block interface (P4-S5)."""

    def test_returns_200_with_ranked_ideas(self):
        """A valid request returns 200 with run_id, artifact key, and ranked ideas body."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
                headers={"Cookie": "session=fake"},  # bypassed via TestClient (no auth in platform routes)
            )

        assert response.status_code == 200
        body = response.json()
        assert "run_id" in body
        assert "ranked_ideas_artifact_key" in body
        assert "selected" in body
        assert "alternatives" in body

    def test_selected_title_present_in_response(self):
        """The selected idea title from the block is in the response."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["selected"]["title"] == "Why Starter Homes Vanished"

    def test_alternatives_in_response(self):
        """The alternatives list from the block is in the response."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["alternatives"], list)
        assert len(body["alternatives"]) == 2

    def test_selected_has_all_seven_axes(self):
        """The selected topic object exposes all 7 scoring axes and final_score."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        body = response.json()
        sel = body["selected"]
        for field in (
            "novelty", "audience_relevance", "emotional_trigger", "search_demand",
            "competition", "evergreen_potential", "monetization_relevance", "final_score",
        ):
            assert field in sel, f"Missing field '{field}' in selected"

    def test_default_mode_is_single(self):
        """Omitting mode defaults to 'single' (no error, valid NicheToIdeasState)."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        assert response.status_code == 200

    def test_explicit_mode_top_n_accepted(self):
        """Passing mode='top_n' is accepted and does not error."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes", "mode": "top_n"},
            )

        assert response.status_code == 200

    def test_audience_field_accepted(self):
        """The optional audience field is accepted without error."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes", "audience": "first-time buyers"},
            )

        assert response.status_code == 200

    def test_run_id_is_a_uuid_string(self):
        """The run_id in the response is a non-empty UUID-formatted string."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        run_id = response.json()["run_id"]
        assert uuid.UUID(run_id)  # raises if not a valid UUID

    def test_ranked_ideas_artifact_key_contains_run_id(self):
        """The ranked_ideas_artifact_key embeds the run_id in the R2 path."""
        client = _make_client()

        with _stub_niche_to_ideas_workers("starter homes"):
            response = client.post(
                "/platform/blocks/niche-to-ideas",
                json={"niche": "starter homes"},
            )

        body = response.json()
        assert body["run_id"] in body["ranked_ideas_artifact_key"]
