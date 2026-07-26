"""Tests for cf_platform/interfaces/api.py and its fault-isolated mount in src/main.py (P1-S1)."""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
)
from cf_platform.core.run_manager import InMemoryRunRepository, create_run, transition_run
from cf_platform.core.schemas import Artifact, LineageEnvelope, Signal, WorkerExecution, WorkerOutput
from cf_platform.core.worker_registry import InMemoryExecutionRepository
from cf_platform.interfaces.api import (
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
)
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.opportunity_scorer import ScoredTopicsArtifact, TopicScore
from cf_platform.workers.topic_generator import CandidateTopic, CandidateTopicsArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from src.config import Settings, get_settings
from src.main import _mount_platform_router, _run_platform_migrations, _setup_platform_checkpointer, app

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)

_STUB_TOPIC = TopicScore(
    title="Why Starter Homes Vanished",
    angle="The economics of disappearing entry-level housing",
    novelty=8.5,
    audience_relevance=9.0,
    emotional_trigger=7.5,
    search_demand=8.0,
    competition=5.5,
    evergreen_potential=7.0,
    monetization_relevance=8.0,
    final_score=7.86,
)


_STUB_SCRIPT_TEXT = "In 1980, the average American could afford a home after 3 years."
_STUB_IDEA_TITLE = "Why Starter Homes Vanished"


@contextmanager
def _stub_idea_to_script_workers():
    """Patch all 11 Blueprint IR builder factories with deterministic stubs (no Claude calls)."""
    from cf_platform.core.idea_to_script_schemas import (
        Blueprint, EvaluationArtifact, GeneratedScriptArtifact,
        HookVariantsArtifact, IntegrityReport, NarrativeLens, NormalizedContext,
        PatchSetArtifact, Section, SelectedHookArtifact,
    )
    from cf_platform.workers.script_packager import ScriptArtifact

    async def _ctx_norm(state):
        return WorkerOutput(artifact=NormalizedContext(
            primary_angle="Supply shortage", evidence_summary="Evidence",
            top_signals=[], controversies=[], hook_bias="Data",
        ))

    async def _bp_gen(state):
        return WorkerOutput(artifact=Blueprint(
            hook_angle="Hook", structure=[Section(title="S", key_points=["p"])],
            claims=["Claim"], monetization_angle="Mon",
            required_evidence=["Evidence"], signal_summary="Sum",
            direction_alignment_notes="Notes",
        ))

    async def _evaluator(state):
        return WorkerOutput(artifact=EvaluationArtifact(
            score=9.0, factual_corrections=[], alignment_notes="",
            evidence_additions=[], passed=True, notes="",
        ))

    async def _bp_merge(state):
        return WorkerOutput(artifact=Blueprint(
            hook_angle="Hook", structure=[Section(title="S", key_points=["p"])],
            claims=["Claim"], monetization_angle="Mon",
            required_evidence=["Evidence"], signal_summary="Sum",
            direction_alignment_notes="Notes",
        ))

    async def _narrative_lens(state):
        return WorkerOutput(artifact=NarrativeLens(
            identity_angle="Identity", contrarian_angle="Contrarian",
            philosophical_angle="Philosophical", emotional_angle="Emotional",
            story_devices=["device 1"],
        ))

    async def _hook_gen(state):
        return WorkerOutput(artifact=HookVariantsArtifact(hooks=["Hook 1"], generated_at=_NOW))

    async def _hook_sel(state):
        return WorkerOutput(artifact=SelectedHookArtifact(hook="Hook 1", generated_at=_NOW))

    async def _script_gen(state):
        return WorkerOutput(artifact=GeneratedScriptArtifact(
            idea_title=_STUB_IDEA_TITLE, niche=None, script=_STUB_SCRIPT_TEXT,
            word_count=len(_STUB_SCRIPT_TEXT.split()), target_duration_seconds=60, generated_at=_NOW,
        ))

    async def _integrity(state):
        return WorkerOutput(artifact=IntegrityReport(passed=True, issues=[]), control="continue")  # type: ignore[arg-type]

    async def _patch_gen(state):
        return WorkerOutput(artifact=PatchSetArtifact(patches=[], generated_at=_NOW))

    async def _patch_apply(state):
        return WorkerOutput(artifact=GeneratedScriptArtifact(
            idea_title=_STUB_IDEA_TITLE, niche=None, script=_STUB_SCRIPT_TEXT,
            word_count=len(_STUB_SCRIPT_TEXT.split()), target_duration_seconds=60, generated_at=_NOW,
        ))

    async def _packager(state):
        return WorkerOutput(artifact=ScriptArtifact(
            idea_title=_STUB_IDEA_TITLE, niche=None, script=_STUB_SCRIPT_TEXT,
            generated_at=_NOW,
        ))

    with (
        patch("cf_platform.blocks.idea_to_script.build_context_normalizer_worker", return_value=_ctx_norm),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_generator_worker", return_value=_bp_gen),
        patch("cf_platform.blocks.idea_to_script.build_evaluator_worker", return_value=_evaluator),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_merger_worker", return_value=_bp_merge),
        patch("cf_platform.blocks.idea_to_script.build_narrative_lens_worker", return_value=_narrative_lens),
        patch("cf_platform.blocks.idea_to_script.build_hook_generator_worker", return_value=_hook_gen),
        patch("cf_platform.blocks.idea_to_script.build_hook_selector_worker", return_value=_hook_sel),
        patch("cf_platform.blocks.idea_to_script.build_script_generator_worker", return_value=_script_gen),
        patch("cf_platform.blocks.idea_to_script.build_integrity_checker_worker", return_value=_integrity),
        patch("cf_platform.blocks.idea_to_script.build_patch_generator_worker", return_value=_patch_gen),
        patch("cf_platform.blocks.idea_to_script.build_patch_applier_worker", return_value=_patch_apply),
        patch("cf_platform.blocks.idea_to_script.build_script_packager_worker", return_value=_packager),
    ):
        yield


