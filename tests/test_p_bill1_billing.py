"""Sprint P-BILL-1 S1–S3 — the usage ledger, credits, holds and hard limits (D123).

The core (`cf_platform/core/billing.py`) against the in-memory store, with the request
principal set the way the auth middleware sets it. The Postgres SQL is run for real in
tests/integration/test_billing_postgres.py. The background-job wiring is tested in
tests/test_p_bill1_wiring.py and the routes in tests/test_p_auth_billing_routes.py.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cf_platform.core import billing
from cf_platform.core.accounts import Principal, owner_principal, reset_principal, set_principal
from cf_platform.core.billing import (
    InMemoryBillingStore,
    PaymentRequiredError,
    UsageEntry,
    price_credits,
)
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
    """A fresh ledger used by everything that asks for the billing store."""
    fresh = InMemoryBillingStore()
    monkeypatch.setattr(billing, "_memory_store", fresh)
    return fresh


@pytest.fixture(autouse=True)
def no_leftover_in_flight():
    """Holds left open by one test must not make the next one look like a running job."""
    billing._in_flight.clear()
    yield
    billing._in_flight.clear()


@pytest.fixture
def friend():
    """A bound (non-owner) tenant for the duration of a test."""
    tenant = f"u_{uuid.uuid4().hex[:10]}"
    token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
    yield tenant
    reset_principal(token)


@pytest.fixture
def owner():
    token = set_principal(owner_principal())
    yield "operator"
    reset_principal(token)


# ── Price ────────────────────────────────────────────────────────────────


class TestPrice:
    def test_default_unit_is_one_cent_of_price_at_double_the_raw_cost(self):
        # $0.05 raw -> $0.10 price -> 10 credits (not 11: 0.05 * 2 / 0.01 is 10.000000000000002 in floats)
        assert price_credits(0.05, cfg()) == 10

    def test_rounds_up_to_whole_credits(self):
        assert price_credits(0.0051, cfg()) == 2  # $0.0102 of price is 1.02 credits

    def test_any_non_zero_cost_is_at_least_one_credit(self):
        assert price_credits(0.0000001, cfg()) == 1

    def test_a_free_action_is_free(self):
        assert price_credits(0, cfg()) == 0
        assert price_credits(-1, cfg()) == 0

    def test_markup_and_unit_come_from_settings(self):
        assert price_credits(0.05, cfg(CREDIT_MARKUP=3.0, CREDIT_VALUE_USD=0.05)) == 3

    def test_a_non_positive_unit_falls_back_to_the_default_instead_of_dividing_by_zero(self):
        assert price_credits(0.05, cfg(CREDIT_VALUE_USD=0)) == 10

    def test_one_credit_is_one_cent_of_provider_cost_by_default(self):
        from cf_platform.core.config import PlatformSettings

        assert PlatformSettings.model_fields["CREDIT_MARKUP"].default == 1.0
        assert price_credits(0.03, SimpleNamespace()) == 3    # an image at 3 cents is 3 credits
        assert price_credits(0.05, SimpleNamespace()) == 5    # a voiceover or a storyboard estimate at 5 cents
        assert price_credits(2.00, SimpleNamespace()) == 200  # a $2 per-video image cap is 200 credits

    def test_settings_without_the_billing_fields_use_the_declared_defaults(self):
        assert price_credits(0.05, SimpleNamespace()) == 5   # one credit = one cent of provider cost
        assert billing.billing_enabled(SimpleNamespace()) is False


# ── Hold -> settle / refund (S2) ─────────────────────────────────────────


class TestHoldSettleRefund:
    def test_a_hold_takes_the_price_and_records_a_held_entry(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("llm", 0.05, "writing the storyboard", run_id="r1", settings=cfg()))
        assert run(store.balance(friend)) == 90
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.status, entry.credits, entry.kind, entry.run_id) == ("held", 10, "llm", "r1")
        assert entry.raw_cost_usd == 0.05 and entry.tenant_id == friend

    def test_settle_closes_the_entry_without_charging_again(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        run(billing.settle(hold, settings=cfg()))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.status, entry.credits, entry.actual_usd) == ("settled", 10, 0.05)
        assert entry.closed_at is not None
        assert run(store.balance(friend)) == 90

    def test_settling_below_the_estimate_returns_the_difference(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "image generation", units=5, settings=cfg()))  # 20 credits
        assert run(store.balance(friend)) == 80
        run(billing.settle(hold, 0.06, units=3, settings=cfg()))  # 3 of 5 images made: 12 credits
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.status, entry.credits, entry.units) == ("settled", 12, 3)
        assert run(store.balance(friend)) == 88

    def test_the_platform_absorbs_an_overrun(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        run(billing.settle(hold, 0.50, settings=cfg()))
        assert run(store.get_entry(hold.entry_id)).credits == 10
        assert run(store.balance(friend)) == 90

    def test_settling_at_zero_returns_everything_and_marks_the_entry_refunded(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "image generation", settings=cfg()))
        run(billing.settle(hold, 0.0, units=0, settings=cfg()))
        assert run(store.get_entry(hold.entry_id)).status == "refunded"
        assert run(store.balance(friend)) == 100

    def test_settling_twice_is_a_no_op(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("llm", 0.10, "x", settings=cfg()))
        run(billing.settle(hold, 0.05, settings=cfg()))
        run(billing.settle(hold, 0.0, settings=cfg()))
        assert run(store.balance(friend)) == 90

    def test_a_failed_action_is_refunded_in_full(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        run(billing.refund(hold, "the provider timed out"))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.status, entry.note) == ("refunded", "the provider timed out")
        assert run(store.balance(friend)) == 100

    def test_a_refund_after_a_settle_or_a_second_refund_changes_nothing(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        done = run(billing.reserve("llm", 0.05, "x", settings=cfg()))
        run(billing.settle(done, settings=cfg()))
        run(billing.refund(done, "late"))
        failed = run(billing.reserve("llm", 0.05, "y", settings=cfg()))
        run(billing.refund(failed, "once"))
        run(billing.refund(failed, "twice"))
        assert run(store.balance(friend)) == 90

    def test_every_balance_change_is_a_transaction_that_adds_up(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))  # -20
        run(billing.settle(hold, 0.05, settings=cfg()))  # +10
        txs = run(store.list_transactions(friend))
        assert sorted(t.kind for t in txs) == ["hold", "settle", "topup"]
        assert sum(t.credits for t in txs) == run(store.balance(friend)) == 90

    def test_a_free_action_is_refused_not_recorded_as_free(self, store, friend):
        """BILL-F3: a zero price would skip the daily bound too, so a non-owner's action must have a price."""
        with pytest.raises(HTTPException) as refused:
            run(billing.reserve("render", 0.0, "rendering the video", settings=cfg()))
        assert refused.value.status_code == 503
        assert run(store.list_entries(friend)) == []

    def test_a_ledger_fault_while_settling_or_refunding_does_not_raise(self, store, friend, caplog):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("llm", 0.05, "x", settings=cfg()))

        class Broken(InMemoryBillingStore):
            async def get_entry(self, entry_id):
                raise RuntimeError("database gone")

        run(billing.settle(hold, store=Broken()))
        run(billing.refund(hold, "x", store=Broken()))
        assert "could not settle" in caplog.text and "could not refund" in caplog.text


