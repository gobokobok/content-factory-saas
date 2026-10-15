"""Sprint P-BILL-1 S2 — every paid background job settles its hold on success and refunds it on failure (D123).

Each background job that calls a paid provider is run here with a fake provider. The
arithmetic is in test_p_bill1_billing.py; the routes that take the hold (and answer 402)
are tested with real sessions in test_p_auth_billing_routes.py.
"""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from cf_platform.core import billing
from cf_platform.core.accounts import Principal, reset_principal, set_principal
from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.config import PlatformSettings
from cf_platform.core.schemas import StageState, WorkerOutput
from tests.cf_platform.p13_helpers import RUN_ID

BASE = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a"}
CFG = PlatformSettings.model_validate({**BASE, "BILLING_ENABLED": True})


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    """Charging on for the process settings, and a fresh ledger."""
    monkeypatch.setenv("BILLING_ENABLED", "true")
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    return fresh


@pytest.fixture
def store(billing_on) -> InMemoryBillingStore:
    return billing_on


@pytest.fixture
def friend(store):
    """A funded (100 credits) bound tenant for direct calls."""
    tenant = f"u_{uuid.uuid4().hex[:10]}"
    run(store.credit(tenant, 100, kind="topup"))
    token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
    yield tenant
    reset_principal(token)


def hold_for(kind, usd, **kw):
    """Take a hold as the current principal."""
    return run(billing.reserve(kind, usd, "test", settings=CFG, **kw))


def entry_of(store, hold):
    """The ledger entry behind a hold."""
    return run(store.get_entry(hold.entry_id))


class _Artifact(BaseModel):
    scene_count: int = 1
    prompt_version: str = "v"


# ── The background jobs ──────────────────────────────────────────────────


class TestVoiceJob:
    def _go(self, hold, worker):
        from cf_platform.interfaces.routes.workers import _run_voice_background

        storage = InMemoryArtifactStorage()
        state = StageState(run_id="r1", user_id="u", inputs={})
        run(_run_voice_background("r1", "j1", state, worker, storage, hold))
        return run(storage.get_json("runs/r1/voice/current_job.json"))

    def test_a_voice_that_completes_is_charged(self, store, friend):
        from cf_platform.workers.voice_production import VoiceAlignmentArtifact

        async def worker(_state):
            return WorkerOutput(artifact=VoiceAlignmentArtifact(
                mp3_r2_key="k.wav", word_timestamps=[], alignment_method="proportional", total_duration_s=3.0))

        hold = hold_for("tts", 0.05)
        assert run(store.balance(friend)) == 90
        job = self._go(hold, worker)
        assert job["status"] == "complete"
        assert entry_of(store, hold).status == "settled" and run(store.balance(friend)) == 90

    def test_a_voice_that_fails_is_refunded_and_the_job_says_why(self, store, friend):
        async def worker(_state):
            raise RuntimeError("Gemini closed the connection")

        hold = hold_for("tts", 0.05)
        job = self._go(hold, worker)
        assert job["status"] == "error" and "Gemini closed the connection" in job["error"]
        entry = entry_of(store, hold)
        assert entry.status == "refunded" and "Gemini closed the connection" in entry.note
        assert run(store.balance(friend)) == 100


class TestStoryboardJob:
    def _go(self, hold, worker):
        from cf_platform.interfaces.routes.workers import _run_storyboard_background

        storage = InMemoryArtifactStorage()
        state = StageState(run_id="r1", user_id="u", inputs={})
        with patch("cf_platform.interfaces.routes.workers.VerifiedStoryboardArtifact", _Artifact):
            run(_run_storyboard_background("r1", "j1", state, worker, storage, hold=hold))
        return run(storage.get_json("runs/r1/storyboard/current_job.json"))

    def test_a_storyboard_that_completes_is_charged(self, store, friend):
        async def worker(_state):
            return WorkerOutput(artifact=_Artifact())

        hold = hold_for("llm", 0.05)
        assert self._go(hold, worker)["status"] == "complete"
        assert entry_of(store, hold).status == "settled" and run(store.balance(friend)) == 90

    def test_a_storyboard_that_fails_is_refunded(self, store, friend):
        async def worker(_state):
            raise RuntimeError("model overloaded")

        hold = hold_for("llm", 0.05)
        assert self._go(hold, worker)["status"] == "error"
        assert entry_of(store, hold).status == "refunded" and run(store.balance(friend)) == 100

    def test_a_worker_that_returns_the_wrong_artifact_is_a_failure_and_refunded(self, store, friend):
        async def worker(_state):
            return WorkerOutput(artifact=BaseModel())

        hold = hold_for("llm", 0.05)
        assert self._go(hold, worker)["status"] == "error"
        assert run(store.balance(friend)) == 100


