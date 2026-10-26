"""Integration test for the erase tool (LEGAL-S1) against a real Postgres (excluded from CI: `-m "not integration"`).

The delete statements, their order against the foreign keys, the dry-run rollback and the ledger
anonymisation can only be checked against the real schema. Set CF_TEST_DATABASE_URL to a throwaway database:

    createdb cf_bill_test
    CF_TEST_DATABASE_URL=postgresql:///cf_bill_test pytest tests/integration/test_erasure_postgres.py -m integration

Each test works inside its own schema (every migration applied), dropped afterwards. Two tenants are seeded;
erasing one must leave the other's rows and files exactly as they were.
"""

import os
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.erasure import ErasureRefused, erase_tenant, pseudonym
from cf_platform.core.migrations import MIGRATIONS_DIR

DATABASE_URL = os.environ.get("CF_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="CF_TEST_DATABASE_URL is not set"),
]


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool]:
    """A small pool on a fresh schema with every migration applied, plus the LangGraph checkpoint tables' shape."""
    schema = f"erase_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
    test_pool = AsyncConnectionPool(
        conninfo=DATABASE_URL, open=False, max_size=4, kwargs={"options": f"-c search_path={schema}"}
    )
    await test_pool.open()
    try:
        async with test_pool.connection() as conn:
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                await conn.execute(path.read_text())
            await conn.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL)")
            await conn.commit()
        yield test_pool
    finally:
        await test_pool.close()
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


async def seed(pool: AsyncConnectionPool, tenant: str, email: str) -> None:
    """One tenant with a user, a session, a project, two runs (one archived) and a row in every table that points at them."""
    run_a, run_b = f"{tenant}-r1", f"{tenant}-r2"
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, tenant_id, google_sub, email, name) VALUES (%s, %s, %s, %s, 'N')",
            (tenant, tenant, f"sub-{tenant}", email),
        )
        await conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + interval '1 day')",
            (f"tok-{tenant}", tenant),
        )
        await conn.execute("INSERT INTO invited_emails (email) VALUES (%s)", (email,))
        await conn.execute("INSERT INTO projects (project_id, tenant_id, name) VALUES (%s, %s, 'P')", (f"p-{tenant}", tenant))
        for run_id, archived in ((run_a, False), (run_b, True)):
            await conn.execute(
                "INSERT INTO runs (run_id, user_id, tenant_id, project_id, block, status) VALUES (%s, %s, %s, %s, 'creator', 'created')",
                (run_id, tenant, tenant, f"p-{tenant}"),
            )
            if archived:
                await conn.execute("UPDATE runs SET archived_at = now() WHERE run_id = %s", (run_id,))
            await conn.execute(
                "INSERT INTO artifacts (run_id, name, stage, version, r2_key, worker, worker_version, prompt_version, model) "
                "VALUES (%s, 'a', 's', 1, 'k', 'w', '1', '1', 'm')", (run_id,),
            )
            await conn.execute(
                "INSERT INTO worker_executions (run_id, worker, worker_version, prompt_version, model, status, started_at, finished_at) "
                "VALUES (%s, 'w', '1', '1', 'm', 'ok', now(), now())", (run_id,),
            )
            await conn.execute(
                "INSERT INTO trace_events (run_id, worker, source, op, status) VALUES (%s, 'w', 's', 'o', 'ok')", (run_id,)
            )
            await conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_id) VALUES (%s, 'c1'), (%s, 'c2')", (run_id, f"{run_id}:idea_to_script:ab12"))
        await conn.execute(
            "INSERT INTO published_videos (run_id, platform, external_id) VALUES (%s, 'youtube', %s)", (run_a, f"yt-{tenant}")
        )
        await conn.execute(
            "INSERT INTO video_metrics (external_id, platform, metric, value) VALUES (%s, 'youtube', 'views', 1)", (f"yt-{tenant}",)
        )
        await conn.execute(
            "INSERT INTO shortlist_items (item_id, tenant_id, project_id, title, discovery_method, discovered_at) "
            "VALUES (%s, %s, %s, 't', 'manual', now())", (f"i-{tenant}", tenant, f"p-{tenant}"),
        )
        await conn.execute("INSERT INTO run_shortlist_items (run_id, item_id) VALUES (%s, %s)", (run_a, f"i-{tenant}"))
        await conn.execute("INSERT INTO tenant_settings (tenant_id, image_provider) VALUES (%s, 'x')", (tenant,))
        await conn.execute("INSERT INTO tenant_usage (tenant_id, day, runs) VALUES (%s, current_date, 1)", (tenant,))
        await conn.execute("INSERT INTO prompt_log (tenant_id, kind, excerpt) VALUES (%s, 'script', 'secret words')", (tenant,))
        await conn.execute(
            "INSERT INTO usage_entries (entry_id, tenant_id, run_id, kind, what, note, status) "
            "VALUES (%s, %s, %s, 'tts', 'voice', 'failed: some prompt text', 'refunded')", (f"e-{tenant}", tenant, run_a),
        )
        await conn.execute("INSERT INTO credit_accounts (tenant_id, balance) VALUES (%s, 50)", (tenant,))
        await conn.execute(
            "INSERT INTO credit_transactions (tenant_id, kind, credits, note, actor) VALUES (%s, 'topup', 50, 'gift', 'owner')", (tenant,)
        )
        await conn.commit()