# ── Hard limits (S3) ─────────────────────────────────────────────────────


class TestHardLimits:
    def test_an_action_over_the_balance_is_refused_with_its_cost_and_what_is_left(self, store, friend):
        run(store.credit(friend, 3, kind="topup"))
        with pytest.raises(PaymentRequiredError) as caught:
            run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        exc = caught.value
        assert exc.status_code == 402
        assert (exc.cost_credits, exc.balance_credits) == (10, 3)
        assert exc.detail == "The voiceover costs 10 credits; you have 3."

    def test_a_refusal_starts_nothing_and_charges_nothing(self, store, friend):
        run(store.credit(friend, 3, kind="topup"))
        with pytest.raises(PaymentRequiredError):
            run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        assert run(store.balance(friend)) == 3
        assert run(store.list_entries(friend)) == []
        assert [t.kind for t in run(store.list_transactions(friend))] == ["topup"]

    def test_an_account_with_nothing_is_refused_too(self, store, friend):
        with pytest.raises(PaymentRequiredError) as caught:
            run(billing.reserve("llm", 0.05, "writing the storyboard", settings=cfg()))
        assert caught.value.balance_credits == 0

    def test_holds_started_at_once_cannot_overdraw(self, store, friend):
        run(store.credit(friend, 25, kind="topup"))

        async def attempt():
            return await asyncio.gather(
                *[billing.reserve("llm", 0.05, "x", settings=cfg()) for _ in range(5)], return_exceptions=True
            )

        results = run(attempt())
        won = [r for r in results if isinstance(r, billing.Hold)]
        refused = [r for r in results if isinstance(r, PaymentRequiredError)]
        assert len(won) == 2 and len(refused) == 3
        assert run(store.balance(friend)) == 5

    def test_the_daily_bound_still_applies_and_gives_the_hold_back(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        with pytest.raises(HTTPException) as caught:
            run(billing.reserve("llm", 0.05, "writing the storyboard", settings=cfg(CAP_DAILY_SPEND_USD=0.01)))
        assert caught.value.status_code == 429
        assert run(store.balance(friend)) == 100
        # the hold was written with its entry, so giving it back closes that entry as refunded
        assert [e.status for e in run(store.list_entries(friend))] == ["refunded"]
        assert sorted(t.kind for t in run(store.list_transactions(friend))) == ["hold", "refund", "topup"]

    def test_a_refused_hold_leaves_the_daily_reservation_alone(self, store, friend):
        from cf_platform.core import limits

        run(store.credit(friend, 3, kind="topup"))
        with pytest.raises(PaymentRequiredError):
            run(billing.reserve("tts", 0.05, "x", settings=cfg(CAP_DAILY_SPEND_USD=0.05)))
        # the whole day's bound is still free: the refusal did not reserve any of it
        run(limits.spend_gate(0.05, "x", cfg(CAP_DAILY_SPEND_USD=0.05)))


# ── Who is charged (D123 point 4) ────────────────────────────────────────


class TestWhoIsCharged:
    def test_billing_off_meters_without_touching_the_balance(self, store, friend):
        hold = run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg(BILLING_ENABLED=False)))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.status, entry.credits) == ("metered", 10)  # what it WOULD cost
        assert run(store.balance(friend)) == 0
        assert run(store.list_transactions(friend)) == []

    def test_metered_actions_are_never_refused_but_the_daily_bound_applies(self, store, friend):
        run(billing.reserve("tts", 0.05, "x", settings=cfg(BILLING_ENABLED=False)))
        with pytest.raises(HTTPException) as caught:
            run(billing.reserve("tts", 5.0, "x", settings=cfg(BILLING_ENABLED=False, CAP_DAILY_SPEND_USD=1.0)))
        assert caught.value.status_code == 429

    def test_settling_a_metered_action_records_the_actual_price(self, store, friend):
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg(BILLING_ENABLED=False)))
        run(billing.settle(hold, 0.04, settings=cfg(BILLING_ENABLED=False)))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.actual_usd, entry.credits, entry.status) == (0.04, 8, "metered")

    def test_the_owner_is_recorded_as_exempt_and_never_refused(self, store, owner):
        hold = run(billing.reserve("llm", 0.05, "writing the storyboard", settings=cfg()))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.tenant_id, entry.status, entry.credits) == ("operator", "exempt", 0)
        assert entry.raw_cost_usd == 0.05
        assert run(store.balance("operator")) == 0

    def test_settling_an_owner_action_records_its_actual_cost(self, store, owner):
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))
        run(billing.settle(hold, 0.04, settings=cfg()))
        entry = run(store.get_entry(hold.entry_id))
        assert (entry.actual_usd, entry.credits, entry.status) == (0.04, 0, "exempt")

    def test_a_view_as_basic_preview_never_charges_and_writes_nothing(self, store):
        token = set_principal(Principal(
            user_id="operator", tenant_id="operator", account_type="super", view_as_basic=True))
        try:
            assert run(billing.reserve("llm", 0.05, "x", settings=cfg())) is None
        finally:
            reset_principal(token)
        assert run(store.list_entries()) == []

    def test_a_call_with_no_principal_records_nothing(self, store):
        from contextvars import ContextVar

        from cf_platform.core import accounts

        token = accounts._principal_var.set(None)
        try:
            assert run(billing.reserve("llm", 0.05, "x", settings=cfg())) is None
        finally:
            accounts._principal_var.reset(token)
        assert isinstance(accounts._principal_var, ContextVar)

    def test_settle_and_refund_accept_no_hold(self, store, friend):
        run(billing.settle(None))
        run(billing.refund(None, "x"))

    def test_a_non_numeric_cost_is_refused_instead_of_raising_a_type_error(self, store, friend):
        with pytest.raises(HTTPException) as refused:
            run(billing.reserve("llm", object(), "x", settings=cfg()))
        assert refused.value.status_code == 503


