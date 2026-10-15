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