@contextmanager
def _stub_niche_to_ideas_workers():
    """Patch all 4 niche_to_ideas worker builders with minimal stubs (no network calls)."""

    async def _disc(state):
        return WorkerOutput(artifact=SignalsArtifact(
            niche=state.inputs.get("niche", "test"),
            generated_at=_NOW,
            signals=[Signal(source="youtube", title="Stub signal", score=100.0)],
        ))

    async def _tgen(state):
        return WorkerOutput(artifact=CandidateTopicsArtifact(
            niche="test", generated_at=_NOW,
            topics=[CandidateTopic(title="Stub Topic", angle="stub")],
        ))

    async def _scorer(state):
        return WorkerOutput(artifact=ScoredTopicsArtifact(
            niche="test", generated_at=_NOW, scored_topics=[_STUB_TOPIC],
        ))

    async def _sel(state):
        return WorkerOutput(artifact=RankedIdeasArtifact(
            niche=state.inputs.get("niche", "test"),
            generated_at=_NOW,
            selected=_STUB_TOPIC,
            alternatives=[],
            mode="single",
        ))

    with (
        patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_disc),
        patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen),
        patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer),
        patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel),
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_settings_override():
    """Remove the get_settings/get_platform_settings dependency overrides after each test."""
    yield
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_platform_settings, None)
    app.dependency_overrides.pop(get_discovery_adapters, None)
    app.dependency_overrides.pop(get_artifact_storage, None)


_PLATFORM_SETTINGS_BASE = {
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
}