# ── Top-up, sign-up grant, account view, stale holds (S4 / S5 core) ──────


class TestAccounts:
    def test_a_top_up_adds_credits_and_records_who_did_it(self, store):
        assert run(billing.topup("t1", 500, "friends beta", actor="owner@example.com", store=store)) == 500
        tx = run(store.list_transactions("t1"))[0]
        assert (tx.kind, tx.credits, tx.actor, tx.note) == ("topup", 500, "owner@example.com", "friends beta")

    def test_a_removal_takes_credits_off(self, store):
        run(billing.topup("t1", 100, store=store))
        assert run(billing.topup("t1", -40, "correction", store=store)) == 60
        assert run(store.list_transactions("t1"))[0].kind == "adjustment"

    def test_a_removal_cannot_take_the_balance_below_zero(self, store):
        run(billing.topup("t1", 10, store=store))
        with pytest.raises(HTTPException) as caught:
            run(billing.topup("t1", -11, store=store))
        assert caught.value.status_code == 409
        assert run(store.balance("t1")) == 10

    def test_a_zero_top_up_changes_nothing(self, store):
        assert run(billing.topup("t1", 0, store=store)) == 0
        assert run(store.list_transactions("t1")) == []

    def test_sign_up_credits_are_granted_once(self, store):
        assert run(billing.grant_signup_credits("t1", cfg(SIGNUP_CREDITS=50), store)) is True
        assert run(billing.grant_signup_credits("t1", cfg(SIGNUP_CREDITS=50), store)) is False
        assert run(store.balance("t1")) == 50

    def test_200_sign_up_credits_by_default_once(self, store):
        assert run(billing.grant_signup_credits("t1", cfg(), store)) is True
        assert run(billing.grant_signup_credits("t1", cfg(), store)) is False
        assert run(store.balance("t1")) == 200

    def test_my_account_shows_balance_and_the_newest_actions_first(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        first = run(billing.reserve("llm", 0.05, "writing the storyboard", settings=cfg()))
        run(billing.settle(first, settings=cfg()))
        run(billing.reserve("tts", 0.05, "the voiceover", settings=cfg()))
        account = run(billing.my_account(cfg(), store))
        assert account["enabled"] is True and account["balance"] == 80
        assert [h["what"] for h in account["history"]] == ["the voiceover", "writing the storyboard"]
        assert {"when", "what", "kind", "credits", "status", "run_id"} == set(account["history"][0])

    def test_my_account_is_empty_for_the_owner_and_when_billing_is_off(self, store, owner):
        assert run(billing.my_account(cfg(), store)) == {"enabled": False, "balance": 0, "history": [], "exempt": True}

    def test_my_account_reports_billing_off(self, store, friend):
        assert run(billing.my_account(cfg(BILLING_ENABLED=False), store))["enabled"] is False

    def test_holds_older_than_the_limit_are_given_back(self, store):
        run(store.credit("t1", 100, kind="topup"))
        old = UsageEntry(tenant_id="t1", kind="tts", credits=10, status="held",
                         created_at=datetime.now(UTC) - timedelta(hours=5))
        fresh = UsageEntry(tenant_id="t1", kind="tts", credits=10, status="held")
        run(store.add_entry(old))
        run(store.add_entry(fresh))
        run(store.debit("t1", 20, kind="hold"))
        assert run(billing.refund_stale_holds(120, cfg(), store)) == 1
        assert run(store.get_entry(old.entry_id)).status == "refunded"
        assert run(store.get_entry(fresh.entry_id)).status == "held"
        assert run(store.balance("t1")) == 90

    def test_the_admin_summary_adds_up(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        done = run(billing.reserve("image", 0.10, "x", settings=cfg()))
        run(billing.settle(done, 0.10, settings=cfg()))
        failed = run(billing.reserve("tts", 0.05, "y", settings=cfg()))
        run(billing.refund(failed, "boom"))
        row = {r["tenant_id"]: r for r in run(store.summary())}[friend]
        assert row["balance"] == 80 and row["credits_spent"] == 20 and row["actions"] == 2
        assert row["raw_cost_usd"] == 0.10  # the refunded action's cost is not counted

    def test_entry_filters(self, store):
        run(store.add_entry(UsageEntry(tenant_id="a", kind="llm")))
        run(store.add_entry(UsageEntry(tenant_id="a", kind="tts")))
        run(store.add_entry(UsageEntry(tenant_id="b", kind="tts")))
        assert len(run(store.list_entries("a"))) == 2
        assert len(run(store.list_entries(kind="tts"))) == 2
        assert len(run(store.list_entries("a", kind="tts"))) == 1
        assert len(run(store.list_entries(limit=1))) == 1
        assert len(run(store.list_entries(since=datetime.now(UTC) + timedelta(hours=1)))) == 0


def test_the_migration_defines_the_tables_the_postgres_store_uses():
    """0006 creates the three tables, keeps a balance non-negative and makes the sign-up grant unique."""
    from cf_platform.core.migrations import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "0006_billing.sql").read_text()
    for needle in (
        "CREATE TABLE IF NOT EXISTS usage_entries",
        "CREATE TABLE IF NOT EXISTS credit_accounts",
        "CREATE TABLE IF NOT EXISTS credit_transactions",
        "CHECK (balance >= 0)",
        "WHERE kind = 'signup'",
    ):
        assert needle in sql
    assert "DROP " not in sql.upper()


def test_the_postgres_store_debits_with_one_conditional_statement():
    """The hold is a single conditional UPDATE (no read-then-write), and a refusal reads on the same connection."""
    import inspect

    source = inspect.getsource(billing.PostgresBillingStore.debit)
    assert "WHERE tenant_id = %s AND balance >= %s" in source
    assert "self.balance(" not in source.split("if row is None:")[1]


# ── Review fixes: one close per hold, hold and entry together, stale holds ──


class _SlowStore(InMemoryBillingStore):
    """A store whose entry update yields to other tasks first — a check-then-act close would credit twice."""

    async def update_entry(self, entry):
        """Yield, then write."""
        await asyncio.sleep(0)
        await super().update_entry(entry)


class TestOneCloseOnly:
    @pytest.mark.parametrize("pair", [
        ("settle", "settle"), ("refund", "refund"), ("settle", "refund"), ("refund", "settle")])
    def test_two_concurrent_closers_credit_once(self, monkeypatch, friend, pair):
        store = _SlowStore()
        monkeypatch.setattr(billing, "_memory_store", store)
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))  # 20 held, balance 80

        async def closer(kind):
            if kind == "settle":
                await billing.settle(hold, 0.05, settings=cfg())  # price 10: 10 returned
            else:
                await billing.refund(hold, "failed")  # all 20 returned

        async def both():
            await asyncio.gather(closer(pair[0]), closer(pair[1]))

        run(both())
        entry = run(store.get_entry(hold.entry_id))
        credited = [t for t in run(store.list_transactions(friend)) if t.kind in ("settle", "refund")]
        assert len(credited) == 1, [(t.kind, t.credits) for t in credited]
        # whichever closer won decides the result; the other changed nothing
        assert (entry.status, run(store.balance(friend))) in (("settled", 90), ("refunded", 100))

    def test_a_settle_after_a_refund_does_not_charge_again_or_reopen_it(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        run(billing.refund(hold, "failed"))
        run(billing.settle(hold, settings=cfg()))
        assert run(store.get_entry(hold.entry_id)).status == "refunded"
        assert run(store.balance(friend)) == 100

    def test_close_held_reports_what_was_held_and_charged_and_none_the_second_time(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))
        assert run(store.close_held(hold.entry_id, price_credits=12)) == (20, 12)
        assert run(store.close_held(hold.entry_id, price_credits=12)) is None
        assert run(store.close_held("no-such-entry", price_credits=None)) is None

    def test_a_failure_while_crediting_leaves_the_entry_held_and_nothing_credited(self, store, friend):
        """The entry change and the credit are one unit: the credit step failing undoes the entry change."""
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))

        async def broken_credit(*_a, **_k):
            raise RuntimeError("database fell over")

        original = store.credit
        store.credit = broken_credit
        with pytest.raises(RuntimeError):
            run(store.close_held(hold.entry_id, price_credits=5))
        store.credit = original
        assert run(store.get_entry(hold.entry_id)).status == "held"
        assert run(store.balance(friend)) == 80
        # and because nothing moved, closing it again works and credits exactly once
        assert run(store.close_held(hold.entry_id, price_credits=5)) == (20, 5)
        assert run(store.balance(friend)) == 95

    def test_a_failure_while_updating_the_entry_credits_nothing(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))

        async def broken_update(_entry):
            raise RuntimeError("could not write the entry")

        original = store.update_entry
        store.update_entry = broken_update
        with pytest.raises(RuntimeError):
            run(store.close_held(hold.entry_id, price_credits=None))
        store.update_entry = original
        assert run(store.get_entry(hold.entry_id)).status == "held"
        assert run(store.balance(friend)) == 80
        assert [t.kind for t in run(store.list_transactions(friend))] == ["hold", "topup"]

    def test_settle_and_refund_log_the_fault_instead_of_raising_and_the_hold_stays_open(self, store, friend, caplog):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("image", 0.10, "x", settings=cfg()))

        async def broken_credit(*_a, **_k):
            raise RuntimeError("database fell over")

        store.credit = broken_credit
        run(billing.refund(hold, "failed"))
        assert "could not refund" in caplog.text
        del store.credit
        assert run(store.get_entry(hold.entry_id)).status == "held"
        # the owner can still give it back later
        assert run(billing.refund_stale_holds(0, cfg(), store)) == 1
        assert run(store.balance(friend)) == 100


