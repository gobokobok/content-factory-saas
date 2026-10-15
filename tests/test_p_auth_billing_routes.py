"""Sprint P-BILL-1 S2–S5 — the routes, with the real auth middleware and real session cookies (D123).

The file name starts with ``test_p_auth`` on purpose: conftest leaves the real, fail-closed
middleware on for those, and the billing routes are only meaningful for a signed-in user
who is not the owner. Covers the 402 refusal, the hold taken by the voice and director
routes, ``GET /platform/billing/me`` (own tenant only), the owner-only admin routes and the
sign-up grant.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from cf_platform.core import billing
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.run_manager import create_run
from tests.cf_platform.p13_helpers import RUN_ID, _lineage
from tests.test_p_auth_accounts import World


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def ledger(monkeypatch) -> InMemoryBillingStore:
    """Charging on and a fresh ledger for everything that resolves the billing store."""
    monkeypatch.setenv("BILLING_ENABLED", "true")
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    return fresh


@pytest.fixture
def world(ledger):
    w = World()
    yield w
    w.close()


def friend(w: World, email: str = "friend@example.com", sub: str = "sub-friend", credits: int = 0):
    """Sign a Basic friend in, optionally funded. Returns (cookie, tenant_id)."""
    cookie, user = run(w.sign_in(email, sub))
    if credits:
        run(billing.topup(user.tenant_id, credits))
    return cookie, user.tenant_id


def own_run(w: World, tenant: str) -> None:
    """A run named RUN_ID owned by tenant (the id the shared storyboard helpers seed)."""
    run(create_run(tenant, "creator", {}, w.runs, run_id=RUN_ID))


async def _seed_storyboard_for(w: World, tenant: str, storyboard) -> None:
    """Write a verified_storyboard artifact under the tenant's own prefix (the shared helper seeds the owner's)."""
    from datetime import datetime

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact

    await write_artifact(
        w.storage,
        VerifiedStoryboardArtifact(
            prompt_version="test", scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"), generated_at=datetime.now(),
        ),
        name="verified_storyboard", stage="storyboard", run_id=RUN_ID, user_id=tenant, lineage=_lineage(),
    )


# ── The refusal and the hold (S2, S3) ────────────────────────────────────


class TestVoiceRoute:
    BODY = {"run_id": RUN_ID, "script": "One two three."}

    def _post(self, w, cookie):
        held = []

        async def fake_bg(run_id, job_id, state, worker, storage, hold=None):
            held.append(hold)

        with patch("cf_platform.interfaces.routes.workers._run_voice_background", fake_bg):
            return w.client(cookie).post("/platform/workers/voice", json=self.BODY), held

    def test_a_funded_friend_is_charged_and_the_job_gets_the_hold(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)
        response, held = self._post(world, cookie)
        assert response.status_code == 202, response.text
        assert len(held) == 1 and held[0].credits == 10 and held[0].charged is True
        assert run(ledger.balance(tenant)) == 90

    def test_a_friend_who_cannot_pay_gets_402_with_the_numbers(self, world, ledger):
        cookie, tenant = friend(world, credits=5)
        own_run(world, tenant)
        response, held = self._post(world, cookie)
        assert response.status_code == 402
        assert response.json() == {
            "detail": "The voiceover costs 10 credits; you have 5.", "cost_credits": 10, "balance_credits": 5}
        assert held == []
        assert run(ledger.balance(tenant)) == 5

    def test_a_refused_voice_starts_nothing(self, world, ledger):
        cookie, tenant = friend(world)
        own_run(world, tenant)
        response, held = self._post(world, cookie)
        assert response.status_code == 402 and held == []
        with pytest.raises(Exception):
            run(world.storage.get_json(f"runs/{RUN_ID}/voice/current_job.json"))

    def test_billing_off_never_refuses(self, world, ledger, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "false")
        cookie, tenant = friend(world)
        own_run(world, tenant)
        response, held = self._post(world, cookie)
        assert response.status_code == 202 and held[0].charged is False
        assert run(ledger.list_entries(tenant))[0].status == "metered"

    def test_the_owner_is_never_charged(self, world, ledger):
        cookie, user = run(world.sign_in("owner@example.com", "sub-owner"))
        run(create_run(user.tenant_id, "creator", {}, world.runs, run_id=RUN_ID))
        response, held = self._post(world, cookie)
        assert response.status_code == 202 and held[0].charged is False
        assert [e.status for e in run(ledger.list_entries(user.tenant_id))] == ["exempt"]


class TestWritePromptRoute:
    URL = f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2/write-prompt"

    def _setup(self, w, credits):
        from cf_platform.workers import scene_prompt_writer  # noqa: F401
        from tests.cf_platform.test_p_lite_scene_prompt import _animated

        cookie, tenant = friend(w, credits=credits)
        own_run(w, tenant)
        run(_seed_storyboard_for(w, tenant, _animated()))
        return cookie, tenant

    def test_a_failed_director_call_is_refunded(self, world, ledger):
        from cf_platform.workers import scene_prompt_writer as spw

        cookie, tenant = self._setup(world, 100)

        async def fake(system, user, key):
            return "sorry, no json"

        with patch.object(spw, "request_scene_prompt", fake):
            response = world.client(cookie).post(self.URL)
        assert response.status_code == 502
        assert [e.status for e in run(ledger.list_entries(tenant))] == ["refunded"]
        assert run(ledger.balance(tenant)) == 100

    def test_a_good_answer_is_charged(self, world, ledger):
        from cf_platform.workers import scene_prompt_writer as spw
        from tests.cf_platform.test_p_lite_scene_prompt import ANSWER

        cookie, tenant = self._setup(world, 100)

        async def fake(system, user, key):
            return ANSWER

        with patch.object(spw, "request_scene_prompt", fake):
            response = world.client(cookie).post(self.URL)
        assert response.status_code == 200, response.text
        assert [e.status for e in run(ledger.list_entries(tenant))] == ["settled"]
        assert run(ledger.balance(tenant)) == 90

    def test_a_friend_who_cannot_pay_is_refused_before_the_model_is_called(self, world, ledger):
        from cf_platform.workers import scene_prompt_writer as spw

        cookie, tenant = self._setup(world, 0)
        called = []

        async def fake(system, user, key):
            called.append(1)
            return json.dumps({})

        with patch.object(spw, "request_scene_prompt", fake):
            response = world.client(cookie).post(self.URL)
        assert response.status_code == 402 and called == []
        assert run(ledger.list_entries(tenant)) == []


def route_source(module_path: str, function: str) -> str:
    """The source text of one top-level function, read from the file (not from the imported object, which other tests patch)."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / module_path).read_text()
    match = re.search(rf"^async def {function}\(.*?(?=^(?:async def |def |@router|class )|\Z)", text, re.S | re.M)
    assert match, f"{function} not found in {module_path}"
    return match.group(0)