async def counts(pool: AsyncConnectionPool, tenant: str) -> dict[str, int]:
    """How many rows of each kind still carry the tenant (ledger tables are counted by the pseudonym when anonymised)."""
    queries = {
        "users": "SELECT count(*) FROM users WHERE tenant_id = %(t)s",
        "sessions": "SELECT count(*) FROM sessions WHERE user_id = %(t)s",
        "invited_emails": "SELECT count(*) FROM invited_emails WHERE email = %(e)s",
        "projects": "SELECT count(*) FROM projects WHERE tenant_id = %(t)s",
        "runs": "SELECT count(*) FROM runs WHERE tenant_id = %(t)s",
        "artifacts": "SELECT count(*) FROM artifacts WHERE run_id LIKE %(t)s || '-%%'",
        "worker_executions": "SELECT count(*) FROM worker_executions WHERE run_id LIKE %(t)s || '-%%'",
        "trace_events": "SELECT count(*) FROM trace_events WHERE run_id LIKE %(t)s || '-%%'",
        "checkpoints": "SELECT count(*) FROM checkpoints WHERE thread_id LIKE %(t)s || '-%%'",
        "published_videos": "SELECT count(*) FROM published_videos WHERE run_id LIKE %(t)s || '-%%'",
        "video_metrics": "SELECT count(*) FROM video_metrics WHERE external_id = 'yt-' || %(t)s",
        "shortlist_items": "SELECT count(*) FROM shortlist_items WHERE tenant_id = %(t)s",
        "run_shortlist_items": "SELECT count(*) FROM run_shortlist_items WHERE item_id = 'i-' || %(t)s",
        "tenant_settings": "SELECT count(*) FROM tenant_settings WHERE tenant_id = %(t)s",
        "tenant_usage": "SELECT count(*) FROM tenant_usage WHERE tenant_id = %(t)s",
        "prompt_log": "SELECT count(*) FROM prompt_log WHERE tenant_id = %(t)s",
        "usage_entries": "SELECT count(*) FROM usage_entries WHERE tenant_id = %(t)s",
        "credit_accounts": "SELECT count(*) FROM credit_accounts WHERE tenant_id = %(t)s",
        "credit_transactions": "SELECT count(*) FROM credit_transactions WHERE tenant_id = %(t)s",
    }
    out: dict[str, int] = {}
    async with pool.connection() as conn:
        for label, sql in queries.items():
            cur = await conn.execute(sql, {"t": tenant, "e": f"{tenant}@example.com"})
            out[label] = (await cur.fetchone())[0]
    return out


async def seed_files(storage: InMemoryArtifactStorage, tenant: str) -> None:
    """The tenant's files under each prefix the erase tool covers."""
    await storage.put_json(f"users/{tenant}/runs/{tenant}-r1/storyboard/verified_storyboard@v1.json", {})
    await storage.put_bytes(f"runs/{tenant}-r1/output/final.mp4", b"x")
    await storage.put_bytes(f"runs/{tenant}-r2/images/scene_1.png", b"x")  # the archived run
    await storage.put_bytes(f"tenant-music/{tenant}/song.mp3", b"x")