VALID_ENV = {
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


def _client_with_settings() -> TestClient:
    """Return a TestClient for the main app with valid settings injected via Depends override."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    return TestClient(app)


class _StubSourceAdapter:
    """Stub SourceAdapter returning a fixed list of signals — avoids real network calls in tests."""

    def __init__(self, signals: list[Signal]) -> None:
        """Store the fixed signals this adapter's fetch() returns."""
        self._signals = signals

    async def fetch(self, niche: str, params: dict) -> list[Signal]:
        """Return the fixed signals regardless of niche/params."""
        return self._signals


class TestPlatformHealthRoute:
    def test_platform_health_returns_200(self):
        """GET /platform/health returns 200 with status ok and a database field."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] in ("ok", "unavailable")

    def test_platform_health_ok_when_database_unset(self):
        """GET /platform/health reports status ok and database unavailable when DATABASE_URL is unset (D048)."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "unavailable"}

    def test_legacy_route_unaffected(self):
        """Mounting the platform router does not break an existing legacy route."""
        client = _client_with_settings()

        response = client.get("/health")

        assert response.status_code == 200


class TestMountPlatformRouterFaultIsolation:
    def test_mount_succeeds_registers_route(self):
        """Normal mount registers /platform/health on a fresh app."""
        fresh_app = FastAPI()

        _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_mount_failure_is_swallowed(self):
        """An import failure in cf_platform.interfaces.api does not raise."""
        fresh_app = FastAPI()

        with patch.dict(sys.modules, {"cf_platform.interfaces.api": None}):
            _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 404


class TestRunPlatformMigrationsFaultIsolation:
    @pytest.mark.asyncio
    async def test_calls_run_migrations_with_database_url(self):
        """_run_platform_migrations calls run_migrations with the platform's DATABASE_URL."""
        with patch(
            "cf_platform.core.migrations.run_migrations", new_callable=AsyncMock
        ) as mock_run_migrations:
            mock_run_migrations.return_value = "unavailable"

            await _run_platform_migrations()

        mock_run_migrations.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self):
        """A failure in run_migrations is logged and swallowed — never raised."""
        with patch(
            "cf_platform.core.migrations.run_migrations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db exploded"),
        ):
            await _run_platform_migrations()  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_import_failure(self):
        """An import failure in cf_platform.core.migrations does not raise."""
        with patch.dict(sys.modules, {"cf_platform.core.migrations": None}):
            await _run_platform_migrations()  # must not raise


class TestRepositoryProviderSelection:
    """get_*_repository() picks Postgres-backed repos when DATABASE_URL is set, else in-memory (D048)."""

    def test_returns_in_memory_repos_when_pool_unset(self):
        """With no Postgres pool (DATABASE_URL unset), provider functions return the in-memory singletons."""
        with patch("cf_platform.interfaces.api.get_pool", return_value=None):
            assert isinstance(get_run_repository(), InMemoryRunRepository)
            assert isinstance(get_execution_repository(), InMemoryExecutionRepository)
            assert isinstance(get_artifact_repository(), InMemoryArtifactRepository)

    def test_returns_postgres_repos_when_pool_set(self):
        """With a Postgres pool available (DATABASE_URL set), provider functions return Postgres-backed repos."""
        with patch("cf_platform.interfaces.api.get_pool", return_value=MagicMock()):
            assert isinstance(get_run_repository(), PostgresRunRepository)
            assert isinstance(get_execution_repository(), PostgresExecutionRepository)
            assert isinstance(get_artifact_repository(), PostgresArtifactRepository)


class TestGetGraphCheckpointer:
    """get_graph_checkpointer() picks a Postgres-backed checkpointer when DATABASE_URL is set (D048, P2-S4)."""

    @pytest.mark.asyncio
    async def test_returns_memory_saver_when_database_url_unset(self):
        """With DATABASE_URL unset, get_graph_checkpointer returns a MemorySaver."""
        checkpointer = await get_graph_checkpointer()

        assert isinstance(checkpointer, MemorySaver)

    @pytest.mark.asyncio
    async def test_returns_postgres_saver_when_database_url_set(self):
        """With DATABASE_URL set, get_graph_checkpointer returns an AsyncPostgresSaver."""
        with patch(
            "cf_platform.interfaces.api.get_platform_settings",
            return_value=MagicMock(DATABASE_URL="postgresql://user:pass@localhost/db"),
        ):
            checkpointer = await get_graph_checkpointer()

        assert isinstance(checkpointer, AsyncPostgresSaver)


class TestSetupPlatformCheckpointerFaultIsolation:
    @pytest.mark.asyncio
    async def test_calls_setup_checkpointer_with_checkpointer(self):
        """_setup_platform_checkpointer calls setup_checkpointer with the platform's checkpointer."""
        with patch(
            "cf_platform.core.db.setup_checkpointer", new_callable=AsyncMock
        ) as mock_setup:
            mock_setup.return_value = "ok"

            await _setup_platform_checkpointer()

        mock_setup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self):
        """A failure in setup_checkpointer is logged and swallowed — never raised."""
        with patch(
            "cf_platform.core.db.setup_checkpointer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db exploded"),
        ):
            await _setup_platform_checkpointer()  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_import_failure(self):
        """An import failure in cf_platform.core.db does not raise."""
        with patch.dict(sys.modules, {"cf_platform.core.db": None}):
            await _setup_platform_checkpointer()  # must not raise