class TestOrderingInTheRoutes:
    """Where a route takes its hold decides whether a refusal can leave something half done."""

    WORKERS = "cf_platform/interfaces/routes/workers.py"

    def test_the_render_route_holds_before_it_marks_the_job_running(self):
        source = route_source(self.WORKERS, "render_worker_endpoint")
        assert source.index("billing.reserve(") < source.index("current_job.json")
        assert source.index("billing.refund(") > source.index("claim_render_slot")

    def test_the_voice_route_holds_after_every_check_that_can_refuse(self):
        voice = route_source(self.WORKERS, "voice_worker_endpoint")
        assert voice.index("_enforce_script_lock") < voice.index("billing.reserve(")
        assert voice.index("pending is not None") < voice.index("billing.reserve(")
        assert voice.index("billing.reserve(") < voice.index("current_job.json")

    def test_the_storyboard_route_holds_after_it_has_what_it_needs_and_before_the_job_starts(self):
        storyboard = route_source(self.WORKERS, "storyboard_worker_endpoint")
        assert storyboard.index("voice_alignment") < storyboard.index("billing.reserve(")
        assert storyboard.index("billing.reserve(") < storyboard.index("current_job.json")

    def test_the_transcription_hold_is_taken_before_anything_is_discarded(self):
        source = route_source("cf_platform/interfaces/routes/studio_voice.py", "studio_upload_voice")
        assert source.index("billing.reserve(") < source.index("discard_storyboard(")

    def test_the_script_route_holds_after_the_run_lookup_and_before_a_run_is_created(self):
        source = route_source("cf_platform/interfaces/routes/blocks.py", "idea_to_script")
        assert source.index("RunNotFoundError") < source.index("billing.reserve(") < source.index("create_run(")