class TestRenderJob:
    def _go(self, hold, worker):
        from cf_platform.interfaces.routes.workers import _run_render_background

        storage = InMemoryArtifactStorage()
        state = StageState(run_id=RUN_ID, user_id="u", inputs={})
        run(_run_render_background(RUN_ID, "j1", state, worker, storage, None, None, hold))
        return run(storage.get_json(f"runs/{RUN_ID}/render/current_job.json"))

    def test_a_render_that_completes_is_charged_and_records_its_minutes(self, store, friend):
        from cf_platform.workers.render_worker import RenderArtifact

        async def worker(_state):
            return WorkerOutput(artifact=RenderArtifact(
                render_script_key="s", video_key="v.mp4", scene_count=3, duration_s=90.0,
                generated_at=datetime.now()))

        hold = hold_for("render", 0.02)
        assert self._go(hold, worker)["status"] == "complete"
        entry = entry_of(store, hold)
        assert entry.status == "settled" and entry.units == 1.5

    def test_a_render_that_fails_is_refunded(self, store, friend):
        async def worker(_state):
            raise RuntimeError("ffmpeg exited 1")

        hold = hold_for("render", 0.02)
        assert self._go(hold, worker)["status"] == "error"
        assert entry_of(store, hold).status == "refunded" and run(store.balance(friend)) == 100


class TestTranscriptionJob:
    def _go(self, hold, worker):
        from cf_platform.core.trace_repo import InMemoryTraceEventRepository
        from cf_platform.interfaces.routes import studio_voice

        storage = InMemoryArtifactStorage()
        state = StageState(run_id="r1", user_id="u", inputs={"language": "en"})

        async def fake_write(*_a, **_k):
            return None

        with patch.object(studio_voice, "_write_transcript_artifacts", fake_write):
            run(studio_voice._run_transcription_background(
                "r1", "j1", state, worker, storage, InMemoryTraceEventRepository(), 0.0043, 0.5, hold))
        return run(storage.get_json("runs/r1/voice/current_job.json"))

    def test_a_transcription_is_settled_at_the_minutes_actually_transcribed(self, store, friend):
        from cf_platform.workers.voice_production import VoiceAlignmentArtifact

        async def worker(_state):
            return WorkerOutput(artifact=VoiceAlignmentArtifact(
                mp3_r2_key="k.mp3", word_timestamps=[], alignment_method="uploaded", total_duration_s=120.0))

        hold = hold_for("transcription", 0.05)
        assert self._go(hold, worker)["status"] == "complete"
        entry = entry_of(store, hold)
        assert entry.status == "settled" and entry.actual_usd == pytest.approx(0.0086)
        assert entry.credits == 2 and entry.units == 120.0
        assert run(store.balance(friend)) == 98  # 10 held, 8 returned

    def test_a_failed_transcription_is_refunded(self, store, friend):
        async def worker(_state):
            raise RuntimeError("Deepgram 500")

        hold = hold_for("transcription", 0.05)
        assert self._go(hold, worker)["status"] == "error"
        assert entry_of(store, hold).status == "refunded" and run(store.balance(friend)) == 100


class TestBulkImageJob:
    def _go(self, hold, job_or_error, unit_usd=0.04):
        from cf_platform.interfaces.routes import studio_ai

        async def fake_job(_ctx, _ids, *, job_id, concurrency):
            if isinstance(job_or_error, Exception):
                raise job_or_error
            return job_or_error

        ctx = SimpleNamespace(cost_usd=unit_usd)
        with patch.object(studio_ai, "run_image_job", fake_job):
            return run(studio_ai._run_billed_image_job(
                hold, ctx, ["1", "2", "3"], job_id="j", concurrency=3))

    def test_only_the_images_that_were_made_are_charged(self, store, friend):
        hold = hold_for("image", 0.12, units=3)  # 3 images at 0.04: 24 credits
        assert run(store.balance(friend)) == 76
        self._go(hold, {"scenes": {"1": "done", "2": "failed", "3": "not_started"}})
        entry = entry_of(store, hold)
        assert (entry.status, entry.credits, entry.units) == ("settled", 8, 1.0)
        assert run(store.balance(friend)) == 92

    def test_a_job_that_made_nothing_costs_nothing(self, store, friend):
        hold = hold_for("image", 0.12, units=3)
        self._go(hold, {"scenes": {"1": "failed", "2": "failed", "3": "not_started"}})
        assert entry_of(store, hold).status == "refunded" and run(store.balance(friend)) == 100

    def test_a_crashed_job_is_refunded_in_full_and_the_error_still_surfaces(self, store, friend):
        hold = hold_for("image", 0.12, units=3)
        with pytest.raises(RuntimeError):
            self._go(hold, RuntimeError("storage down"))
        assert entry_of(store, hold).status == "refunded" and run(store.balance(friend)) == 100


class TestImagesPlan:
    def test_the_plan_shows_the_price_in_credits_before_the_user_confirms(self):
        from cf_platform.core.billing import price_credits

        settings = SimpleNamespace(CREDIT_VALUE_USD=0.01, CREDIT_MARKUP=2.0)
        assert price_credits(0.04 * 3, settings) == 24 and price_credits(0.04, settings) == 8