class TestObservabilityRoutes:
    """GET /platform/runs and GET /platform/runs/{run_id} (P2-S5)."""

    @pytest.fixture(autouse=True)
    def _override_repositories(self):
        """Inject fresh in-memory repositories for each test, cleared afterwards."""
        self.runs = InMemoryRunRepository()
        self.artifacts = InMemoryArtifactRepository()
        self.executions = InMemoryExecutionRepository()
        app.dependency_overrides[get_run_repository] = lambda: self.runs
        app.dependency_overrides[get_artifact_repository] = lambda: self.artifacts
        app.dependency_overrides[get_execution_repository] = lambda: self.executions
        yield
        app.dependency_overrides.pop(get_run_repository, None)
        app.dependency_overrides.pop(get_artifact_repository, None)
        app.dependency_overrides.pop(get_execution_repository, None)

    @pytest.mark.asyncio
    async def test_list_runs_returns_created_runs(self):
        """GET /platform/runs returns a summary for every run, most recent first."""
        run_a = await create_run("operator", "echo", {"text": "first"}, self.runs)
        run_b = await create_run("operator", "echo", {"text": "second"}, self.runs)

        client = _client_with_settings()
        response = client.get("/platform/runs")

        assert response.status_code == 200
        body = response.json()
        assert [r["run_id"] for r in body] == [run_b.run_id, run_a.run_id]
        assert body[0]["status"] == "created"
        assert body[0]["block"] == "echo"

    @pytest.mark.asyncio
    async def test_list_runs_empty(self):
        """GET /platform/runs returns an empty list when no runs exist."""
        client = _client_with_settings()

        response = client.get("/platform/runs")

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_run_returns_lineage_detail(self):
        """GET /platform/runs/{run_id} returns status, artifacts (R2 keys), and per-worker cost/latency/version."""
        run = await create_run("operator", "echo", {"text": "hello"}, self.runs)
        run = await transition_run(run.run_id, "running", self.runs)
        now = datetime.now(timezone.utc)
        lineage = LineageEnvelope(
            run_id=run.run_id,
            worker="echo",
            worker_version="1.0.0",
            prompt_version="v1",
            model="claude-haiku-4-5-20251001",
            sampling_params={},
            created_at=now,
        )
        artifact = Artifact(
            name="echo",
            stage="echo",
            version=1,
            run_id=run.run_id,
            r2_key="users/operator/runs/r1/echo/echo@v1.json",
            lineage=lineage,
        )
        await self.artifacts.record(artifact)
        execution = WorkerExecution(
            run_id=run.run_id,
            worker="echo",
            worker_version="1.0.0",
            prompt_version="v1",
            model="claude-haiku-4-5-20251001",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            latency_ms=42,
            status="ok",
            artifact_r2_key=artifact.r2_key,
            started_at=now,
            finished_at=now,
        )
        await self.executions.record(execution)

        client = _client_with_settings()
        response = client.get(f"/platform/runs/{run.run_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["run"]["run_id"] == run.run_id
        assert body["run"]["status"] == "running"
        assert body["artifacts"] == [
            {
                "name": "echo",
                "stage": "echo",
                "version": 1,
                "r2_key": artifact.r2_key,
                "worker": "echo",
                "worker_version": "1.0.0",
                "prompt_version": "v1",
                "model": "claude-haiku-4-5-20251001",
            }
        ]
        assert len(body["executions"]) == 1
        assert body["executions"][0]["cost_usd"] == 0.001
        assert body["executions"][0]["latency_ms"] == 42

    @pytest.mark.asyncio
    async def test_get_run_unknown_returns_404(self):
        """GET /platform/runs/{run_id} returns 404 for an unknown run_id."""
        client = _client_with_settings()

        response = client.get("/platform/runs/does-not-exist")

        assert response.status_code == 404


class TestTelegramWebhookRoute:
    """POST /platform/telegram/webhook (P3-S1, D049) — trigger-only, secret-validated."""

    def _client_with_telegram_settings(self, signals: Optional[list[Signal]] = None, **overrides) -> TestClient:
        """Return a TestClient with PlatformSettings overridden for telegram tests.

        Also overrides get_discovery_adapters (stub adapters returning `signals`,
        default empty) and get_artifact_storage (in-memory) so `/ideas <niche>`
        runs the real discovery graph without any network calls.
        """
        settings_kwargs = {
            **_PLATFORM_SETTINGS_BASE,
            "TELEGRAM_BOT_TOKEN": "test-bot-token",
            "TELEGRAM_WEBHOOK_SECRET": "test-secret",
            **overrides,
        }
        app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(**settings_kwargs)
        app.dependency_overrides[get_discovery_adapters] = lambda: [
            ("stub", _StubSourceAdapter(signals or []))
        ]
        app.dependency_overrides[get_artifact_storage] = lambda: InMemoryArtifactStorage()
        return TestClient(app)

    def test_missing_secret_header_rejected(self):
        """A request with no secret header is rejected with 401."""
        client = self._client_with_telegram_settings()

        response = client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": "/ideas starter homes"}},
        )

        assert response.status_code == 401

    def test_wrong_secret_header_rejected(self):
        """A request with the wrong secret header is rejected with 401."""
        client = self._client_with_telegram_settings()

        response = client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": "/ideas starter homes"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )

        assert response.status_code == 401

    def test_unset_webhook_secret_rejects_everything(self):
        """If TELEGRAM_WEBHOOK_SECRET is unset, every call is rejected with 401."""
        client = self._client_with_telegram_settings(TELEGRAM_WEBHOOK_SECRET="")

        response = client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 1}, "text": "/ideas starter homes"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": ""},
        )

        assert response.status_code == 401

    def test_ideas_command_sends_ack_then_ranked_ideas_reply(self):
        """A valid /ideas <niche> update sends an immediate ack, then the ranked-ideas result."""
        client = self._client_with_telegram_settings()

        with _stub_niche_to_ideas_workers(), patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/ideas starter homes"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # Two messages: immediate ack + ranked-ideas result
        assert mock_send.await_count == 2
        ack_args, _ = mock_send.call_args_list[0]
        assert ack_args[0] == 42
        assert "starter homes" in ack_args[1]
        result_args, _ = mock_send.call_args_list[1]
        assert result_args[0] == 42
        assert "starter homes" in result_args[1]
        assert _STUB_TOPIC.title in result_args[1]

    def test_ideas_command_reply_contains_numbered_ideas_and_pick_cta(self):
        """The ranked-ideas reply (second message) shows numbered ideas and a /pick CTA (P7-S1)."""
        client = self._client_with_telegram_settings()

        with _stub_niche_to_ideas_workers(), patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/ideas starter homes"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        # Second call is the ranked-ideas result.
        result_args, _ = mock_send.call_args_list[1]
        reply = result_args[1]
        assert "1." in reply, "Expected numbered idea #1 in reply"
        assert "/pick" in reply, "Expected /pick CTA in reply"
        assert "Score:" in reply, "Expected Score: line in reply"

    def test_ideas_without_niche_sends_usage_reply(self):
        """`/ideas` with no niche sends a usage reply, not an ack."""
        client = self._client_with_telegram_settings()

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/ideas"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        assert "/ideas" in args[1]

    def test_unrecognized_command_sends_help_reply(self):
        """An unrecognized message sends a help reply pointing at /ideas."""
        client = self._client_with_telegram_settings()

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "hello there"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        assert "/ideas" in args[1]

    def test_update_without_message_is_acked_without_reply(self):
        """An update with no `message` field (e.g. edited_message) is acked with no reply sent."""
        client = self._client_with_telegram_settings()

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_send.assert_not_called()