# ── The user's own view (S5) ─────────────────────────────────────────────


class TestMe:
    def test_a_friend_sees_balance_prices_and_history(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        r = world.client(cookie).get("/platform/billing/me")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is True and body["exempt"] is False and body["balance"] == 100
        assert body["history"] == []
        assert body["prices"]["voice"] == 10 and body["prices"]["storyboard"] == 10
        assert body["prices"]["render"] == 10 and body["prices"]["ideas"] == 30
        assert body["credit_value_usd"] == 0.01
        assert "markup" not in json.dumps(body).lower()

    def test_history_lists_the_friends_priced_actions_newest_first(self, world, ledger):
        cookie, tenant = friend(world, credits=100)
        own_run(world, tenant)
        from cf_platform.core.accounts import Principal, reset_principal, set_principal

        token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
        try:
            first = run(billing.reserve("llm", 0.05, "writing the storyboard", run_id=RUN_ID))
            run(billing.settle(first))
            run(billing.reserve("tts", 0.05, "the voiceover", run_id=RUN_ID))
        finally:
            reset_principal(token)
        body = world.client(cookie).get("/platform/billing/me").json()
        assert [(h["what"], h["status"], h["credits"]) for h in body["history"]] == [
            ("the voiceover", "held", 10), ("writing the storyboard", "settled", 10)]
        assert body["balance"] == 80

    def test_one_friend_never_sees_another_friends_account(self, world, ledger):
        cookie_a, _ = friend(world, "friend@example.com", "sub-a", credits=100)
        cookie_b, tenant_b = friend(world, "other@example.com", "sub-b", credits=7)
        assert world.client(cookie_a).get("/platform/billing/me").json()["balance"] == 100
        assert world.client(cookie_b).get("/platform/billing/me").json()["balance"] == 7
        # there is no parameter that selects another tenant
        other = world.client(cookie_a).get("/platform/billing/me", params={"tenant_id": tenant_b})
        assert other.json()["balance"] == 100

    def test_it_needs_a_session(self, world):
        assert world.client().get("/platform/billing/me").status_code == 401

    def test_the_owner_is_shown_as_exempt(self, world):
        cookie, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        body = world.client(cookie).get("/platform/billing/me").json()
        assert body["enabled"] is False and body["exempt"] is True

    def test_billing_off_is_reported_so_the_page_can_hide_credits(self, world, monkeypatch):
        monkeypatch.setenv("BILLING_ENABLED", "false")
        cookie, _ = friend(world)
        assert world.client(cookie).get("/platform/billing/me").json()["enabled"] is False

    def test_a_basic_account_may_call_it_and_the_allow_list_says_so(self):
        from cf_platform.core.gating import basic_may

        assert basic_may("GET", "/platform/billing/me")
        assert not basic_may("POST", "/platform/billing/me")
        for path in ("users", "usage"):
            assert not basic_may("GET", f"/platform/admin/billing/{path}")
        assert not basic_may("POST", "/platform/admin/billing/topup")
        assert not basic_may("POST", "/platform/admin/billing/refund-stale")


# ── The owner's top-up and admin view (S4) ───────────────────────────────


class TestAdmin:
    def _owner(self, w):
        cookie, _ = run(w.sign_in("owner@example.com", "sub-owner"))
        return w.client(cookie)

    def test_the_owner_tops_an_account_up_by_email(self, world, ledger):
        _, tenant = friend(world)
        r = self._owner(world).post(
            "/platform/admin/billing/topup", json={"email": "Friend@Example.com", "credits": 500, "note": "beta"})
        assert r.status_code == 200, r.text
        assert r.json() == {"tenant_id": tenant, "balance": 500}
        tx = run(ledger.list_transactions(tenant))[0]
        assert (tx.kind, tx.actor, tx.note) == ("topup", "owner@example.com", "beta")

    def test_or_by_tenant_id(self, world, ledger):
        _, tenant = friend(world)
        r = self._owner(world).post("/platform/admin/billing/topup", json={"tenant_id": tenant, "credits": 20})
        assert r.json()["balance"] == 20

    def test_a_removal_below_zero_is_refused(self, world, ledger):
        _, tenant = friend(world, credits=10)
        r = self._owner(world).post("/platform/admin/billing/topup", json={"tenant_id": tenant, "credits": -11})
        assert r.status_code == 409 and "below zero" in r.json()["detail"]
        assert run(ledger.balance(tenant)) == 10

    def test_an_unknown_account_gets_nothing(self, world, ledger):
        owner = self._owner(world)
        assert owner.post("/platform/admin/billing/topup", json={"email": "nobody@example.com", "credits": 5}).status_code == 404
        assert owner.post("/platform/admin/billing/topup", json={"tenant_id": "u_ghost", "credits": 5}).status_code == 404
        assert owner.post("/platform/admin/billing/topup", json={"credits": 5}).status_code == 422
        assert run(ledger.balance("u_ghost")) == 0

    def test_absurd_amounts_are_refused(self, world, ledger):
        _, tenant = friend(world)
        r = self._owner(world).post("/platform/admin/billing/topup", json={"tenant_id": tenant, "credits": 10**9})
        assert r.status_code == 422

    def test_users_lists_balances_and_usage_without_the_owner(self, world, ledger):
        _, tenant = friend(world, credits=100)
        run(ledger.add_entry(billing.UsageEntry(
            tenant_id=tenant, kind="image", credits=8, raw_cost_usd=0.04, status="settled")))
        rows = self._owner(world).get("/platform/admin/billing/users").json()
        row = next(r for r in rows if r["tenant_id"] == tenant)
        assert row["email"] == "friend@example.com" and row["balance"] == 100
        assert row["credits_spent"] == 8 and row["actions"] == 1 and row["raw_cost_usd"] == 0.04
        assert all(r["tenant_id"] != "operator" for r in rows)

    def test_a_user_with_no_activity_is_listed_with_zeros(self, world, ledger):
        _, tenant = friend(world)
        row = next(r for r in self._owner(world).get("/platform/admin/billing/users").json() if r["tenant_id"] == tenant)
        assert (row["balance"], row["credits_spent"], row["actions"], row["last_action_at"]) == (0, 0, 0, None)

    def test_usage_filters_by_tenant_and_kind(self, world, ledger):
        _, a = friend(world, "friend@example.com", "sub-a")
        _, b = friend(world, "other@example.com", "sub-b")
        run(ledger.add_entry(billing.UsageEntry(tenant_id=a, kind="tts")))
        run(ledger.add_entry(billing.UsageEntry(tenant_id=a, kind="image")))
        run(ledger.add_entry(billing.UsageEntry(tenant_id=b, kind="tts")))
        owner = self._owner(world)
        assert len(owner.get("/platform/admin/billing/usage").json()) == 3
        assert len(owner.get("/platform/admin/billing/usage", params={"tenant_id": a}).json()) == 2
        assert [e["kind"] for e in owner.get("/platform/admin/billing/usage", params={"tenant_id": a, "kind": "image"}).json()] == ["image"]
        assert owner.get("/platform/admin/billing/usage", params={"limit": 0}).status_code == 422

    def test_stale_holds_can_be_given_back(self, world, ledger):
        from datetime import UTC, datetime, timedelta

        _, tenant = friend(world, credits=100)
        run(ledger.debit(tenant, 10, kind="hold"))
        run(ledger.add_entry(billing.UsageEntry(
            tenant_id=tenant, kind="tts", credits=10, status="held",
            created_at=datetime.now(UTC) - timedelta(hours=9))))
        r = self._owner(world).post("/platform/admin/billing/refund-stale")
        assert r.json() == {"refunded": 1}
        assert run(ledger.balance(tenant)) == 100

    def test_no_one_but_the_owner_may_use_the_admin_routes(self, world, ledger):
        cookie, tenant = friend(world, credits=10)
        super_cookie, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        for who in (world.client(cookie), world.client(super_cookie), world.client()):
            assert who.get("/platform/admin/billing/users").status_code in (401, 403)
            assert who.get("/platform/admin/billing/usage").status_code in (401, 403)
            assert who.post("/platform/admin/billing/topup", json={"tenant_id": tenant, "credits": 1}).status_code in (401, 403)
            assert who.post("/platform/admin/billing/refund-stale").status_code in (401, 403)
        assert run(ledger.balance(tenant)) == 10

    def test_view_as_basic_loses_the_admin_routes(self, world, ledger):
        cookie, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        client = world.client(cookie)
        assert client.post("/auth/view-as", json={"basic": True}).status_code == 200
        assert client.get("/platform/admin/billing/users").status_code in (302, 403)


class TestSignUpGrant:
    def test_a_new_account_gets_its_sign_up_credits_once(self, world, ledger, monkeypatch):
        from src.routes.auth import _grant_signup_credits

        monkeypatch.setenv("SIGNUP_CREDITS", "50")
        run(_grant_signup_credits("u_new"))
        run(_grant_signup_credits("u_new"))
        assert run(ledger.balance("u_new")) == 50

    def test_none_by_default_and_never_for_the_owner(self, world, ledger, monkeypatch):
        from src.routes.auth import _grant_signup_credits

        run(_grant_signup_credits("u_new"))
        monkeypatch.setenv("SIGNUP_CREDITS", "50")
        run(_grant_signup_credits("operator"))
        assert run(ledger.balance("u_new")) == 0 and run(ledger.balance("operator")) == 0

    def test_a_billing_fault_never_blocks_sign_in(self, world, ledger, monkeypatch):
        from src.routes.auth import _grant_signup_credits

        async def broken(*_a, **_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(billing, "grant_signup_credits", broken)
        run(_grant_signup_credits("u_new"))  # does not raise


class TestPaymentRequiredHandler:
    def test_the_402_body_carries_the_numbers_as_fields(self):
        from cf_platform.core.billing import PaymentRequiredError

        exc = PaymentRequiredError(12, 3, "image generation")
        assert exc.status_code == 402 and (exc.cost_credits, exc.balance_credits) == (12, 3)
        assert exc.detail == "Image generation costs 12 credits; you have 3."


# ── Images and scripts: the same hold, settle and refund ─────────────────


class TestImageRoutes:
    @pytest.fixture(autouse=True)
    def _no_leftover_job(self):
        """A bulk job claimed by one test must not make the next one answer "already running"."""
        from cf_platform.workers.scene_images import release_job

        release_job(RUN_ID)
        yield
        release_job(RUN_ID)

    def _setup(self, w, credits):
        from tests.cf_platform.test_p_lite_scene_prompt import _animated

        cookie, tenant = friend(w, credits=credits)
        own_run(w, tenant)
        run(_seed_storyboard_for(w, tenant, _animated()))
        return cookie, tenant

    def _generate(self, w, cookie, fake_generate):
        from types import SimpleNamespace

        async def fake_context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04, cap_usd=2.0)

        with patch("cf_platform.interfaces.routes.studio_ai._generation_context", fake_context), patch(
            "cf_platform.interfaces.routes.studio_ai.generate_scene_image", fake_generate
        ), patch("cf_platform.interfaces.routes.studio_ai.spend_summary", lambda *_a, **_k: {}):
            return w.client(cookie).post(
                f"/platform/studio/runs/{RUN_ID}/scenes/2/generate", json={"prompt": "a quiet street at dusk"})

    def test_a_generated_image_is_charged_at_the_models_price(self, world, ledger):
        cookie, tenant = self._setup(world, 100)

        async def ok(ctx, scene, prompt):
            return {"file_key": "k.png", "ai_prompt": prompt, "ledger": {}}

        response = self._generate(world, cookie, ok)
        assert response.status_code == 200, response.text
        assert [(e.kind, e.status, e.credits) for e in run(ledger.list_entries(tenant))] == [("image", "settled", 8)]
        assert run(ledger.balance(tenant)) == 92

    def test_a_provider_failure_is_a_502_and_costs_nothing(self, world, ledger):
        from cf_platform.core.image_provider import ImageGenerationError

        cookie, tenant = self._setup(world, 100)

        async def boom(ctx, scene, prompt):
            raise ImageGenerationError("provider said no")

        response = self._generate(world, cookie, boom)
        assert response.status_code == 502
        assert [e.status for e in run(ledger.list_entries(tenant))] == ["refunded"]
        assert run(ledger.balance(tenant)) == 100

    def test_an_unexpected_crash_is_refunded_too(self, world, ledger):
        cookie, tenant = self._setup(world, 100)

        async def crash(ctx, scene, prompt):
            raise RuntimeError("storage fell over")

        assert self._generate(world, cookie, crash).status_code == 500
        assert run(ledger.balance(tenant)) == 100

    def test_not_enough_credits_for_an_image_never_reaches_the_provider(self, world, ledger):
        cookie, tenant = self._setup(world, 3)
        called = []

        async def never(ctx, scene, prompt):
            called.append(1)
            return {}

        response = self._generate(world, cookie, never)
        assert response.status_code == 402 and called == []
        assert response.json()["cost_credits"] == 8 and response.json()["balance_credits"] == 3

    def test_generate_all_holds_the_whole_batch_and_hands_the_hold_to_the_job(self, world, ledger):
        from types import SimpleNamespace

        cookie, tenant = self._setup(world, 100)
        seen = []

        async def fake_plan(*_a, **_k):
            return {"scene_ids": ["1", "2", "3"]}

        async def fake_context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04)

        async def fake_job(hold, ctx, scene_ids, *, job_id, concurrency):
            seen.append((hold, scene_ids))

        with patch("cf_platform.interfaces.routes.studio_ai._plan", fake_plan), patch(
            "cf_platform.interfaces.routes.studio_ai._generation_context", fake_context
        ), patch("cf_platform.interfaces.routes.studio_ai._run_billed_image_job", fake_job):
            response = world.client(cookie).post(f"/platform/studio/runs/{RUN_ID}/images/generate", json={})
        assert response.status_code == 202, response.text
        hold, ids = seen[0]
        assert hold.credits == 24 and ids == ["1", "2", "3"]
        assert run(ledger.balance(tenant)) == 76

    def test_generate_all_that_cannot_be_paid_for_starts_no_job(self, world, ledger):
        from types import SimpleNamespace

        cookie, tenant = self._setup(world, 10)
        seen = []

        async def fake_plan(*_a, **_k):
            return {"scene_ids": ["1", "2", "3"]}

        async def fake_context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04)

        async def fake_job(*a, **k):
            seen.append(1)

        with patch("cf_platform.interfaces.routes.studio_ai._plan", fake_plan), patch(
            "cf_platform.interfaces.routes.studio_ai._generation_context", fake_context
        ), patch("cf_platform.interfaces.routes.studio_ai._run_billed_image_job", fake_job):
            response = world.client(cookie).post(f"/platform/studio/runs/{RUN_ID}/images/generate", json={})
        assert response.status_code == 402 and seen == []
        assert response.json()["cost_credits"] == 24 and response.json()["balance_credits"] == 10
        from cf_platform.workers.scene_images import job_is_active

        assert not job_is_active(RUN_ID)

    def test_a_job_already_running_gives_the_hold_back(self, world, ledger):
        from types import SimpleNamespace

        cookie, tenant = self._setup(world, 100)

        async def fake_plan(*_a, **_k):
            return {"scene_ids": ["1"]}

        async def fake_context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04)

        with patch("cf_platform.interfaces.routes.studio_ai._plan", fake_plan), patch(
            "cf_platform.interfaces.routes.studio_ai._generation_context", fake_context
        ), patch("cf_platform.interfaces.routes.studio_ai.claim_job", lambda _run: False):
            response = world.client(cookie).post(f"/platform/studio/runs/{RUN_ID}/images/generate", json={})
        assert response.status_code == 202 and response.json()["already_running"] is True
        assert run(ledger.balance(tenant)) == 100

    def test_the_plan_shows_the_price_in_credits_before_anything_is_spent(self, world, ledger):
        import inspect

        from cf_platform.interfaces.routes import studio_ai

        source = inspect.getsource(studio_ai._plan)
        assert '"estimated_credits"' in source and '"credits_per_image"' in source


