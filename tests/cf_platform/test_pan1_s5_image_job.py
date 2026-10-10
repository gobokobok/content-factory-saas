"""Tests for P-AN1-S5: generating every missing image of a run in one confirmed action."""

import asyncio

import pytest

from cf_platform.core.ai_images import (
    SpendCapReachedError,
    effective_spend_cap,
    ensure_under_cap,
    read_spend,
)
from cf_platform.workers import scene_images
from cf_platform.workers.scene_images import (
    ImageGenContext,
    claim_job,
    generate_scene_image,
    read_job,
    release_job,
    run_image_job,
    scenes_missing_images,
)
from tests.cf_platform.p13_helpers import RUN_ID
from tests.cf_platform.pan1_helpers import FakeProvider, _load, animation_env

_RUN = f"/platform/studio/runs/{RUN_ID}"


def _ctx(env, *, cap: float = 2.0, cost: float = 0.5) -> ImageGenContext:
    """A generation context on the env's storage with the fake provider."""
    return ImageGenContext(
        storage=env.storage, run_id=RUN_ID, provider=FakeProvider("kie", "k", "kie-model"),
        provider_name="kie", model="kie-model", cost_usd=cost, cap_usd=cap, aspect_ratio="9:16",
        master_style="STYLE",
    )


def _spent(env) -> tuple[int, float]:
    """(number of ledger entries, total) of the run."""
    ledger = asyncio.run(read_spend(env.storage, RUN_ID))
    return len(ledger["generations"]), ledger["total_usd"]


class TestCapHelpers:
    def test_reserved_spend_counts_against_the_cap(self):
        ledger = {"total_usd": 1.0}
        ensure_under_cap(ledger, 0.5, 2.0, reserved_usd=0.5)
        with pytest.raises(SpendCapReachedError):
            ensure_under_cap(ledger, 0.5, 2.0, reserved_usd=1.0)

    def test_a_runs_own_cap_wins_and_is_clamped_to_the_maximum(self):
        assert effective_spend_cap(None, 2.0, 10.0) == 2.0
        assert effective_spend_cap(5.0, 2.0, 10.0) == 5.0
        assert effective_spend_cap(50.0, 2.0, 10.0) == 10.0
        assert effective_spend_cap(0.0, 2.0, 10.0) == 0.0


