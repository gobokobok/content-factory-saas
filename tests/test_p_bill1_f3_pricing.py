"""BILL-F3 — a zero price is refused, non-owner image models must be priced, and the calibration report adds up."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cf_platform.core import billing, limits
from cf_platform.core.accounts import OWNER_TENANT_ID, Principal, owner_principal, reset_principal, set_principal
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.config import PlatformSettings
from cf_platform.core.cost_report import format_report, summarise
from cf_platform.core.tenant_settings import (
    InMemoryTenantSettingsRepository,
    resolve_image_config,
    save_image_settings,
)

BASE = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a"}


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


def cfg(**over) -> PlatformSettings:
    """Settings with billing on and the given overrides."""
    return PlatformSettings.model_validate({**BASE, "BILLING_ENABLED": True, **over})


@pytest.fixture
def store(monkeypatch):
    """A fresh ledger and daily-usage store."""
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    monkeypatch.setattr(limits, "_memory_usage", limits.InMemoryUsageStore())
    billing._in_flight.clear()
    return fresh


@pytest.fixture
def friend(store):
    """A funded non-owner tenant."""
    tenant = f"u_{uuid.uuid4().hex[:10]}"
    token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
    run(store.credit(tenant, 100, kind="topup"))
    yield tenant
    reset_principal(token)


class TestZeroPrice:
    @pytest.mark.parametrize("billing_on", [True, False])
    def test_a_zero_price_is_refused_before_anything_is_held(self, store, friend, billing_on):
        with pytest.raises(HTTPException) as refused:
            run(billing.reserve("render", 0.0, "the render", settings=cfg(BILLING_ENABLED=billing_on)))
        assert refused.value.status_code == 503 and "no price" in refused.value.detail
        assert run(store.balance(friend)) == 100 and run(store.list_entries(friend)) == []

    def test_an_unreadable_price_is_a_zero_price(self, store, friend):
        with pytest.raises(HTTPException):
            run(billing.reserve("tts", "free", "the voiceover", settings=cfg()))  # type: ignore[arg-type]

    def test_a_real_price_still_works(self, store, friend):
        assert run(billing.reserve("tts", 0.05, "x", settings=cfg())) is not None

    def test_the_owner_is_not_affected(self, store):
        token = set_principal(owner_principal())
        try:
            assert run(billing.reserve("render", 0.0, "x", settings=cfg())) is not None
        finally:
            reset_principal(token)

    def test_the_shipped_defaults_are_all_priced(self):
        s = PlatformSettings.model_validate(BASE)
        assert min(s.EST_LLM_CALL_USD, s.EST_TTS_CALL_USD, s.EST_RENDER_USD, s.EST_TRANSCRIPTION_USD, s.EST_IDEAS_USD) > 0
        assert s.IMAGE_COST_USD > 0 and all(v > 0 for v in s.IMAGE_MODEL_COSTS_USD.values())


class TestImageModelAllowList:
    S = cfg()

    def test_a_non_owner_cannot_save_a_model_without_a_price(self):
        repo = InMemoryTenantSettingsRepository()
        with pytest.raises(ValueError, match="no price"):
            run(save_image_settings(repo, "u_a", self.S, provider="kie", model="gpt-image-2-text-to-image"))

    def test_a_priced_model_or_the_default_is_accepted(self):
        repo = InMemoryTenantSettingsRepository()
        run(save_image_settings(repo, "u_a", self.S, provider="kie", model="nano-banana-2-1"))
        assert run(repo.get("u_a")).image_model == "nano-banana-2-1"
        run(save_image_settings(repo, "u_a", self.S, model=""))
        assert run(repo.get("u_a")).image_model is None

    def test_the_owner_may_use_any_model(self):
        repo = InMemoryTenantSettingsRepository()
        run(save_image_settings(repo, OWNER_TENANT_ID, self.S, provider="kie", model="gpt-image-2-text-to-image"))
        assert run(repo.get(OWNER_TENANT_ID)).image_model == "gpt-image-2-text-to-image"

    def test_a_model_saved_before_the_check_falls_back_to_the_default(self):
        from cf_platform.core.tenant_settings import TenantSettings

        repo = InMemoryTenantSettingsRepository()
        run(repo.save(TenantSettings(tenant_id="u_a", image_provider="kie", image_model="nano-banana-2")))
        config = run(resolve_image_config(repo, "u_a", cfg(KIE_API_KEY="k", KIE_IMAGE_MODEL="nano-banana-2-1")))
        assert config.model == "nano-banana-2-1"
        owner_repo = InMemoryTenantSettingsRepository()
        run(owner_repo.save(TenantSettings(tenant_id=OWNER_TENANT_ID, image_provider="kie", image_model="nano-banana-2")))
        assert run(resolve_image_config(owner_repo, OWNER_TENANT_ID, cfg(KIE_API_KEY="k"))).model == "nano-banana-2"

    def test_settings_without_a_price_table_skip_the_check(self):
        repo = InMemoryTenantSettingsRepository()
        run(save_image_settings(repo, "u_a", SimpleNamespace(IMAGE_PROVIDER="kie"), provider="kie", model="anything"))
        assert run(repo.get("u_a")).image_model == "anything"


class TestCostReport:
    S = cfg(EST_LLM_CALL_USD=0.05)

    def entries(self):
        mk = lambda kind, status, raw=0.05, actual=None: {  # noqa: E731
            "kind": kind, "status": status, "raw_cost_usd": raw, "actual_usd": actual, "run_id": "r"}
        return [mk("llm", "settled")] * 4 + [mk("llm", "refunded")] + [mk("image", "settled", 0.04, 0.04)] * 2 + [
            mk("tts", "settled")]

    def test_counts_reserved_and_actual(self):
        rows = {r.kind: r for r in summarise(self.entries(), {}, self.S)}
        assert (rows["llm"].actions, rows["llm"].refunded) == (4, 1)
        assert rows["llm"].reserved_usd == pytest.approx(0.20)
        assert rows["image"].actual_usd == pytest.approx(0.08) and rows["image"].with_actual == 2
        assert rows["render"].actions == 0

    def test_a_bill_gives_the_implied_cost_and_a_suggestion_with_headroom(self):
        rows = {r.kind: r for r in summarise(self.entries(), {"llm": 0.40}, self.S)}
        assert rows["llm"].implied_per_action == pytest.approx(0.10)
        assert rows["llm"].suggested_per_action == pytest.approx(0.125)
        assert any("MORE per action" in n for n in rows["llm"].notes)

    def test_a_bill_for_a_kind_with_no_actions_is_noted_not_divided(self):
        rows = {r.kind: r for r in summarise([], {"render": 3.0}, self.S)}
        assert rows["render"].implied_per_action is None and rows["render"].notes

    def test_a_zero_estimate_is_flagged(self):
        rows = {r.kind: r for r in summarise([], {}, cfg(EST_RENDER_USD=0))}
        assert any("price is 0" in n for n in rows["render"].notes)

    def test_the_text_report_says_what_is_not_measured(self):
        text = format_report(summarise(self.entries(), {"llm": 0.4}, self.S), self.S, 30, 1)
        assert "Not measured" in text and "llm" in text and "markup" in text

    def test_bill_arguments_are_checked(self):
        from scripts.cost_report import parse_bills

        assert parse_bills(["llm=1.5", "tts=0"]) == {"llm": 1.5, "tts": 0.0}
        for bad in ("nope=1", "llm=abc", "llm=-1"):
            with pytest.raises(SystemExit):
                parse_bills([bad])
