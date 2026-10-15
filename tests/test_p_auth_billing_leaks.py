"""P-BILL-1 review fixes — a hold must never outlive a failed start (D123).

Every await between ``billing.reserve`` and the moment a background job takes the hold over is
guarded: a failure there refunds the hold and lets the error through. Each path below injects a
failure AFTER the hold is taken and asserts the balance is back and the entry says refunded.
Cancellation of a running job refunds too. Real auth middleware and real session cookies
(the ``test_p_auth`` prefix keeps conftest from swapping in the owner).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cf_platform.core import billing
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.run_manager import create_run
from tests.cf_platform.p13_helpers import RUN_ID
from tests.test_p_auth_accounts import World
from tests.test_p_auth_billing_routes import _seed_storyboard_for, friend, own_run


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def ledger(monkeypatch) -> InMemoryBillingStore:
    """Charging on, a fresh ledger, and no holds left over from another test."""
    monkeypatch.setenv("BILLING_ENABLED", "true")
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    billing._in_flight.clear()
    yield fresh
    billing._in_flight.clear()


@pytest.fixture
def world(ledger):
    w = World()
    yield w
    w.close()


def fail_storage_writes(w: World, marker: str) -> None:
    """Make the next write of any key containing `marker` raise — the failure injected after the hold."""
    original = w.storage.put_json

    async def put_json(key, data, *args, **kwargs):
        if marker in key:
            raise RuntimeError(f"storage refused {key}")
        return await original(key, data, *args, **kwargs)

    w.storage.put_json = put_json


def assert_restored(ledger, tenant: str, balance: int = 100) -> None:
    """The balance is back, every entry is refunded, no hold is left in flight."""
    assert run(ledger.balance(tenant)) == balance
    entries = run(ledger.list_entries(tenant))
    assert entries and all(e.status == "refunded" for e in entries), [(e.kind, e.status) for e in entries]
    assert not billing._in_flight


# ── The routes: a failure after the hold ─────────────────────────────────


class TestStartFailures:
    def test_storyboard_route(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)
        fail_storage_writes(world, "storyboard/current_job.json")
        response = world.client(cookie).post(
            "/platform/workers/storyboard", json={"run_id": RUN_ID, "script": "One two three four."})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_voice_route(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)
        fail_storage_writes(world, "voice/current_job.json")
        response = world.client(cookie).post(
            "/platform/workers/voice", json={"run_id": RUN_ID, "script": "One two three."})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_voice_route_when_queueing_the_job_fails(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)
        with patch("fastapi.BackgroundTasks.add_task", side_effect=RuntimeError("queue is closed")):
            response = world.client(cookie).post(
                "/platform/workers/voice", json={"run_id": RUN_ID, "script": "One two three."})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def _render_ready(self, world, credits):
        cookie, tenant = friend(world, credits=credits)
        own_run(world, tenant)
        from tests.cf_platform.test_p_lite_scene_prompt import _animated

        run(_seed_storyboard_for(world, tenant, _animated()))
        run(world.storage.put_json(f"users/{tenant}/runs/{RUN_ID}/acquisition/asset_manifest@v1.json", {"body": {}}))
        return cookie, tenant

    def test_render_route_marker_write_fails(self, world, ledger):
        cookie, tenant = self._render_ready(world, 100)
        fail_storage_writes(world, "render/current_job.json")
        response = world.client(cookie).post("/platform/workers/render", json={"run_id": RUN_ID})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_render_route_gives_back_the_slot_too(self, world, ledger):
        from cf_platform.core import limits

        cookie, tenant = self._render_ready(world, 100)
        with patch("fastapi.BackgroundTasks.add_task", side_effect=RuntimeError("queue is closed")):
            response = world.client(cookie).post("/platform/workers/render", json={"run_id": RUN_ID})
        assert response.status_code == 500
        assert_restored(ledger, tenant)
        assert limits._active_renders.get(tenant, 0) == 0, "the render slot was released"

    def test_render_route_refused_slot_still_refunds(self, world, ledger):
        from cf_platform.core import limits

        cookie, tenant = self._render_ready(world, 100)
        limits._active_renders[tenant] = 5
        try:
            response = world.client(cookie).post("/platform/workers/render", json={"run_id": RUN_ID})
        finally:
            limits._active_renders.pop(tenant, None)
        assert response.status_code == 429
        assert_restored(ledger, tenant)

    def test_voiceover_upload_route(self, world, ledger):
        # Uploading a voiceover is Super's (a Basic account has no upload), so use a Super account that is not the owner.
        cookie, user = run(world.sign_in("boss@example.com", "sub-boss"))
        tenant = user.tenant_id
        run(billing.topup(tenant, 100))
        run(create_run(tenant, "creator", {"voice_source": "uploaded"}, world.runs, run_id=RUN_ID))

        async def boom(*_a, **_k):
            raise RuntimeError("storage refused the upload")

        with patch("cf_platform.interfaces.routes.studio_voice.validate_voice_upload", return_value=".mp3"), patch.object(
            world.storage, "put_bytes", boom
        ):
            response = world.client(cookie).post(
                f"/platform/studio/runs/{RUN_ID}/voice/upload",
                files={"file": ("voice.mp3", b"ID3" + b"\x00" * 64, "audio/mpeg")},
            )
        assert response.status_code == 500, response.text
        assert_restored(ledger, tenant)

    def test_script_generation_route(self, world, ledger):
        cookie, user = run(world.sign_in("boss@example.com", "sub-boss"))
        run(billing.topup(user.tenant_id, 100))
        with patch("cf_platform.interfaces.routes.blocks.create_run", side_effect=RuntimeError("database gone")):
            response = world.client(cookie).post(
                "/platform/blocks/idea-to-script", json={"idea_title": "Why starter homes vanished"})
        assert response.status_code == 500
        assert_restored(ledger, user.tenant_id)

    def test_script_generation_when_the_graph_cannot_be_built(self, world, ledger):
        cookie, user = run(world.sign_in("boss@example.com", "sub-boss"))
        run(billing.topup(user.tenant_id, 100))
        with patch("cf_platform.interfaces.routes.blocks.build_idea_to_script_graph", side_effect=RuntimeError("no graph")):
            response = world.client(cookie).post(
                "/platform/blocks/idea-to-script", json={"idea_title": "Why starter homes vanished"})
        assert response.status_code == 500
        assert_restored(ledger, user.tenant_id)

    def test_bulk_images_route_when_the_job_cannot_be_recorded(self, world, ledger):
        from cf_platform.workers.scene_images import job_is_active, release_job

        release_job(RUN_ID)
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)

        async def fake_plan(*_a, **_k):
            return {"scene_ids": ["1", "2"]}

        async def fake_context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04)

        fail_storage_writes(world, "images")
        with patch("cf_platform.interfaces.routes.studio_ai._plan", fake_plan), patch(
            "cf_platform.interfaces.routes.studio_ai._generation_context", fake_context
        ):
            response = world.client(cookie).post(f"/platform/studio/runs/{RUN_ID}/images/generate", json={})
        assert response.status_code == 500
        assert_restored(ledger, tenant)
        assert not job_is_active(RUN_ID), "the job claim was released"


# ── niche-to-ideas is billed (review fix 4) ──────────────────────────────


class TestNicheToIdeas:
    BODY = {"niche": "american housing"}

    def _super(self, w, credits):
        cookie, user = run(w.sign_in("boss@example.com", "sub-boss"))
        if credits:
            run(billing.topup(user.tenant_id, credits))
        return cookie, user.tenant_id

    def test_a_failed_run_is_refunded(self, world, ledger):
        cookie, tenant = self._super(world, 100)
        with patch("cf_platform.interfaces.routes.blocks.run_graph", AsyncMock(side_effect=RuntimeError("graph failed"))):
            response = world.client(cookie).post("/platform/blocks/niche-to-ideas", json=self.BODY)
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_not_enough_credits_is_refused_before_a_run_is_created(self, world, ledger):
        cookie, tenant = self._super(world, 5)
        response = world.client(cookie).post("/platform/blocks/niche-to-ideas", json=self.BODY)
        assert response.status_code == 402
        assert response.json()["cost_credits"] == 30 and response.json()["balance_credits"] == 5
        assert run(world.runs.list_runs(tenant_id=tenant)) == []

    def test_a_run_that_works_is_charged_its_price(self, world, ledger):
        from cf_platform.workers.opportunity_scorer import TopicScore

        cookie, tenant = self._super(world, 100)
        score = TopicScore(
            title="t", angle="a", novelty=1, audience_relevance=1, emotional_trigger=1, search_demand=1,
            competition=1, evergreen_potential=1, monetization_relevance=1, final_score=1)
        ranked = SimpleNamespace(selected=score, alternatives=[])
        with patch(
            "cf_platform.interfaces.routes.blocks.run_graph",
            AsyncMock(return_value=SimpleNamespace(artifacts={"ranked_ideas": "k"})),
        ), patch("cf_platform.interfaces.routes.blocks.read_artifact", AsyncMock(return_value=(None, {}))), patch(
            "cf_platform.interfaces.routes.blocks.RankedIdeasArtifact.model_validate", return_value=ranked
        ):
            response = world.client(cookie).post("/platform/blocks/niche-to-ideas", json=self.BODY)
        assert response.status_code == 200, response.text
        entries = run(ledger.list_entries(tenant))
        assert [(e.kind, e.what, e.status, e.credits) for e in entries] == [("llm", "finding ideas", "settled", 30)]
        assert run(ledger.balance(tenant)) == 70

    def test_the_price_is_listed_with_the_other_actions(self, world, ledger):
        cookie, _ = friend(world, credits=1)
        assert world.client(cookie).get("/platform/billing/me").json()["prices"]["ideas"] == 30

    def test_a_basic_account_still_cannot_reach_it(self, world, ledger):
        cookie, _ = friend(world, credits=100)
        assert world.client(cookie).post("/platform/blocks/niche-to-ideas", json=self.BODY).status_code in (302, 403)


# ── Cancellation of a running job refunds, then re-raises ────────────────


class TestCancellation:
    @pytest.fixture
    def funded(self, ledger):
        import uuid

        from cf_platform.core.accounts import Principal, reset_principal, set_principal

        tenant = f"u_{uuid.uuid4().hex[:10]}"
        run(ledger.credit(tenant, 100, kind="topup"))
        token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
        yield tenant
        reset_principal(token)

    def _hold(self, kind="tts", usd=0.05):
        cfg = billing.PlatformSettings.model_validate({
            "R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a",
            "BILLING_ENABLED": True})
        return run(billing.reserve(kind, usd, "x", settings=cfg))

    @staticmethod
    async def _cancelled(*_a, **_k):
        raise asyncio.CancelledError()

    def test_voice_job(self, ledger, funded):
        from cf_platform.core.schemas import StageState
        from cf_platform.interfaces.routes.workers import _run_voice_background

        hold = self._hold()
        with pytest.raises(asyncio.CancelledError):
            run(_run_voice_background(
                "r1", "j", StageState(run_id="r1", user_id="u", inputs={}), self._cancelled,
                SimpleNamespace(), hold))
        assert_restored(ledger, funded)

    def test_storyboard_job(self, ledger, funded):
        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.schemas import StageState
        from cf_platform.interfaces.routes.workers import _run_storyboard_background

        hold = self._hold("llm")
        with pytest.raises(asyncio.CancelledError):
            run(_run_storyboard_background(
                "r1", "j", StageState(run_id="r1", user_id="u", inputs={}), self._cancelled,
                InMemoryArtifactStorage(), hold=hold))
        assert_restored(ledger, funded)

    def test_render_job_also_gives_back_its_slot(self, ledger, funded):
        from cf_platform.core import limits
        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.schemas import StageState
        from cf_platform.interfaces.routes.workers import _run_render_background

        hold = self._hold("render")
        slot = limits.claim_render_slot()
        with pytest.raises(asyncio.CancelledError):
            run(_run_render_background(
                "r1", "j", StageState(run_id="r1", user_id="u", inputs={}), self._cancelled,
                InMemoryArtifactStorage(), None, slot, hold))
        assert_restored(ledger, funded)
        assert limits._active_renders.get(funded, 0) == 0

    def test_transcription_job(self, ledger, funded):
        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.schemas import StageState
        from cf_platform.core.trace_repo import InMemoryTraceEventRepository
        from cf_platform.interfaces.routes.studio_voice import _run_transcription_background

        hold = self._hold("transcription")
        with pytest.raises(asyncio.CancelledError):
            run(_run_transcription_background(
                "r1", "j", StageState(run_id="r1", user_id="u", inputs={}), self._cancelled,
                InMemoryArtifactStorage(), InMemoryTraceEventRepository(), 0.0043, 0.5, hold))
        assert_restored(ledger, funded)

    def test_bulk_image_job(self, ledger, funded):
        from cf_platform.interfaces.routes import studio_ai

        hold = self._hold("image", 0.12)
        with patch.object(studio_ai, "run_image_job", self._cancelled), pytest.raises(asyncio.CancelledError):
            run(studio_ai._run_billed_image_job(
                hold, SimpleNamespace(cost_usd=0.04), ["1", "2", "3"], job_id="j", concurrency=3))
        assert_restored(ledger, funded)

    def test_a_cancelled_job_with_no_hold_is_just_cancelled(self, ledger, funded):
        from cf_platform.core.schemas import StageState
        from cf_platform.interfaces.routes.workers import _run_voice_background

        with pytest.raises(asyncio.CancelledError):
            run(_run_voice_background(
                "r1", "j", StageState(run_id="r1", user_id="u", inputs={}), self._cancelled, SimpleNamespace(), None))


class TestRefundOnError:
    """The guard itself: any error, and a cancellation, gives the hold back and propagates."""

    def test_an_error_refunds_and_propagates(self, ledger):
        cfg = billing.PlatformSettings.model_validate({
            "R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a",
            "BILLING_ENABLED": True})
        from cf_platform.core.accounts import Principal, reset_principal, set_principal

        token = set_principal(Principal(user_id="u_guard", tenant_id="u_guard", account_type="basic"))
        try:
            run(ledger.credit("u_guard", 100, kind="topup"))

            async def go(exc):
                hold = await billing.reserve("tts", 0.05, "x", settings=cfg)
                async with billing.refund_on_error(hold, "the thing"):
                    raise exc

            for exc, expected in ((RuntimeError("boom"), RuntimeError), (asyncio.CancelledError(), asyncio.CancelledError)):
                with pytest.raises(expected):
                    run(go(exc))
            assert run(ledger.balance("u_guard")) == 100
            assert [e.status for e in run(ledger.list_entries("u_guard"))] == ["refunded", "refunded"]

            async def fine():
                hold = await billing.reserve("tts", 0.05, "x", settings=cfg)
                async with billing.refund_on_error(hold, "the thing"):
                    pass
                return hold

            hold = run(fine())
            assert run(ledger.get_entry(hold.entry_id)).status == "held", "success leaves the hold for the job"
            run(billing.refund_on_error(None, "x").__aenter__())  # no hold: nothing to give back
        finally:
            reset_principal(token)