class TestTelegramWebhookAllowlist:
    """TELEGRAM_ALLOWED_CHAT_IDS restricts replies to specific chats (temporary, ahead of S19)."""

    def _client_with_telegram_settings(self, **overrides) -> TestClient:
        """Return a TestClient with PlatformSettings overridden for allowlist tests.

        Also overrides get_discovery_adapters (stub, no signals) and
        get_artifact_storage (in-memory) so an allowed `/ideas <niche>` runs the
        real discovery graph without any network calls.
        """
        settings_kwargs = {
            **_PLATFORM_SETTINGS_BASE,
            "TELEGRAM_BOT_TOKEN": "test-bot-token",
            "TELEGRAM_WEBHOOK_SECRET": "test-secret",
            **overrides,
        }
        app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(**settings_kwargs)
        app.dependency_overrides[get_discovery_adapters] = lambda: [("stub", _StubSourceAdapter([]))]
        app.dependency_overrides[get_artifact_storage] = lambda: InMemoryArtifactStorage()
        return TestClient(app)

    def test_allowed_chat_id_gets_normal_reply(self):
        """A chat id present in TELEGRAM_ALLOWED_CHAT_IDS receives the usual reply."""
        client = self._client_with_telegram_settings(TELEGRAM_ALLOWED_CHAT_IDS="111000111")

        with _stub_niche_to_ideas_workers(), patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 111000111}, "text": "/ideas starter homes"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        # ack + result = 2 messages for an /ideas command
        assert mock_send.await_count == 2

    def test_disallowed_chat_id_gets_no_reply(self):
        """A chat id absent from TELEGRAM_ALLOWED_CHAT_IDS is acked with no reply sent."""
        client = self._client_with_telegram_settings(TELEGRAM_ALLOWED_CHAT_IDS="111000111")

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 1}, "text": "/ideas starter homes"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_send.assert_not_called()


