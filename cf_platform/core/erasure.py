"""Erase one tenant's data (LEGAL-S1): the code behind ``scripts/erase_tenant.py`` and RUNBOOK "Erasing an account".

What goes:
* every R2 object under ``users/{tenant}/`` and ``tenant-music/{tenant}/``, and under ``runs/{run_id}/`` for each of
  the tenant's runs (archived ones too — a deleted video is only hidden until now);
* the tenant's rows: sign-in (``users``, ``sessions``), projects, runs and everything hanging off a run
  (artifacts, worker executions, trace events, published videos and their metrics, shortlist, LangGraph checkpoints),
  settings, daily usage counters, the prompt log, and the invitation for the user's e-mail.

What stays, without the identity: the credit ledger (``usage_entries``, ``credit_transactions``, ``credit_accounts``) is
kept because accounting may need it. Its tenant id becomes a one-way pseudonym and the free-text notes and run ids are
cleared, so a row can no longer be tied back to a person.

The owner's tenant is refused. Rows are deleted in one transaction (a dry run runs the same statements and rolls them
back, so its counts are exact). Files go first: if that fails nothing else was touched, and if the rows then fail the
run is safe to repeat.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from cf_platform.core.accounts import OWNER_TENANT_ID

_logger = logging.getLogger(__name__)

# The LangGraph checkpoint tables are created by the checkpointer's own setup, so they may not exist.
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


class ErasureRefused(ValueError):
    """The tenant must not be erased (the owner's, or an empty id)."""


@dataclass
class ErasureReport:
    """What an erase run removed (or, for a dry run, would remove)."""

    tenant_id: str
    dry_run: bool
    emails: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    prefixes: list[str] = field(default_factory=list)
    files: int = 0
    sample_files: list[str] = field(default_factory=list)
    rows: dict[str, int] = field(default_factory=dict)
    anonymised_as: str = ""


def pseudonym(tenant_id: str) -> str:
    """The one-way stand-in for a tenant id in the kept credit ledger."""
    return "erased_" + hashlib.sha256(tenant_id.encode()).hexdigest()[:12]


def check_tenant(tenant_id: str) -> str:
    """Return the tenant id, or raise ErasureRefused when it is empty or the owner's."""
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        raise ErasureRefused("A tenant id is required.")
    if tenant_id == OWNER_TENANT_ID:
        raise ErasureRefused("The owner's tenant is not erased by this tool.")
    return tenant_id


def file_prefixes(tenant_id: str, run_ids: list[str]) -> list[str]:
    """The R2 prefixes that hold the tenant's files (each ends in "/" so one id cannot match another's)."""
    prefixes = [f"users/{tenant_id}/", f"tenant-music/{tenant_id}/"]
    prefixes += [f"runs/{run_id}/" for run_id in run_ids if run_id]
    return prefixes


async def collect_files(storage: Any, prefixes: list[str]) -> list[str]:
    """Every key under the prefixes."""
    keys: list[str] = []
    for prefix in prefixes:
        keys += await storage.list_keys(prefix)
    return sorted(set(keys))


async def delete_files(storage: Any, keys: list[str]) -> int:
    """Delete the keys one by one. Returns how many were deleted; the first failure is raised."""
    for key in keys:
        await storage.delete_key(key)
    return len(keys)


async def delete_prefixes(storage: Any, prefixes: list[str], *, max_rounds: int = 50) -> int:
    """Delete everything under the prefixes, re-listing until each is empty. Returns how many keys went.

    A listing can be cut short (R2 answers 1000 keys a call), so one pass is never trusted: the
    prefixes are listed again after each deletion and the loop only ends on an empty listing. If
    objects remain after ``max_rounds`` the run fails loudly rather than report a partial erasure.
    """
    deleted = 0
    for _ in range(max_rounds):
        keys = await collect_files(storage, prefixes)
        if not keys:
            return deleted
        deleted += await delete_files(storage, keys)
    raise RuntimeError(f"Objects are still left under {prefixes[:3]} after {max_rounds} passes; nothing else was erased.")


async def find_tenant(pool: Any, *, email: str = "", tenant_id: str = "") -> tuple[str, list[str]]:
    """Resolve an e-mail or a tenant id to (tenant id, the e-mails of its users). Raises LookupError when unknown."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            if email:
                await cur.execute("SELECT tenant_id FROM users WHERE lower(email) = lower(%s)", (email.strip(),))
                row = await cur.fetchone()
                if row is None:
                    raise LookupError(f"No account has the e-mail {email!r}.")
                tenant_id = row[0]
            await cur.execute("SELECT email FROM users WHERE tenant_id = %s", (tenant_id,))
            emails = [r[0] for r in await cur.fetchall() if r[0]]
            await cur.execute("SELECT 1 FROM users WHERE tenant_id = %s UNION ALL SELECT 1 FROM runs WHERE tenant_id = %s LIMIT 1", (tenant_id, tenant_id))
            if await cur.fetchone() is None:
                raise LookupError(f"No data found for tenant {tenant_id!r}.")
    return tenant_id, emails


async def tenant_run_ids(pool: Any, tenant_id: str) -> list[str]:
    """The ids of every run the tenant owns, archived ones included."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT run_id FROM runs WHERE tenant_id = %s", (tenant_id,))
            return [r[0] for r in await cur.fetchall()]


