"""Integration tests for P-BILL-1 against a real Postgres (excluded from CI: `-m "not integration"`).

Mocks cannot tell whether migration 0006 or the conditional SQL of PostgresBillingStore is
right, so these run them for real. Set CF_TEST_DATABASE_URL to a throwaway database:

    createdb cf_bill_test
    CF_TEST_DATABASE_URL=postgresql:///cf_bill_test pytest tests/integration/test_billing_postgres.py -m integration

Each test works inside its own schema, dropped afterwards.

Covers:
- 0006 applies on an empty database and is re-runnable
- concurrent holds cannot overdraw (and a refusal never leaves a transaction row)
- many refused holds at once do not exhaust a small connection pool
- the sign-up grant is made once, even from concurrent calls
- entries round-trip with their filters; the admin summary adds up
- the CHECK on credit_accounts refuses a negative balance
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.billing import PostgresBillingStore, UsageEntry
from cf_platform.core.migrations import MIGRATIONS_DIR

DATABASE_URL = os.environ.get("CF_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="CF_TEST_DATABASE_URL is not set"),
]

_BILLING = (MIGRATIONS_DIR / "0006_billing.sql").read_text()
_ACCOUNTS_SQL = (MIGRATIONS_DIR / "0005_accounts.sql").read_text()
# Only the daily USD bound's table: the rest of 0005 alters tables other migrations create.
_USAGE = _ACCOUNTS_SQL[_ACCOUNTS_SQL.index("CREATE TABLE IF NOT EXISTS tenant_usage"):].split(";")[0] + ";"


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool]:
    """Yield a small pool (as in production) whose connections live in a fresh schema with 0006 applied."""
    schema = f"bill_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
    test_pool = AsyncConnectionPool(
        conninfo=DATABASE_URL, open=False, max_size=4, kwargs={"options": f"-c search_path={schema}"}
    )
    await test_pool.open()
    try:
        async with test_pool.connection() as conn:
            await conn.execute(_USAGE)
            await conn.execute(_BILLING)
            await conn.commit()
        yield test_pool
    finally:
        await test_pool.close()
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.asyncio
async def test_migration_is_rerunnable(pool):
    """Applying 0006 a second time changes nothing and raises nothing."""
    async with pool.connection() as conn:
        await conn.execute(_BILLING)
        await conn.commit()


@pytest.mark.asyncio
async def test_concurrent_holds_cannot_overdraw(pool):
    """Ten holds of 30 against 100 credits: exactly three succeed, the balance is 10, refusals left no row."""
    store = PostgresBillingStore(pool)
    await store.credit("t1", 100, kind="topup")
    results = await asyncio.gather(*[store.debit("t1", 30, kind="hold", entry_id=f"e{i}") for i in range(10)])
    assert sum(1 for ok, _ in results if ok) == 3
    assert await store.balance("t1") == 10
    ok, left = await store.debit("t1", 11, kind="adjustment")
    assert (ok, left) == (False, 10)
    transactions = await store.list_transactions("t1")
    assert len(transactions) == 4 and sum(t.credits for t in transactions) == 10


@pytest.mark.asyncio
async def test_many_refused_holds_do_not_exhaust_the_pool(pool):
    """A refusal reads the balance on its own connection: 20 refusals at once on a pool of 4 finish."""
    store = PostgresBillingStore(pool)
    results = await asyncio.wait_for(
        asyncio.gather(*[store.debit("empty", 5, kind="hold") for _ in range(20)]), timeout=20
    )
    assert all(ok is False and balance == 0 for ok, balance in results)


@pytest.mark.asyncio
async def test_signup_grant_is_made_once(pool):
    """Five concurrent grants add the credits once."""
    store = PostgresBillingStore(pool)
    granted = await asyncio.gather(*[store.grant_signup("new", 25) for _ in range(5)])
    assert sum(granted) == 1
    assert await store.balance("new") == 25


@pytest.mark.asyncio
async def test_entries_filters_and_summary(pool):
    """An entry round-trips, the filters narrow the list and the summary adds up."""
    store = PostgresBillingStore(pool)
    await store.credit("t2", 50, kind="topup")
    entry = UsageEntry(tenant_id="t2", run_id="r1", kind="image", what="img", units=2, raw_cost_usd=0.04, credits=8)
    await store.add_entry(entry)
    entry.status, entry.actual_usd = "settled", 0.04
    await store.update_entry(entry)
    held = UsageEntry(
        tenant_id="t2", kind="tts", raw_cost_usd=0.05, credits=10, created_at=datetime.now(UTC) - timedelta(hours=3)
    )
    await store.add_entry(held)

    fetched = await store.get_entry(entry.entry_id)
    assert fetched is not None and fetched.status == "settled" and fetched.actual_usd == 0.04
    assert len(await store.list_entries("t2", kind="image")) == 1
    assert [e.entry_id for e in await store.list_entries(status="held")] == [held.entry_id]
    old = await store.list_entries(before=datetime.now(UTC) - timedelta(hours=1))
    assert [e.entry_id for e in old] == [held.entry_id]
    row = {r["tenant_id"]: r for r in await store.summary()}["t2"]
    assert row["balance"] == 50 and row["credits_spent"] == 18 and row["actions"] == 2


@pytest.mark.asyncio
async def test_negative_balance_is_refused_by_the_database(pool):
    """The CHECK on credit_accounts is the last line of defence."""
    store = PostgresBillingStore(pool)
    await store.credit("t3", 5, kind="topup")
    with pytest.raises(psycopg.errors.CheckViolation):
        async with pool.connection() as conn:
            await conn.execute("UPDATE credit_accounts SET balance = -1 WHERE tenant_id = 't3'")


# ── Review fixes: one close per hold, hold and entry in one transaction ──


async def _held(store: PostgresBillingStore, tenant: str, credits: int = 20) -> UsageEntry:
    """Fund the tenant and take a hold of `credits`; returns the held entry."""
    await store.credit(tenant, 100, kind="topup")
    entry = UsageEntry(tenant_id=tenant, kind="image", what="img", raw_cost_usd=0.1, credits=credits)
    assert (await store.hold(entry))[0] is True
    return entry


async def _raise_on(pool: AsyncConnectionPool, table: str, event: str, when: str) -> None:
    """Install a trigger that raises on `event` of `table` when `when` holds — a fault injected into one step."""
    async with pool.connection() as conn:
        await conn.execute(
            "CREATE OR REPLACE FUNCTION fail_step() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'injected failure'; END $$ LANGUAGE plpgsql"
        )
        await conn.execute(
            f"CREATE TRIGGER injected BEFORE {event} ON {table} FOR EACH ROW WHEN ({when}) EXECUTE FUNCTION fail_step()"
        )
        await conn.commit()


async def _remove_trigger(pool: AsyncConnectionPool, table: str) -> None:
    """Take the injected fault away again."""
    async with pool.connection() as conn:
        await conn.execute(f"DROP TRIGGER injected ON {table}")
        await conn.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("pair", [("settle", "settle"), ("refund", "refund"), ("settle", "refund"), ("refund", "settle")])
async def test_two_concurrent_closers_credit_exactly_once(pool, pair):
    """Two callers racing to close one held entry: one gets the row, only that one credits."""
    store = PostgresBillingStore(pool)
    entry = await _held(store, "race")  # balance 80, 20 held

    async def close(kind):
        if kind == "settle":
            return await store.close_held(entry.entry_id, price_credits=10, actual_usd=0.05)
        return await store.close_held(entry.entry_id, price_credits=None, note="failed")

    results = await asyncio.gather(close(pair[0]), close(pair[1]))
    assert sorted(r is None for r in results) == [False, True]
    credits = [t for t in await store.list_transactions("race") if t.kind in ("settle", "refund")]
    assert len(credits) == 1
    final = await store.get_entry(entry.entry_id)
    assert (final.status, await store.balance("race")) in (("settled", 90), ("refunded", 100))


@pytest.mark.asyncio
async def test_many_concurrent_closers_credit_once(pool):
    """Twenty callers on one entry, on a pool of 4: still one credit, and nobody hangs."""
    store = PostgresBillingStore(pool)
    entry = await _held(store, "crowd")
    results = await asyncio.wait_for(
        asyncio.gather(*[store.close_held(entry.entry_id, price_credits=None, note="x") for _ in range(20)]), timeout=30)
    assert sum(r is not None for r in results) == 1
    assert await store.balance("crowd") == 100


@pytest.mark.asyncio
async def test_a_failure_while_crediting_rolls_the_entry_change_back(pool):
    """The credit step fails after the entry was claimed: the whole transaction is undone, the entry is still held."""
    store = PostgresBillingStore(pool)
    entry = await _held(store, "credit-fails")
    await _raise_on(pool, "credit_accounts", "UPDATE", "NEW.balance > OLD.balance")
    with pytest.raises(psycopg.errors.RaiseException):
        await store.close_held(entry.entry_id, price_credits=None, note="failed")
    assert (await store.get_entry(entry.entry_id)).status == "held"
    assert await store.balance("credit-fails") == 80
    await _remove_trigger(pool, "credit_accounts")
    assert await store.close_held(entry.entry_id, price_credits=None, note="failed") == (20, 0)
    assert await store.balance("credit-fails") == 100


@pytest.mark.asyncio
async def test_a_failure_while_updating_the_entry_credits_nothing(pool):
    """The entry update fails: no credit is written, balance and transactions are unchanged."""
    store = PostgresBillingStore(pool)
    entry = await _held(store, "update-fails")
    await _raise_on(pool, "usage_entries", "UPDATE", "NEW.status <> 'held'")
    with pytest.raises(psycopg.errors.RaiseException):
        await store.close_held(entry.entry_id, price_credits=5, actual_usd=0.02)
    assert (await store.get_entry(entry.entry_id)).status == "held"
    assert await store.balance("update-fails") == 80
    assert [t.kind for t in await store.list_transactions("update-fails")] == ["hold", "topup"]


@pytest.mark.asyncio
async def test_settling_returns_the_excess_in_the_same_transaction_and_records_the_actuals(pool):
    """A settle below the hold credits the difference once, with the actual cost and units on the entry."""
    store = PostgresBillingStore(pool)
    entry = await _held(store, "settle-ok")
    assert await store.close_held(entry.entry_id, price_credits=12, actual_usd=0.06, units=3) == (20, 12)
    done = await store.get_entry(entry.entry_id)
    assert (done.status, done.credits, done.actual_usd, done.units) == ("settled", 12, 0.06, 3)
    assert await store.balance("settle-ok") == 88
    assert await store.close_held(entry.entry_id, price_credits=12) is None
    # an overrun is capped at the hold, and a price of zero refunds the hold
    over = await _held(store, "settle-over")
    assert await store.close_held(over.entry_id, price_credits=500) == (20, 20)
    zero = await _held(store, "settle-zero")
    assert await store.close_held(zero.entry_id, price_credits=0) == (20, 0)
    assert (await store.get_entry(zero.entry_id)).status == "refunded"


@pytest.mark.asyncio
async def test_a_crash_between_the_debit_and_the_entry_leaves_neither(pool):
    """The entry insert fails after the debit: the debit and its transaction row roll back with it."""
    store = PostgresBillingStore(pool)
    await store.credit("crash", 100, kind="topup")
    await _raise_on(pool, "usage_entries", "INSERT", "TRUE")
    entry = UsageEntry(tenant_id="crash", kind="tts", credits=10)
    with pytest.raises(psycopg.errors.RaiseException):
        await store.hold(entry)
    assert await store.balance("crash") == 100
    assert [t.kind for t in await store.list_transactions("crash")] == ["topup"]
    assert await store.get_entry(entry.entry_id) is None


@pytest.mark.asyncio
async def test_a_hold_and_its_entry_appear_together_and_a_refusal_writes_nothing(pool):
    """A successful hold has both rows; a refused one has neither; a free one has an entry and no debit."""
    store = PostgresBillingStore(pool)
    await store.credit("both", 15, kind="topup")
    ok = UsageEntry(tenant_id="both", kind="tts", credits=10)
    assert await store.hold(ok) == (True, 5)
    assert (await store.get_entry(ok.entry_id)).status == "held"
    refused = UsageEntry(tenant_id="both", kind="tts", credits=10)
    assert await store.hold(refused) == (False, 5)
    assert await store.get_entry(refused.entry_id) is None
    free = UsageEntry(tenant_id="both", kind="render", credits=0)
    assert await store.hold(free) == (True, 5)
    assert [t.kind for t in await store.list_transactions("both")] == ["hold", "topup"]


@pytest.mark.asyncio
async def test_concurrent_holds_still_cannot_overdraw_with_the_entry_written_too(pool):
    """Ten holds of 30 against 100 credits: three succeed, each with its entry; seven refusals leave no entry."""
    store = PostgresBillingStore(pool)
    await store.credit("burst", 100, kind="topup")
    entries = [UsageEntry(tenant_id="burst", kind="llm", credits=30) for _ in range(10)]
    results = await asyncio.wait_for(asyncio.gather(*[store.hold(e) for e in entries]), timeout=30)
    assert sum(1 for ok, _ in results if ok) == 3
    assert await store.balance("burst") == 10
    assert len(await store.list_entries("burst")) == 3


@pytest.mark.asyncio
async def test_refund_and_settle_release_the_daily_reservation(pool, monkeypatch):
    """BILL-F1 on real SQL: a refund restores the day's room, a settle at half returns half, a double refund releases once."""
    from cf_platform.core import billing, limits
    from cf_platform.core.accounts import Principal, reset_principal, set_principal
    from cf_platform.core.config import PlatformSettings

    ledger, usage = PostgresBillingStore(pool), limits.PostgresUsageStore(pool)
    monkeypatch.setattr(limits, "get_usage_store", lambda: usage)
    settings = PlatformSettings.model_validate({
        "R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a",
        "BILLING_ENABLED": True, "CAP_DAILY_SPEND_USD": 1.0,
    })
    token = set_principal(Principal(user_id="u_f1", tenant_id="u_f1", account_type="basic"))
    try:
        await ledger.credit("u_f1", 1000, kind="topup")
        today = datetime.now(UTC).date()
        kept = await billing.reserve("tts", 0.30, "kept", settings=settings, store=ledger)
        hold = await billing.reserve("image", 0.10, "x", settings=settings, store=ledger)
        assert await usage.spend_today("u_f1", today) == pytest.approx(0.40)
        await billing.settle(hold, 0.05, settings=settings, store=ledger)
        assert await usage.spend_today("u_f1", today) == pytest.approx(0.35)
        failed = await billing.reserve("tts", 0.20, "y", settings=settings, store=ledger)
        await asyncio.gather(*[billing.refund(failed, "boom", store=ledger) for _ in range(5)])
        assert await usage.spend_today("u_f1", today) == pytest.approx(0.35)  # released once, not five times
        assert kept is not None
        assert await usage.release_spend("u_f1", today, 99.0) == 0.0  # never below zero
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_the_cost_report_reads_the_ledger_and_leaves_the_owners_actions_out(pool):
    """BILL-F3: fetch_entries on real SQL — the window, the exempt filter and the run count."""
    from cf_platform.core.cost_report import fetch_entries

    store = PostgresBillingStore(pool)
    now = datetime.now(UTC)
    rows = [
        ("r1", "llm", "settled", now), ("r1", "tts", "refunded", now), ("r2", "llm", "exempt", now),
        ("r2", "render", "settled", now - timedelta(days=40)),
    ]
    for i, (run_id, kind, status, created) in enumerate(rows):
        await store.add_entry(UsageEntry(
            entry_id=f"e{i}", tenant_id="t1", run_id=run_id, kind=kind, status=status, raw_cost_usd=0.05, created_at=created))
    entries, runs = await fetch_entries(pool, 30)
    assert sorted((e["kind"], e["status"]) for e in entries) == [("llm", "settled"), ("tts", "refunded")]
    assert runs == 1