class TestScriptRoute:
    """POST /platform/blocks/idea-to-script is Super's; a Super account that is not the owner is charged."""

    BODY = {"idea_title": "Why starter homes vanished", "max_iterations": 2}

    def _super(self, w, credits):
        cookie, user = run(w.sign_in("boss@example.com", "sub-boss"))
        if credits:
            run(billing.topup(user.tenant_id, credits))
        return cookie, user.tenant_id

    def test_a_failed_generation_is_refunded_and_the_error_surfaces(self, world, ledger):
        cookie, tenant = self._super(world, 100)

        async def boom(*_a, **_k):
            raise RuntimeError("the graph failed")

        with patch("cf_platform.interfaces.routes.blocks.run_graph", boom):
            response = world.client(cookie).post("/platform/blocks/idea-to-script", json=self.BODY)
        assert response.status_code == 500
        assert [(e.kind, e.status) for e in run(ledger.list_entries(tenant))] == [("llm", "refunded")]
        assert run(ledger.balance(tenant)) == 100

    def test_the_hold_is_for_every_iteration_the_request_allows(self, world, ledger):
        cookie, tenant = self._super(world, 100)

        async def boom(*_a, **_k):
            raise RuntimeError("stop here")

        with patch("cf_platform.interfaces.routes.blocks.run_graph", boom):
            world.client(cookie).post("/platform/blocks/idea-to-script", json=self.BODY)
        entry = run(ledger.list_entries(tenant))[0]
        assert entry.raw_cost_usd == pytest.approx(0.10)  # 2 iterations x $0.05
        assert entry.units == 2.0

    def test_not_enough_credits_refuses_before_any_run_is_created(self, world, ledger):
        cookie, tenant = self._super(world, 5)
        response = world.client(cookie).post("/platform/blocks/idea-to-script", json=self.BODY)
        assert response.status_code == 402
        assert response.json()["cost_credits"] == 20 and response.json()["balance_credits"] == 5
        assert run(world.runs.list_runs(tenant_id=tenant)) == []