class TestHoldAndEntryTogether:
    def test_a_crash_between_the_debit_and_the_entry_leaves_neither(self, monkeypatch, friend):
        class CrashBeforeEntry(InMemoryBillingStore):
            async def add_entry(self, entry):
                raise RuntimeError("the process died after the debit")

        store = CrashBeforeEntry()
        monkeypatch.setattr(billing, "_memory_store", store)
        run(store.credit(friend, 100, kind="topup"))
        with pytest.raises(RuntimeError):
            run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        assert run(store.balance(friend)) == 100
        assert [t.kind for t in run(store.list_transactions(friend))] == ["topup"], "no debit without its entry"
        assert run(store.list_entries(friend)) == []

    def test_a_refused_hold_writes_nothing(self, store, friend):
        run(store.credit(friend, 3, kind="topup"))
        entry = UsageEntry(tenant_id=friend, kind="tts", credits=10)
        assert run(store.hold(entry)) == (False, 3)
        assert run(store.list_entries(friend)) == []

    def test_a_free_hold_records_the_entry_and_no_debit(self, store, friend):
        entry = UsageEntry(tenant_id=friend, kind="render", credits=0)
        assert run(store.hold(entry)) == (True, 0)
        assert run(store.get_entry(entry.entry_id)).status == "held"
        assert run(store.list_transactions(friend)) == []

    def test_the_hold_and_its_entry_carry_the_same_id(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        hold = run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        tx = next(t for t in run(store.list_transactions(friend)) if t.kind == "hold")
        assert tx.entry_id == hold.entry_id and run(store.get_entry(hold.entry_id)).status == "held"


class TestStaleHolds:
    def test_a_hold_whose_job_is_still_running_is_not_refunded(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        running = run(billing.reserve("render", 0.05, "rendering the video", settings=cfg()))
        assert running.entry_id in billing._in_flight
        assert run(billing.refund_stale_holds(0, cfg(), store)) == 0
        assert run(store.get_entry(running.entry_id)).status == "held"
        assert run(store.balance(friend)) == 90

    def test_it_becomes_refundable_once_the_job_is_gone(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        lost = run(billing.reserve("render", 0.05, "rendering the video", settings=cfg()))
        billing._in_flight.clear()  # what a server restart does: the job no longer exists
        assert run(billing.refund_stale_holds(0, cfg(), store)) == 1
        assert run(store.get_entry(lost.entry_id)).status == "refunded"
        assert run(store.balance(friend)) == 100

    def test_settling_or_refunding_ends_the_in_flight_state(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        done = run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        failed = run(billing.reserve("tts", 0.05, "y", settings=cfg()))
        run(billing.settle(done, settings=cfg()))
        run(billing.refund(failed, "boom"))
        assert done.entry_id not in billing._in_flight and failed.entry_id not in billing._in_flight

    def test_a_refused_daily_bound_does_not_leave_the_hold_in_flight(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        with pytest.raises(HTTPException):
            run(billing.reserve("llm", 0.05, "x", settings=cfg(CAP_DAILY_SPEND_USD=0.01)))
        assert not billing._in_flight

    def test_only_old_holds_are_candidates(self, store, friend):
        run(store.credit(friend, 100, kind="topup"))
        run(billing.reserve("tts", 0.05, "x", settings=cfg()))
        billing._in_flight.clear()
        assert run(billing.refund_stale_holds(120, cfg(), store)) == 0  # held for seconds, limit two hours