class TestTelegramWebhookScriptCommand:
    """POST /platform/telegram/webhook — /script <idea_title> command (P5-S5)."""

    def _client(self, **overrides) -> TestClient:
        settings_kwargs = {
            **_PLATFORM_SETTINGS_BASE,
            "TELEGRAM_BOT_TOKEN": "test-bot-token",
            "TELEGRAM_WEBHOOK_SECRET": "test-secret",
            "ANTHROPIC_API_KEY": "sk-ant-fake",
            **overrides,
        }
        app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(**settings_kwargs)
        app.dependency_overrides[get_artifact_storage] = lambda: InMemoryArtifactStorage()
        return TestClient(app)

    def _post_script(self, client: TestClient, idea_title: str) -> "TestClient":
        return client.post(
            "/platform/telegram/webhook",
            json={"message": {"chat": {"id": 42}, "text": f"/script {idea_title}"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

    def test_script_command_sends_ack_and_script_reply(self):
        """A valid /script <title> sends an immediate ack, then the finished script."""
        client = self._client()

        with _stub_idea_to_script_workers(), patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = self._post_script(client, _STUB_IDEA_TITLE)

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        # Two messages: ack + script reply
        assert mock_send.await_count == 2
        ack_args, _ = mock_send.call_args_list[0]
        assert ack_args[0] == 42
        assert _STUB_IDEA_TITLE in ack_args[1]

    def test_script_reply_contains_script_text(self):
        """The script reply (second message) contains the script body."""
        client = self._client()

        with _stub_idea_to_script_workers(), patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            self._post_script(client, _STUB_IDEA_TITLE)

        result_args, _ = mock_send.call_args_list[1]
        assert _STUB_SCRIPT_TEXT in result_args[1]

    def test_bare_script_command_sends_usage_reply(self):
        """`/script` with no title sends a usage reply."""
        client = self._client()

        with patch(
            "cf_platform.interfaces.api.TelegramClient.send_message", new_callable=AsyncMock
        ) as mock_send:
            response = client.post(
                "/platform/telegram/webhook",
                json={"message": {"chat": {"id": 42}, "text": "/script"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )

        assert response.status_code == 200
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        assert "/script" in args[1]


class TestTelegramWebhookAuthExempt:
    """The legacy auth middleware exempts /platform/telegram/webhook (Telegram has no session cookie)."""

    def test_webhook_path_is_auth_exempt(self):
        """POSTing without a session cookie does not get redirected/401'd by the legacy auth middleware.

        The route itself still rejects the request (401, missing/wrong secret) —
        this test only proves the *legacy* middleware doesn't intercept it first
        with a redirect-to-login or a generic Unauthorized body.
        """
        app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(
            **_PLATFORM_SETTINGS_BASE
        )
        client = TestClient(app, follow_redirects=False)

        response = client.post("/platform/telegram/webhook", json={})

        assert response.status_code != 302
        assert response.json() != {"detail": "Unauthorized"}