class TestMetadataRoute:
    """The metadata call is a paid LLM call: held before, refunded on failure, settled on success (Super, not the owner)."""

    BODY = {"run_id": RUN_ID}

    def _post(self, w, credits, worker_factory):
        from unittest.mock import AsyncMock

        cookie, user = run(w.sign_in("boss@example.com", "sub-boss"))
        if credits:
            run(billing.topup(user.tenant_id, credits))
        run(create_run(user.tenant_id, "creator", {}, w.runs, run_id=RUN_ID))
        with patch("cf_platform.interfaces.routes.workers._latest_artifact_key", AsyncMock(return_value="script-key")), patch(
            "cf_platform.workers.youtube_metadata.build_youtube_metadata_worker", worker_factory
        ):
            return w.client(cookie).post("/platform/workers/metadata", json=self.BODY), user.tenant_id

    def test_a_failed_metadata_call_is_refunded(self, world, ledger):
        from cf_platform.core.llm import LLMError

        def factory(*_a, **_k):
            async def worker(_state):
                raise LLMError("model overloaded")

            return worker

        response, tenant = self._post(world, 100, factory)
        assert response.status_code == 502
        assert [e.status for e in run(ledger.list_entries(tenant))] == ["refunded"]
        assert run(ledger.balance(tenant)) == 100

    def test_not_enough_credits_refuses_before_the_model_is_called(self, world, ledger):
        called = []

        def factory(*_a, **_k):
            async def worker(_state):
                called.append(1)

            return worker

        response, tenant = self._post(world, 0, factory)
        assert response.status_code == 402 and called == []
        assert response.json()["cost_credits"] == 10