@pytest.mark.asyncio
async def test_a_dry_run_reports_exact_counts_and_changes_nothing(pool):
    await seed(pool, "u_a", "u_a@example.com")
    storage = InMemoryArtifactStorage()
    await seed_files(storage, "u_a")
    before, files_before = await counts(pool, "u_a"), await storage.list_keys("")
    report = await erase_tenant(pool, storage, email="U_A@example.com")  # case-insensitive, dry run by default
    assert report.dry_run and report.tenant_id == "u_a" and report.files == 4 and len(report.run_ids) == 2
    assert report.rows["runs"] == 2 and report.rows["artifacts"] == 2 and report.rows["checkpoints"] == 4
    assert report.rows["users"] == 1 and report.rows["sessions"] == 1 and report.rows["video_metrics"] == 1
    assert await counts(pool, "u_a") == before and await storage.list_keys("") == files_before


@pytest.mark.asyncio
async def test_erasing_one_tenant_removes_their_rows_and_files_and_leaves_the_other_untouched(pool):
    for tenant in ("u_a", "u_b"):
        await seed(pool, tenant, f"{tenant}@example.com")
    storage = InMemoryArtifactStorage()
    await seed_files(storage, "u_a")
    await seed_files(storage, "u_b")
    b_rows = await counts(pool, "u_b")
    b_all = sorted(k for k in await storage.list_keys("") if "u_b" in k)

    report = await erase_tenant(pool, storage, tenant_id="u_a", dry_run=False)
    assert not report.dry_run and report.files == 4

    gone = await counts(pool, "u_a")
    assert all(v == 0 for v in gone.values())  # nothing is left under the old tenant id, ledger included
    assert sorted(k for k in await storage.list_keys("") if "u_a" in k) == []
    assert await counts(pool, "u_b") == b_rows
    assert sorted(k for k in await storage.list_keys("") if "u_b" in k) == b_all

    # the ledger survives, anonymised: counted, but no longer tied to the tenant, run or free text
    alias = pseudonym("u_a")
    async with pool.connection() as conn:
        entry = await (await conn.execute("SELECT run_id, note, tenant_id FROM usage_entries WHERE tenant_id = %s", (alias,))).fetchone()
        tx = await (await conn.execute("SELECT note, actor FROM credit_transactions WHERE tenant_id = %s", (alias,))).fetchone()
        balance = await (await conn.execute("SELECT balance FROM credit_accounts WHERE tenant_id = %s", (alias,))).fetchone()
    assert entry == ("", "", alias) and tx == ("", "") and balance == (50,)


@pytest.mark.asyncio
async def test_a_failure_in_the_rows_rolls_everything_back_and_a_rerun_finishes(pool, monkeypatch):
    await seed(pool, "u_a", "u_a@example.com")
    storage = InMemoryArtifactStorage()
    await seed_files(storage, "u_a")
    before = await counts(pool, "u_a")

    async with pool.connection() as conn:  # a trigger that refuses the last delete, to fail mid-transaction
        await conn.execute(
            "CREATE FUNCTION refuse() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'no'; END $$ LANGUAGE plpgsql"
        )
        await conn.execute("CREATE TRIGGER refuse_users BEFORE DELETE ON users FOR EACH ROW EXECUTE FUNCTION refuse()")
        await conn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        await erase_tenant(pool, storage, tenant_id="u_a", dry_run=False)
    assert await counts(pool, "u_a") == before  # the transaction left every row alone (the files were already gone)

    async with pool.connection() as conn:
        await conn.execute("DROP TRIGGER refuse_users ON users")
        await conn.commit()
    report = await erase_tenant(pool, storage, tenant_id="u_a", dry_run=False)
    assert report.files == 0 and all(v == 0 for v in (await counts(pool, "u_a")).values())


@pytest.mark.asyncio
async def test_the_owner_and_unknown_tenants_are_refused(pool):
    storage = InMemoryArtifactStorage()
    with pytest.raises(ErasureRefused):
        await erase_tenant(pool, storage, tenant_id="operator")
    with pytest.raises(LookupError):
        await erase_tenant(pool, storage, email="nobody@example.com")
    with pytest.raises(LookupError):
        await erase_tenant(pool, storage, tenant_id="u_unknown")
