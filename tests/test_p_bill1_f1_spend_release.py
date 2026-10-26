"""BILL-F1 — a refunded or settled-down hold gives back the day's USD reservation (D120, D123).

`billing.reserve()` reserves the raw cost against `CAP_DAILY_SPEND_USD` next to the credit hold;
closing the hold must return that reservation, or a tenant whose actions fail reaches the cap
having spent nothing.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from cf_platform.core import billing, limits
from cf_platform.core.accounts import Principal, reset_principal, set_principal
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.config import PlatformSettings

BASE = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a"}


def cfg(**over) -> PlatformSettings:
    """A PlatformSettings with billing on and the given overrides."""
    return PlatformSettings.model_validate({**BASE, "BILLING_ENABLED": True, **over})


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(monkeypatch) -> InMemoryBillingStore:
    """A fresh ledger and a fresh daily-usage store."""
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    monkeypatch.setattr(limits, "_memory_usage", limits.InMemoryUsageStore())
    billing._in_flight.clear()
    yield fresh
    billing._in_flight.clear()


@pytest.fixture
def friend(store):
    """A bound tenant with 1000 credits."""
    tenant = f"u_{uuid.uuid4().hex[:10]}"
    token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
    run(store.credit(tenant, 1000, kind="topup"))
    yield tenant
    reset_principal(token)


def spent(tenant: str) -> float:
    """The dollars reserved for tenant today."""
    return run(limits.get_usage_store().spend_today(tenant, datetime.now(UTC).date()))


def test_a_refund_restores_the_days_room(store, friend):
    c = cfg(CAP_DAILY_SPEND_USD=0.10)
    hold = run(billing.reserve("tts", 0.10, "x", settings=c))
    assert spent(friend) == pytest.approx(0.10)
    with pytest.raises(HTTPException) as refused:
        run(billing.reserve("tts", 0.05, "y", settings=c))
    assert refused.value.status_code == 429
    run(billing.refund(hold, "failed", store=store))
    assert spent(friend) == pytest.approx(0.0)
    run(billing.reserve("tts", 0.10, "z", settings=c))  # the whole day is free again


def test_a_settle_at_half_returns_half(store, friend):
    hold = run(billing.reserve("image", 0.10, "x", settings=cfg(CAP_DAILY_SPEND_USD=1)))
    run(billing.settle(hold, 0.05, settings=cfg(CAP_DAILY_SPEND_USD=1), store=store))
    assert spent(friend) == pytest.approx(0.05)


def test_a_settle_above_the_estimate_releases_nothing(store, friend):
    hold = run(billing.reserve("llm", 0.05, "x", settings=cfg(CAP_DAILY_SPEND_USD=1)))
    run(billing.settle(hold, 0.20, settings=cfg(CAP_DAILY_SPEND_USD=1), store=store))
    assert spent(friend) == pytest.approx(0.05)


def test_a_settle_at_zero_returns_all_of_it(store, friend):
    hold = run(billing.reserve("image", 0.10, "x", settings=cfg(CAP_DAILY_SPEND_USD=1)))
    run(billing.settle(hold, 0.0, settings=cfg(CAP_DAILY_SPEND_USD=1), store=store))
    assert spent(friend) == pytest.approx(0.0)


def test_a_double_refund_releases_once(store, friend):
    c = cfg(CAP_DAILY_SPEND_USD=1)
    other = run(billing.reserve("tts", 0.30, "other", settings=c))
    hold = run(billing.reserve("tts", 0.10, "x", settings=c))
    run(billing.refund(hold, "a", store=store))
    run(billing.refund(hold, "b", store=store))
    run(billing.settle(hold, 0.0, settings=c, store=store))
    assert spent(friend) == pytest.approx(0.30)  # the other action's reservation is untouched
    assert other is not None


def test_a_refund_after_a_settle_releases_nothing_more(store, friend):
    c = cfg(CAP_DAILY_SPEND_USD=1)
    hold = run(billing.reserve("tts", 0.10, "x", settings=c))
    run(billing.settle(hold, 0.10, settings=c, store=store))
    run(billing.refund(hold, "late", store=store))
    assert spent(friend) == pytest.approx(0.10)


def test_a_refused_daily_bound_does_not_release_what_it_never_took(store, friend):
    c = cfg(CAP_DAILY_SPEND_USD=0.10)
    keep = run(billing.reserve("tts", 0.10, "x", settings=c))
    with pytest.raises(HTTPException):
        run(billing.reserve("tts", 0.10, "y", settings=c))  # refund() runs inside reserve
    assert spent(friend) == pytest.approx(0.10)
    assert keep is not None


def test_billing_off_metered_entries_release_too(store, friend):
    c = cfg(BILLING_ENABLED=False, CAP_DAILY_SPEND_USD=1)
    hold = run(billing.reserve("tts", 0.10, "x", settings=c))
    assert spent(friend) == pytest.approx(0.10)
    run(billing.refund(hold, "failed", store=store))
    run(billing.refund(hold, "again", store=store))
    assert spent(friend) == pytest.approx(0.0)


def test_a_stale_hold_refunded_by_the_owner_releases_it(store, friend):
    c = cfg(CAP_DAILY_SPEND_USD=1)
    run(billing.reserve("tts", 0.10, "x", settings=c))
    billing._in_flight.clear()  # as after a restart
    assert run(billing.refund_stale_holds(older_than_minutes=0, settings=c, store=store)) == 1
    assert spent(friend) == pytest.approx(0.0)


def test_the_owner_has_no_reservation_to_release(store):
    from cf_platform.core.accounts import owner_principal

    token = set_principal(owner_principal())
    try:
        hold = run(billing.reserve("tts", 0.10, "x", settings=cfg()))
        run(billing.refund(hold, "failed", store=store))
        assert run(limits.get_usage_store().spend_today(limits.OWNER_TENANT_ID, datetime.now(UTC).date())) == 0.0
    finally:
        reset_principal(token)


def test_release_never_goes_below_zero(store):
    run(limits.release_spend("u_x", 5.0))
    assert run(limits.get_usage_store().spend_today("u_x", datetime.now(UTC).date())) == 0.0
