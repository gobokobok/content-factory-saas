"""BILL-F2 — a user is not charged for a result the platform then lost (D123).

Each paid path whose provider call succeeds and is followed by work that can still fail:
the script and ideas blocks (run bookkeeping and artifact read), metadata (the artifact write),
the single image (building the response) and the director (saving the prompt). Each test injects
the failure AFTER the provider call and asserts the balance. The one deliberate exception is the
director's 409 (the scene was merged or split meanwhile): the cost is real and the cause is the
user's own edit, so it stays charged (D123).
Background jobs (storyboard, voice, render, transcription, bulk images) already settle as their
last step; tests/test_p_auth_billing_leaks.py covers their failures.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cf_platform.core import billing
from cf_platform.core.run_manager import create_run
from tests.cf_platform.p13_helpers import RUN_ID
from tests.test_p_auth_billing_leaks import assert_restored, ledger, world  # noqa: F401  (fixtures)
from tests.test_p_auth_billing_routes import _seed_storyboard_for, friend, own_run


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


def super_account(w, credits):
    """A signed-in Super (non-owner) account, funded. Returns (cookie, tenant)."""
    cookie, user = run(w.sign_in("boss@example.com", "sub-boss"))
    run(billing.topup(user.tenant_id, credits))
    return cookie, user.tenant_id


class TestBlocks:
    def test_ideas_that_cannot_be_read_back_are_refunded(self, world, ledger):
        cookie, tenant = super_account(world, 100)
        with patch(
            "cf_platform.interfaces.routes.blocks.run_graph",
            AsyncMock(return_value=SimpleNamespace(artifacts={"ranked_ideas": "k"})),
        ), patch("cf_platform.interfaces.routes.blocks.read_artifact", AsyncMock(side_effect=RuntimeError("gone"))):
            response = world.client(cookie).post("/platform/blocks/niche-to-ideas", json={"niche": "housing"})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_ideas_whose_run_cannot_be_completed_are_refunded(self, world, ledger):
        cookie, tenant = super_account(world, 100)
        with patch(
            "cf_platform.interfaces.routes.blocks.run_graph",
            AsyncMock(return_value=SimpleNamespace(artifacts={"ranked_ideas": "k"})),
        ), patch(
            "cf_platform.interfaces.routes.blocks.transition_run",
            AsyncMock(side_effect=[SimpleNamespace(run_id="r1"), RuntimeError("run store down")]),
        ), patch("cf_platform.interfaces.routes.blocks.create_run", AsyncMock(return_value=SimpleNamespace(run_id="r1"))):
            response = world.client(cookie).post("/platform/blocks/niche-to-ideas", json={"niche": "housing"})
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_a_script_that_cannot_be_read_back_is_refunded(self, world, ledger):
        cookie, tenant = super_account(world, 100)
        with patch(
            "cf_platform.interfaces.routes.blocks.run_graph",
            AsyncMock(return_value=SimpleNamespace(artifacts={"script": "k"}, iteration=1)),
        ), patch("cf_platform.interfaces.routes.blocks.read_artifact", AsyncMock(side_effect=RuntimeError("gone"))):
            response = world.client(cookie).post(
                "/platform/blocks/idea-to-script", json={"idea_title": "Why starter homes vanished", "max_iterations": 2})
        assert response.status_code == 500
        assert_restored(ledger, tenant)


class TestMetadata:
    def test_a_metadata_artifact_that_cannot_be_saved_is_refunded(self, world, ledger):
        class Artifact:
            """Stands in for YoutubeMetadataArtifact."""

        def factory(*_a, **_k):
            async def worker(_state):
                return SimpleNamespace(artifact=Artifact())

            return worker

        cookie, user = run(world.sign_in("boss@example.com", "sub-boss"))
        run(billing.topup(user.tenant_id, 100))
        run(create_run(user.tenant_id, "creator", {}, world.runs, run_id=RUN_ID))
        with patch(
            "cf_platform.interfaces.routes.workers._latest_artifact_key", AsyncMock(return_value="script-key")
        ), patch("cf_platform.workers.youtube_metadata.build_youtube_metadata_worker", factory), patch(
            "cf_platform.workers.youtube_metadata.YoutubeMetadataArtifact", Artifact
        ), patch(
            "cf_platform.core.artifact_manager.write_artifact", AsyncMock(side_effect=RuntimeError("R2 is down"))
        ):
            response = world.client(cookie).post("/platform/workers/metadata", json={"run_id": RUN_ID})
        assert response.status_code == 500
        assert_restored(ledger, user.tenant_id)


class TestSingleImage:
    def _setup(self, w):
        from tests.cf_platform.test_p_lite_scene_prompt import _animated

        cookie, tenant = friend(w, credits=100)
        own_run(w, tenant)
        run(_seed_storyboard_for(w, tenant, _animated()))
        return cookie, tenant

    def test_an_image_whose_response_cannot_be_built_is_refunded(self, world, ledger):
        cookie, tenant = self._setup(world)

        async def context(*_a, **_k):
            return SimpleNamespace(cost_usd=0.04, cap_usd=2.0)

        async def made(ctx, scene, prompt):
            return {"file_key": "k.png", "ai_prompt": prompt, "ledger": {}}

        with patch("cf_platform.interfaces.routes.studio_ai._generation_context", context), patch(
            "cf_platform.interfaces.routes.studio_ai.generate_scene_image", made
        ), patch("cf_platform.interfaces.routes.studio_ai.spend_summary", side_effect=RuntimeError("bad ledger")):
            response = world.client(cookie).post(
                f"/platform/studio/runs/{RUN_ID}/scenes/2/generate", json={"prompt": "a quiet street at dusk"})
        assert response.status_code == 500
        assert_restored(ledger, tenant)


class TestDirector:
    URL = f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2/write-prompt"

    def _post(self, w, **patches):
        from cf_platform.workers import scene_prompt_writer as spw
        from tests.cf_platform.test_p_lite_scene_prompt import ANSWER, _animated

        cookie, tenant = friend(w, credits=100)
        own_run(w, tenant)
        run(_seed_storyboard_for(w, tenant, _animated()))

        async def fake(system, user, key):
            return ANSWER

        with patch.object(spw, "request_scene_prompt", fake):
            if not patches:
                return w.client(cookie).post(self.URL), tenant
            with patch.multiple("cf_platform.interfaces.routes.studio_animation", **patches):
                return w.client(cookie).post(self.URL), tenant

    def test_a_scene_merged_meanwhile_stays_charged(self, world, ledger):
        response, tenant = self._post(world, apply_scene_prompt=lambda *_a, **_k: None)
        assert response.status_code == 409
        assert [(e.kind, e.status) for e in run(ledger.list_entries(tenant))] == [("llm", "settled")]
        assert run(ledger.balance(tenant)) == 90

    def test_a_prompt_that_cannot_be_saved_is_refunded(self, world, ledger):
        response, tenant = self._post(world, _respond=AsyncMock(side_effect=RuntimeError("R2 is down")))
        assert response.status_code == 500
        assert_restored(ledger, tenant)

    def test_the_good_path_is_charged_once(self, world, ledger):
        response, tenant = self._post(world)
        assert response.status_code == 200, response.text
        assert [e.status for e in run(ledger.list_entries(tenant))] == ["settled"]
        assert run(ledger.balance(tenant)) == 90
