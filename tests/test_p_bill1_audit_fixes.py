"""Audit 2026-10-22 fixes: HIGH-1 (View as Basic must not be a free ride) and HIGH-2 (a listing is not the whole prefix)."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from cf_platform.core import billing, limits
from cf_platform.core.accounts import Principal, owner_principal, reset_principal, set_principal
from cf_platform.core.artifact_manager import InMemoryArtifactStorage, R2ArtifactStorage
from cf_platform.core.billing import InMemoryBillingStore
from cf_platform.core.config import PlatformSettings
from cf_platform.core.erasure import delete_prefixes

BASE = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a"}


def run(coro):
    """Run a coroutine to completion."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(monkeypatch):
    """A fresh ledger and daily-usage store."""
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    monkeypatch.setattr(limits, "_memory_usage", limits.InMemoryUsageStore())
    billing._in_flight.clear()
    return fresh


def cfg(**over) -> PlatformSettings:
    """Billing on, with overrides."""
    return PlatformSettings.model_validate({**BASE, "BILLING_ENABLED": True, **over})


class TestViewAsBasic:
    def test_a_non_owner_super_in_view_as_basic_is_charged_and_bound(self, store):
        tenant = f"u_{uuid.uuid4().hex[:10]}"
        token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="super", view_as_basic=True))
        try:
            run(store.credit(tenant, 100, kind="topup"))
            c = cfg(CAP_DAILY_SPEND_USD=0.10)
            hold = run(billing.reserve("tts", 0.05, "x", settings=c))
            assert hold is not None and run(store.balance(tenant)) == 90
            run(billing.reserve("tts", 0.05, "y", settings=c))
            with pytest.raises(HTTPException) as refused:
                run(billing.reserve("tts", 0.05, "z", settings=c))  # the daily bound applies too
            assert refused.value.status_code == 429
        finally:
            reset_principal(token)

    def test_a_non_owner_super_in_view_as_basic_cannot_overdraw(self, store):
        tenant = f"u_{uuid.uuid4().hex[:10]}"
        token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="super", view_as_basic=True))
        try:
            with pytest.raises(billing.PaymentRequiredError):
                run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        finally:
            reset_principal(token)

    def test_the_owners_own_preview_is_still_free_and_unrecorded(self, store, monkeypatch):
        owner_preview = Principal(
            user_id=owner_principal().user_id, tenant_id=owner_principal().tenant_id, account_type="super",
            view_as_basic=True, email=owner_principal().email,
        )
        token = set_principal(owner_preview)
        try:
            assert owner_preview.is_owner and billing._charging_principal() is None
            assert run(billing.reserve("tts", 0.05, "x", settings=cfg())) is None
        finally:
            reset_principal(token)


class TestListingIsNotThePrefix:
    def test_the_r2_listing_follows_the_continuation_token(self):
        pages = [
            {"Contents": [{"Key": "p/1"}, {"Key": "p/2"}], "IsTruncated": True, "NextContinuationToken": "t1"},
            {"Contents": [{"Key": "p/3"}], "IsTruncated": True, "NextContinuationToken": "t2"},
            {"Contents": [{"Key": "p/4"}], "IsTruncated": False},
        ]
        calls: list[dict] = []

        class Client:
            def list_objects_v2(self, **kwargs):
                calls.append(kwargs)
                return pages[len(calls) - 1]

        storage = object.__new__(R2ArtifactStorage)
        storage._client, storage._bucket = Client(), "b"
        assert run(storage.list_keys("p/")) == ["p/1", "p/2", "p/3", "p/4"]
        assert [c.get("ContinuationToken") for c in calls] == [None, "t1", "t2"]

    def test_an_empty_listing_is_empty(self):
        class Client:
            def list_objects_v2(self, **kwargs):
                return {"IsTruncated": False}

        storage = object.__new__(R2ArtifactStorage)
        storage._client, storage._bucket = Client(), "b"
        assert run(storage.list_keys("p/")) == []

    def test_delete_prefixes_keeps_going_when_a_listing_is_cut_short(self):
        class Capped(InMemoryArtifactStorage):
            """Lists at most 3 keys a call, like a truncated R2 page."""

            async def list_keys(self, prefix):
                return (await super().list_keys(prefix))[:3]

        storage = Capped()
        for i in range(10):
            run(storage.put_bytes(f"users/u_a/f{i}", b"x"))
        run(storage.put_bytes("users/u_b/keep", b"x"))
        assert run(delete_prefixes(storage, ["users/u_a/"])) == 10
        assert run(InMemoryArtifactStorage.list_keys(storage, "")) == ["users/u_b/keep"]

    def test_delete_prefixes_fails_loudly_rather_than_report_a_partial_erasure(self):
        class Stuck(InMemoryArtifactStorage):
            async def delete_key(self, key):
                return None  # the object never goes away

        storage = Stuck()
        run(storage.put_bytes("users/u_a/f", b"x"))
        with pytest.raises(RuntimeError):
            run(delete_prefixes(storage, ["users/u_a/"], max_rounds=3))