class TestPlan:
    def test_the_plan_counts_missing_scenes_and_what_they_cost(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1",)) as env:
            plan = env.client.get(f"{_RUN}/images/plan").json()
            assert plan["scene_ids"] == ["2", "3"] and plan["count"] == 2
            assert (plan["cost_per_image_usd"], plan["estimated_cost_usd"]) == (0.5, 1.0)
            assert (plan["spent_usd"], plan["cap_usd"], plan["remaining_usd"], plan["cap_max_usd"]) == (0.0, 2.0, 2.0, 10.0)
            assert plan["affordable"] == 2 and plan["job_active"] is False and plan["model"] == "kie-model"
            assert FakeProvider.calls == []  # looking costs nothing

    def test_scenes_without_a_prompt_are_listed_not_counted(self, monkeypatch):
        with animation_env(monkeypatch, **{"2": {"ai_prompt": None}}) as env:
            plan = env.client.get(f"{_RUN}/images/plan").json()
            assert plan["scene_ids"] == ["1", "3"] and plan["without_prompt"] == ["2"]

    def test_named_scenes_are_planned_even_when_they_have_an_image(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1", "2", "3")) as env:
            assert env.client.get(f"{_RUN}/images/plan").json()["count"] == 0
            plan = env.client.get(f"{_RUN}/images/plan?scene_ids=1,3").json()
            assert plan["scene_ids"] == ["1", "3"]
            assert env.client.get(f"{_RUN}/images/plan?scene_ids=9").status_code == 404

    def test_the_cap_limits_what_is_affordable(self, monkeypatch):
        with animation_env(monkeypatch, cap=1.2) as env:
            plan = env.client.get(f"{_RUN}/images/plan").json()
            assert plan["count"] == 3 and plan["affordable"] == 2


class TestJobThroughTheApi:
    def test_generate_all_fills_every_missing_scene_and_skips_the_ones_that_have_an_image(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1",)) as env:
            r = env.client.post(f"{_RUN}/images/generate", json={})
            assert r.status_code == 202, r.text
            assert r.json()["job"]["total"] == 2
            job = env.client.get(f"{_RUN}/images/status").json()
            assert (job["status"], job["done"], job["left"], job["failed"]) == ("complete", 2, 0, [])
            assert job["scenes"] == {"2": "done", "3": "done"}
            assert sorted(p.split("\n\n")[0] for p, _ in FakeProvider.calls) == ["prompt 2", "prompt 3"]
            entries = {e["scene_id"]: e for e in env.manifest_entries()}
            assert all(e["status"] == "acquired" and e["source"] == "ai_generated" for e in entries.values())
            assert entries["1"]["file_key"].endswith("_ai_old.png")  # untouched
            assert _spent(env) == (2, 1.0)

    def test_the_assembled_prompt_is_what_the_job_sends(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            env.client.post(f"{_RUN}/images/generate", json={"scene_ids": ["1"]})
            sent = FakeProvider.calls[0][0]
            assert sent.startswith("prompt 1\n\nThe learner:") and sent.endswith("Vertical 9:16.")

    def test_starting_again_when_everything_is_done_generates_nothing(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            env.client.post(f"{_RUN}/images/generate", json={})
            assert len(FakeProvider.calls) == 3
            r = env.client.post(f"{_RUN}/images/generate", json={})
            assert r.json()["status"] == "nothing_to_do" and len(FakeProvider.calls) == 3

    def test_a_second_start_while_a_job_runs_starts_nothing(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            assert claim_job(RUN_ID)  # a job is alive in this process
            try:
                r = env.client.post(f"{_RUN}/images/generate", json={})
                assert r.status_code == 202 and r.json()["already_running"] is True
                assert FakeProvider.calls == []
                assert env.client.get(f"{_RUN}/images/plan").json()["job_active"] is True
            finally:
                release_job(RUN_ID)

    def test_the_job_stops_cleanly_at_the_cap_and_says_how_many_are_left(self, monkeypatch):
        with animation_env(monkeypatch, cap=1.2) as env:
            env.settings.IMAGE_JOB_CONCURRENCY = 1
            env.client.post(f"{_RUN}/images/generate", json={})
            job = env.client.get(f"{_RUN}/images/status").json()
            assert job["status"] == "stopped_at_cap" and job["done"] == 2 and job["left"] == 1
            assert "1 scene left" in job["message"] and job["failed"] == []
            assert _spent(env) == (2, 1.0)  # never over the cap
            # the scenes that were generated are kept
            assert sum(1 for e in env.manifest_entries() if e["status"] == "acquired") == 2

    def test_raising_the_cap_in_the_dialog_lets_the_rest_finish(self, monkeypatch):
        with animation_env(monkeypatch, cap=1.2) as env:
            env.settings.IMAGE_JOB_CONCURRENCY = 1
            env.client.post(f"{_RUN}/images/generate", json={})
            r = env.client.post(f"{_RUN}/images/generate", json={"spend_cap_usd": 3.0})
            assert r.status_code == 202 and r.json()["plan"]["cap_usd"] == 3.0
            assert env.client.get(f"{_RUN}/images/status").json()["status"] == "complete"
            assert _spent(env) == (3, 1.5)
            assert env.client.get(f"{_RUN}/ai-spend").json()["cap_usd"] == 3.0
            # the cap is the run's own: it is in settings.json beside the settings it did not touch
            saved = asyncio.run(env.storage.get_json(f"runs/{RUN_ID}/settings.json"))
            assert saved["image_spend_cap_usd"] == 3.0 and saved["visual_mode"] == "ai_animation"

    def test_a_cap_above_the_tenant_maximum_is_422_and_changes_nothing(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            r = env.client.post(f"{_RUN}/images/generate", json={"spend_cap_usd": 10.5})
            assert r.status_code == 422 and "IMAGE_RUN_SPEND_CAP_MAX_USD" in r.json()["detail"]
            assert FakeProvider.calls == []
            assert env.client.get(f"{_RUN}/ai-spend").json()["cap_usd"] == 2.0

    def test_a_failing_scene_is_retried_once_then_reported_and_the_rest_continue(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            FakeProvider.fail_on = {"prompt 2": 2}  # fails on both attempts
            env.client.post(f"{_RUN}/images/generate", json={})
            job = env.client.get(f"{_RUN}/images/status").json()
            assert job["status"] == "complete" and job["done"] == 2
            assert job["failed"] == [{"scene": "2", "reason": "provider refused prompt 2"}]
            assert job["scenes"]["2"] == "failed"
            assert _spent(env) == (2, 1.0)  # a failed generation is not charged
            # the per-scene retry: name the scene
            env.client.post(f"{_RUN}/images/generate", json={"scene_ids": ["2"]})
            assert env.client.get(f"{_RUN}/images/status").json()["scenes"] == {"2": "done"}

    def test_one_failure_then_success_is_a_success(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            FakeProvider.fail_on = {"prompt 2": 1}
            env.client.post(f"{_RUN}/images/generate", json={})
            job = env.client.get(f"{_RUN}/images/status").json()
            assert job["failed"] == [] and job["done"] == 3

    def test_no_key_is_409_before_anything_starts(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            env.settings.KIE_API_KEY = ""
            r = env.client.post(f"{_RUN}/images/generate", json={})
            assert r.status_code == 409 and "key" in r.json()["detail"]
            assert env.client.get(f"{_RUN}/images/status").json() == {"status": "none"}
            assert not scene_images.job_is_active(RUN_ID)


class TestRestart:
    def test_a_running_job_with_no_live_process_reads_as_interrupted_and_can_be_started_again(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            # what a restart leaves behind: a document that says "running", one scene done
            asyncio.run(generate_scene_image(_ctx(env), "1"))
            asyncio.run(env.storage.put_json(scene_images.images_job_key(RUN_ID), {
                "job_id": "old", "status": "running", "total": 3, "done": 1, "failed": [], "left": 2,
                "scenes": {"1": "done", "2": "running", "3": "pending"}, "message": "",
            }))
            job = env.client.get(f"{_RUN}/images/status").json()
            assert job["status"] == "interrupted" and job["left"] == 2
            assert job["scenes"] == {"1": "done", "2": "not_started", "3": "not_started"}
            r = env.client.post(f"{_RUN}/images/generate", json={})
            assert r.json()["job"]["total"] == 2  # only the scenes still missing
            assert env.client.get(f"{_RUN}/images/status").json()["status"] == "complete"
            assert _spent(env) == (3, 1.5)  # scene 1 was not paid for twice


class TestSharedFunction:
    def test_parallel_generations_cannot_overshoot_the_cap(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            FakeProvider.delay_s = 0.01
            ctx = _ctx(env, cap=1.0, cost=0.5)

            async def _all():
                """Start three generations at once under a cap that allows two."""
                return await asyncio.gather(
                    *(generate_scene_image(ctx, s) for s in ("1", "2", "3")), return_exceptions=True
                )

            results = asyncio.run(_all())
            assert sum(isinstance(r, SpendCapReachedError) for r in results) == 1
            assert _spent(env) == (2, 1.0)
            assert scene_images._RESERVED_USD[RUN_ID] == 0.0

    def test_a_provider_failure_charges_nothing_and_releases_the_reservation(self, monkeypatch):
        from cf_platform.core.image_provider import ImageGenerationError

        with animation_env(monkeypatch) as env:
            FakeProvider.fail_on = {"prompt 1": 1}
            with pytest.raises(ImageGenerationError):
                asyncio.run(generate_scene_image(_ctx(env), "1"))
            assert _spent(env) == (0, 0.0) and scene_images._RESERVED_USD[RUN_ID] == 0.0

    def test_the_spend_is_in_the_ledger_even_when_storing_the_image_fails(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            async def _boom(*args, **kwargs):
                """Fail the upload that follows a paid generation."""
                raise RuntimeError("storage down")

            monkeypatch.setattr(env.storage, "put_bytes", _boom)
            with pytest.raises(RuntimeError):
                asyncio.run(generate_scene_image(_ctx(env), "1"))
            assert _spent(env) == (1, 0.5)

    def test_a_bulk_generation_does_not_rewrite_an_unchanged_storyboard(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            before = env.versions("storyboard", "verified_storyboard")
            asyncio.run(generate_scene_image(_ctx(env), "2"))
            assert env.versions("storyboard", "verified_storyboard") == before

    def test_missing_scenes_are_ai_image_scenes_without_a_generated_file(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("2",)) as env:
            from cf_platform.interfaces.routes.studio import _load_manifest

            _, storyboard = asyncio.run(_load(env.storage))
            manifest = asyncio.run(_load_manifest(env.storage, RUN_ID))
            assert scenes_missing_images(storyboard, manifest) == ["1", "3"]
            assert scenes_missing_images(storyboard, None) == ["1", "2", "3"]

    def test_the_job_function_never_raises_and_releases_its_claim(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            assert claim_job(RUN_ID)
            job = asyncio.run(run_image_job(_ctx(env), ["1", "9"], job_id="j", concurrency=2))
            assert job["status"] == "complete" and job["scenes"]["1"] == "done" and job["scenes"]["9"] == "failed"
            assert job["finished_at"] and not scene_images.job_is_active(RUN_ID)
            assert asyncio.run(read_job(env.storage, RUN_ID))["status"] == "complete"