async def _count(cur: Any, label: str, sql: str, params: tuple, rows: dict[str, int]) -> None:
    """Run one statement and add its affected-row count to rows[label]."""
    await cur.execute(sql, params)
    rows[label] = rows.get(label, 0) + max(cur.rowcount, 0)


async def erase_rows(pool: Any, tenant_id: str, run_ids: list[str], emails: list[str], *, dry_run: bool) -> dict[str, int]:
    """Delete the tenant's rows (and anonymise its ledger) in one transaction; a dry run rolls it back."""
    tenant_id = check_tenant(tenant_id)
    alias = pseudonym(tenant_id)
    rows: dict[str, int] = {}
    lowered = [e.lower() for e in emails]
    async with pool.connection() as conn:
        try:
            async with conn.cursor() as cur:
                for table in _CHECKPOINT_TABLES:
                    await cur.execute("SELECT to_regclass(%s)", (table,))
                    if (await cur.fetchone())[0] is not None:
                        await _count(
                            cur, table,
                            f"DELETE FROM {table} WHERE thread_id = ANY(%s) OR split_part(thread_id, ':', 1) = ANY(%s)",
                            (run_ids, run_ids), rows,
                        )
                await _count(
                    cur, "video_metrics",
                    "DELETE FROM video_metrics m USING published_videos p "
                    "WHERE p.run_id = ANY(%s) AND m.external_id = p.external_id AND m.platform = p.platform",
                    (run_ids,), rows,
                )
                for table in ("published_videos", "trace_events", "worker_executions", "artifacts", "run_shortlist_items"):
                    await _count(cur, table, f"DELETE FROM {table} WHERE run_id = ANY(%s)", (run_ids,), rows)
                await _count(
                    cur, "run_shortlist_items",
                    "DELETE FROM run_shortlist_items WHERE item_id IN (SELECT item_id FROM shortlist_items WHERE tenant_id = %s)",
                    (tenant_id,), rows,
                )
                await _count(cur, "shortlist_items", "DELETE FROM shortlist_items WHERE tenant_id = %s", (tenant_id,), rows)
                await _count(cur, "runs", "DELETE FROM runs WHERE tenant_id = %s", (tenant_id,), rows)
                for table in ("projects", "tenant_settings", "tenant_usage", "prompt_log"):
                    await _count(cur, table, f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,), rows)
                await _count(
                    cur, "usage_entries (anonymised)",
                    "UPDATE usage_entries SET tenant_id = %s, run_id = '', note = '' WHERE tenant_id = %s",
                    (alias, tenant_id), rows,
                )
                await _count(
                    cur, "credit_transactions (anonymised)",
                    "UPDATE credit_transactions SET tenant_id = %s, note = '', actor = '' WHERE tenant_id = %s",
                    (alias, tenant_id), rows,
                )
                await _count(
                    cur, "credit_accounts (anonymised)",
                    "UPDATE credit_accounts SET tenant_id = %s WHERE tenant_id = %s", (alias, tenant_id), rows,
                )
                if lowered:
                    await _count(cur, "invited_emails", "DELETE FROM invited_emails WHERE lower(email) = ANY(%s)", (lowered,), rows)
                await _count(
                    cur, "sessions",
                    "DELETE FROM sessions WHERE user_id IN (SELECT user_id FROM users WHERE tenant_id = %s)",
                    (tenant_id,), rows,
                )
                await _count(cur, "users", "DELETE FROM users WHERE tenant_id = %s", (tenant_id,), rows)
            if dry_run:
                await conn.rollback()
            else:
                await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
    return rows


async def erase_tenant(
    pool: Any, storage: Any, *, tenant_id: str = "", email: str = "", dry_run: bool = True, sample: int = 10,
) -> ErasureReport:
    """Erase (or, by default, only count) one tenant's files and rows. See the module docstring."""
    if email:
        tenant_id, emails = await find_tenant(pool, email=email)
    else:
        tenant_id = check_tenant(tenant_id)
        tenant_id, emails = await find_tenant(pool, tenant_id=tenant_id)
    tenant_id = check_tenant(tenant_id)
    run_ids = await tenant_run_ids(pool, tenant_id)
    prefixes = file_prefixes(tenant_id, run_ids)
    keys = await collect_files(storage, prefixes)
    report = ErasureReport(
        tenant_id=tenant_id, dry_run=dry_run, emails=emails, run_ids=run_ids, prefixes=prefixes,
        files=len(keys), sample_files=keys[:sample], anonymised_as=pseudonym(tenant_id),
    )
    if not dry_run:
        report.files = await delete_prefixes(storage, prefixes)
    report.rows = await erase_rows(pool, tenant_id, run_ids, emails, dry_run=dry_run)
    _logger.info(
        "erasure: tenant=%s dry_run=%s files=%d rows=%s", tenant_id, dry_run, report.files, report.rows,
    )
    return report
