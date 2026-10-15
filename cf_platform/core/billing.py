"""The usage ledger and credits (Sprint P-BILL-1, D123).

Every paid action — an LLM call, a voiceover, a transcription, an image, a render — is
one priced :class:`UsageEntry` with its raw provider cost. For every tenant except the
owner's it is also *charged* in credits, in three steps that are the only way a balance
moves for a paid action:

1. :func:`reserve` **holds** the action's price from the balance before the provider is
   called. The hold is one atomic conditional statement, so several actions started at
   once cannot overdraw; one that does not fit is refused with 402 naming its cost and
   the balance, and nothing starts.
2. :func:`settle` closes the hold at the actual cost when that is known (the excess is
   returned; the platform absorbs an overrun — a user is never charged more than they
   were shown).
3. :func:`refund` returns a hold in full when the action failed.

``BILLING_ENABLED`` (default false) turns charging on. Off, the ledger still records
every action as ``metered`` — what it would have cost — and no balance is touched.
The owner's actions are recorded as ``exempt``; a View-as-Basic session records nothing
(the preview never charges and never writes the owner's ledger, D114).

The daily USD bound of ``limits.spend_gate`` (D120) stays as a second, independent
ceiling: the hold is taken first, and a refused daily bound gives the hold back.
"""

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from fastapi import HTTPException
from pydantic import BaseModel, Field

from cf_platform.core import limits
from cf_platform.core.accounts import NotAuthenticatedError, current_principal
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import get_pool

_logger = logging.getLogger(__name__)

Kind = Literal["llm", "tts", "transcription", "image", "render"]
EntryStatus = Literal["held", "settled", "refunded", "exempt", "metered"]
TransactionKind = Literal["topup", "signup", "hold", "settle", "refund", "adjustment"]

# Float noise guard for ceil(): 0.05 * 2 / 0.01 is 10.000000000000002, which is 10 credits, not 11.
_EPSILON = 1e-9


class UsageEntry(BaseModel):
    """One paid action: what it was, what the provider charged and what the user was charged."""

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    tenant_id: str
    run_id: str = ""
    kind: Kind
    what: str = ""
    units: float = 1.0
    raw_cost_usd: float = 0.0
    actual_usd: float | None = None
    credits: int = 0
    status: EntryStatus = "held"
    note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None


class CreditTransaction(BaseModel):
    """One signed change to a tenant's balance."""

    tenant_id: str
    kind: TransactionKind
    credits: int
    entry_id: str = ""
    note: str = ""
    actor: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PaymentRequiredError(HTTPException):
    """402 — the balance does not cover an action. Carries the numbers for the page."""

    def __init__(self, cost_credits: int, balance_credits: int, what: str = "this") -> None:
        """Build the refusal: it names the cost and what is left."""
        self.cost_credits = cost_credits
        self.balance_credits = balance_credits
        super().__init__(
            status_code=402,
            detail=f"{what.capitalize()} costs {cost_credits} credits; you have {balance_credits}.",
        )


class Hold:
    """The handle :func:`reserve` returns: what was held, for settle / refund to close."""

    __slots__ = ("entry_id", "tenant_id", "credits", "raw_usd", "kind", "charged", "recorded")

    def __init__(self, entry: UsageEntry, charged: bool, recorded: bool = True) -> None:
        """Remember the entry's id and what is held (credits are held only when ``charged``)."""
        self.entry_id = entry.entry_id
        self.tenant_id = entry.tenant_id
        self.credits = entry.credits
        self.raw_usd = entry.raw_cost_usd
        self.kind = entry.kind
        self.charged = charged
        self.recorded = recorded


class BillingStore(Protocol):
    """Ledger and balances. Every balance change writes its transaction row with it."""

    async def balance(self, tenant_id: str) -> int:
        """The tenant's balance in credits (0 when it has no account yet)."""
        ...

    async def debit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> tuple[bool, int]:
        """Take credits unless the balance is lower. Returns (ok, balance after / before)."""
        ...

    async def credit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> int:
        """Add credits. Returns the balance after."""
        ...

    async def grant_signup(self, tenant_id: str, credits: int) -> bool:
        """Grant the sign-up credits once per tenant. True when this call made the grant."""
        ...

    async def add_entry(self, entry: UsageEntry) -> None:
        """Store a new entry."""
        ...

    async def update_entry(self, entry: UsageEntry) -> None:
        """Replace an entry (same id)."""
        ...

    async def get_entry(self, entry_id: str) -> UsageEntry | None:
        """One entry, or None."""
        ...

    async def list_entries(
        self, tenant_id: str | None = None, *, kind: str | None = None, status: str | None = None,
        since: datetime | None = None, before: datetime | None = None, limit: int = 100, offset: int = 0,
    ) -> list[UsageEntry]:
        """Newest-first entries, optionally one tenant's, one kind's, one status and between two times."""
        ...

    async def list_transactions(self, tenant_id: str, limit: int = 100) -> list[CreditTransaction]:
        """Newest-first balance changes of one tenant."""
        ...

    async def summary(self) -> list[dict[str, Any]]:
        """One row per tenant with an account or an entry: balance, credits spent, raw cost, actions, last action."""
        ...


def _summary_row(tenant_id: str, balance: int, entries: list[UsageEntry]) -> dict[str, Any]:
    """Fold a tenant's entries into the admin summary row (settled and held actions count as spent)."""
    charged = [e for e in entries if e.status in ("held", "settled")]
    last = max((e.created_at for e in entries), default=None)
    return {
        "tenant_id": tenant_id,
        "balance": balance,
        "credits_spent": sum(e.credits for e in charged),
        "raw_cost_usd": round(sum((e.actual_usd if e.actual_usd is not None else e.raw_cost_usd) for e in entries
                                  if e.status != "refunded"), 6),
        "actions": len(entries),
        "last_action_at": last,
    }


class InMemoryBillingStore:
    """Process-local BillingStore — the local-development fallback (D048) and the tests' reference."""

    def __init__(self) -> None:
        """Start empty."""
        self._balances: dict[str, int] = {}
        self._entries: dict[str, UsageEntry] = {}
        self._transactions: list[CreditTransaction] = []
        self._signups: set[str] = set()

    async def balance(self, tenant_id: str) -> int:
        """The tenant's balance in credits."""
        return self._balances.get(tenant_id, 0)

    async def debit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> tuple[bool, int]:
        """Take credits unless the balance is lower (no await between check and write, so it is atomic here)."""
        current = self._balances.get(tenant_id, 0)
        if credits > current:
            return False, current
        self._balances[tenant_id] = current - credits
        self._transactions.append(CreditTransaction(
            tenant_id=tenant_id, kind=kind, credits=-credits, entry_id=entry_id, note=note, actor=actor))
        return True, current - credits

    async def credit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> int:
        """Add credits and record the change."""
        self._balances[tenant_id] = self._balances.get(tenant_id, 0) + credits
        self._transactions.append(CreditTransaction(
            tenant_id=tenant_id, kind=kind, credits=credits, entry_id=entry_id, note=note, actor=actor))
        return self._balances[tenant_id]

    async def grant_signup(self, tenant_id: str, credits: int) -> bool:
        """Grant once per tenant."""
        if credits <= 0 or tenant_id in self._signups:
            return False
        self._signups.add(tenant_id)
        await self.credit(tenant_id, credits, kind="signup", note="sign-up credits")
        return True

    async def add_entry(self, entry: UsageEntry) -> None:
        """Store a new entry."""
        self._entries[entry.entry_id] = entry.model_copy()

    async def update_entry(self, entry: UsageEntry) -> None:
        """Replace an entry."""
        self._entries[entry.entry_id] = entry.model_copy()

    async def get_entry(self, entry_id: str) -> UsageEntry | None:
        """One entry, or None."""
        found = self._entries.get(entry_id)
        return found.model_copy() if found else None

    async def list_entries(
        self, tenant_id: str | None = None, *, kind: str | None = None, status: str | None = None,
        since: datetime | None = None, before: datetime | None = None, limit: int = 100, offset: int = 0,
    ) -> list[UsageEntry]:
        """Newest-first entries with the filters applied."""
        rows = [
            e for e in self._entries.values()
            if (tenant_id is None or e.tenant_id == tenant_id)
            and (kind is None or e.kind == kind)
            and (status is None or e.status == status)
            and (since is None or e.created_at >= since)
            and (before is None or e.created_at < before)
        ]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return [e.model_copy() for e in rows[offset:offset + limit]]

    async def list_transactions(self, tenant_id: str, limit: int = 100) -> list[CreditTransaction]:
        """Newest-first balance changes of one tenant."""
        rows = [t for t in self._transactions if t.tenant_id == tenant_id]
        return list(reversed(rows))[:limit]

    async def summary(self) -> list[dict[str, Any]]:
        """One row per tenant with an account or an entry."""
        tenants = set(self._balances) | {e.tenant_id for e in self._entries.values()}
        return sorted(
            (_summary_row(t, self._balances.get(t, 0), [e for e in self._entries.values() if e.tenant_id == t])
             for t in tenants),
            key=lambda r: r["tenant_id"],
        )


_ENTRY_COLUMNS = (
    "entry_id, tenant_id, run_id, kind, what, units, raw_cost_usd, actual_usd, credits, status, note, "
    "created_at, closed_at"
)


def _entry_from_row(row: tuple) -> UsageEntry:
    """Build a UsageEntry from a row selected with _ENTRY_COLUMNS."""
    keys = _ENTRY_COLUMNS.replace(" ", "").split(",")
    return UsageEntry(**dict(zip(keys, row, strict=True)))


class PostgresBillingStore:
    """BillingStore on the ``usage_entries``, ``credit_accounts`` and ``credit_transactions`` tables (migration 0006).

    A balance change and its transaction row are written in one database transaction.
    A debit is a conditional UPDATE, so concurrent holds cannot overdraw.
    """

    def __init__(self, pool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def _run(self, statements: list[tuple[str, tuple]], *, fetch: bool = True) -> list[tuple | None]:
        """Run statements in one transaction; returns each one's first row (or None)."""
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        results: list[tuple | None] = []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                for sql, params in statements:
                    await cur.execute(sql, params)
                    results.append(await cur.fetchone() if (fetch and cur.description) else None)
            await conn.commit()
        return results

    async def _all(self, sql: str, params: tuple) -> list[tuple]:
        """Run one SELECT and return every row."""
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return list(await cur.fetchall())

    async def balance(self, tenant_id: str) -> int:
        """The tenant's balance in credits."""
        rows = await self._all("SELECT balance FROM credit_accounts WHERE tenant_id = %s", (tenant_id,))
        return int(rows[0][0]) if rows else 0

    async def debit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> tuple[bool, int]:
        """Take credits unless the balance is lower — one conditional UPDATE, then the transaction row."""
        if credits <= 0:
            return True, await self.balance(tenant_id)
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE credit_accounts SET balance = balance - %s, updated_at = now() "
                    "WHERE tenant_id = %s AND balance >= %s RETURNING balance",
                    (credits, tenant_id, credits),
                )
                row = await cur.fetchone()
                if row is None:
                    # Read the balance on THIS connection: asking the pool for a second one while
                    # holding this one exhausts a small pool when several holds are refused at once.
                    await conn.rollback()
                    await cur.execute("SELECT balance FROM credit_accounts WHERE tenant_id = %s", (tenant_id,))
                    current = await cur.fetchone()
                    return False, int(current[0]) if current else 0
                await cur.execute(
                    "INSERT INTO credit_transactions (tenant_id, kind, credits, entry_id, note, actor) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (tenant_id, kind, -credits, entry_id, note, actor),
                )
            await conn.commit()
        return True, int(row[0])

    async def credit(
        self, tenant_id: str, credits: int, *, kind: TransactionKind, entry_id: str = "", note: str = "", actor: str = ""
    ) -> int:
        """Add credits (an upsert) and write the transaction row in the same transaction."""
        rows = await self._run([
            (
                "INSERT INTO credit_accounts (tenant_id, balance) VALUES (%s, %s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET balance = credit_accounts.balance + EXCLUDED.balance, "
                "updated_at = now() RETURNING balance",
                (tenant_id, credits),
            ),
            (
                "INSERT INTO credit_transactions (tenant_id, kind, credits, entry_id, note, actor) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant_id, kind, credits, entry_id, note, actor),
            ),
        ])
        return int(rows[0][0])  # type: ignore[index]

    async def grant_signup(self, tenant_id: str, credits: int) -> bool:
        """Grant once: the unique index on (tenant, 'signup') turns a repeat into a no-op."""
        if credits <= 0:
            return False
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO credit_transactions (tenant_id, kind, credits, note) "
                    "VALUES (%s, 'signup', %s, 'sign-up credits') "
                    "ON CONFLICT (tenant_id) WHERE kind = 'signup' DO NOTHING RETURNING tx_id",
                    (tenant_id, credits),
                )
                inserted = await cur.fetchone()
                if inserted is None:
                    await conn.rollback()
                    return False
                await cur.execute(
                    "INSERT INTO credit_accounts (tenant_id, balance) VALUES (%s, %s) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET balance = credit_accounts.balance + EXCLUDED.balance, "
                    "updated_at = now()",
                    (tenant_id, credits),
                )
            await conn.commit()
        return True

    async def add_entry(self, entry: UsageEntry) -> None:
        """Store a new entry."""
        await self._run([(
            f"INSERT INTO usage_entries ({_ENTRY_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            self._entry_params(entry),
        )], fetch=False)

    @staticmethod
    def _entry_params(entry: UsageEntry) -> tuple:
        """The INSERT parameters of an entry, in _ENTRY_COLUMNS order."""
        return (
            entry.entry_id, entry.tenant_id, entry.run_id, entry.kind, entry.what, entry.units,
            entry.raw_cost_usd, entry.actual_usd, entry.credits, entry.status, entry.note,
            entry.created_at, entry.closed_at,
        )

    async def update_entry(self, entry: UsageEntry) -> None:
        """Replace an entry's mutable fields."""
        await self._run([(
            "UPDATE usage_entries SET units = %s, actual_usd = %s, credits = %s, status = %s, note = %s, "
            "closed_at = %s WHERE entry_id = %s",
            (entry.units, entry.actual_usd, entry.credits, entry.status, entry.note, entry.closed_at, entry.entry_id),
        )], fetch=False)

    async def get_entry(self, entry_id: str) -> UsageEntry | None:
        """One entry, or None."""
        rows = await self._all(f"SELECT {_ENTRY_COLUMNS} FROM usage_entries WHERE entry_id = %s", (entry_id,))
        return _entry_from_row(rows[0]) if rows else None

    async def list_entries(
        self, tenant_id: str | None = None, *, kind: str | None = None, status: str | None = None,
        since: datetime | None = None, before: datetime | None = None, limit: int = 100, offset: int = 0,
    ) -> list[UsageEntry]:
        """Newest-first entries with the filters applied."""
        where, params = ["TRUE"], []
        if tenant_id is not None:
            where.append("tenant_id = %s")
            params.append(tenant_id)
        if kind is not None:
            where.append("kind = %s")
            params.append(kind)
        if status is not None:
            where.append("status = %s")
            params.append(status)
        if since is not None:
            where.append("created_at >= %s")
            params.append(since)
        if before is not None:
            where.append("created_at < %s")
            params.append(before)
        rows = await self._all(
            f"SELECT {_ENTRY_COLUMNS} FROM usage_entries WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        return [_entry_from_row(r) for r in rows]

    async def list_transactions(self, tenant_id: str, limit: int = 100) -> list[CreditTransaction]:
        """Newest-first balance changes of one tenant."""
        rows = await self._all(
            "SELECT tenant_id, kind, credits, entry_id, note, actor, created_at FROM credit_transactions "
            "WHERE tenant_id = %s ORDER BY created_at DESC, tx_id DESC LIMIT %s",
            (tenant_id, limit),
        )
        keys = ("tenant_id", "kind", "credits", "entry_id", "note", "actor", "created_at")
        return [CreditTransaction(**dict(zip(keys, r, strict=True))) for r in rows]

    async def summary(self) -> list[dict[str, Any]]:
        """One row per tenant with an account or an entry."""
        rows = await self._all(
            """
            SELECT t.tenant_id,
                   COALESCE(a.balance, 0),
                   COALESCE(SUM(e.credits) FILTER (WHERE e.status IN ('held', 'settled')), 0),
                   COALESCE(SUM(COALESCE(e.actual_usd, e.raw_cost_usd)) FILTER (WHERE e.status <> 'refunded'), 0),
                   COUNT(e.entry_id),
                   MAX(e.created_at)
              FROM (SELECT tenant_id FROM credit_accounts UNION SELECT tenant_id FROM usage_entries) t
              LEFT JOIN credit_accounts a ON a.tenant_id = t.tenant_id
              LEFT JOIN usage_entries e ON e.tenant_id = t.tenant_id
             GROUP BY t.tenant_id, a.balance
             ORDER BY t.tenant_id
            """,
            (),
        )
        return [
            {
                "tenant_id": r[0], "balance": int(r[1]), "credits_spent": int(r[2]),
                "raw_cost_usd": round(float(r[3]), 6), "actions": int(r[4]), "last_action_at": r[5],
            }
            for r in rows
        ]


_memory_store = InMemoryBillingStore()


def get_billing_store() -> BillingStore:
    """Postgres billing store when DATABASE_URL is set, else the in-memory one."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresBillingStore(pool)
    return _memory_store


def setting(settings: Any, name: str) -> Any:
    """A billing setting from settings, or its declared default when the object predates it.

    Callers that build their own settings object (tests, older call sites) may not carry
    the P-BILL-1 fields; the default is read from PlatformSettings so it is never repeated here.
    """
    return getattr(settings, name, PlatformSettings.model_fields[name].default)


def billing_enabled(settings: PlatformSettings | None = None) -> bool:
    """True when credits are charged (BILLING_ENABLED); false means the ledger only meters."""
    return bool(setting(settings or get_platform_settings(), "BILLING_ENABLED"))


def price_credits(raw_usd: float, settings: PlatformSettings | None = None) -> int:
    """The price in whole credits of an action whose provider cost is raw_usd.

    raw × CREDIT_MARKUP / CREDIT_VALUE_USD, rounded up, at least one credit for any
    non-zero cost; zero for a free action.
    """
    if raw_usd <= 0:
        return 0
    cfg = settings or get_platform_settings()
    value = setting(cfg, "CREDIT_VALUE_USD")
    if value <= 0:
        value = PlatformSettings.model_fields["CREDIT_VALUE_USD"].default
    return max(1, math.ceil(raw_usd * setting(cfg, "CREDIT_MARKUP") / value - _EPSILON))


def _as_float(value: Any) -> float:
    """value as a non-negative float; 0.0 when it is not a number (a price must never raise before the provider call)."""
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _charging_principal():
    """The signed-in principal, or None when there is none or a View-as-Basic preview is on (nothing is recorded)."""
    try:
        principal = current_principal()
    except NotAuthenticatedError:
        return None
    return None if principal.view_as_basic else principal


async def reserve(
    kind: Kind,
    usd: float,
    what: str = "this",
    *,
    run_id: str = "",
    units: float = 1.0,
    settings: PlatformSettings | None = None,
    store: BillingStore | None = None,
) -> Hold | None:
    """Price a paid action, hold its credits and bound its daily spend. Call BEFORE the provider is.

    Returns the :class:`Hold` for :func:`settle` / :func:`refund`, or None when nothing is
    recorded (no principal, or a View-as-Basic preview). Raises 402 when the balance does not
    cover the price and 429 when the daily bound is reached; in both cases nothing is held.
    """
    principal = _charging_principal()
    if principal is None:
        return None
    cfg = settings or get_platform_settings()
    ledger = store or get_billing_store()
    usd = _as_float(usd)
    entry = UsageEntry(
        tenant_id=principal.tenant_id, run_id=run_id, kind=kind, what=what, units=units, raw_cost_usd=usd,
    )
    if principal.is_owner:
        entry.status = "exempt"
        await ledger.add_entry(entry)
        return Hold(entry, charged=False)
    entry.credits = price_credits(usd, cfg)

    if not billing_enabled(cfg):
        entry.status = "metered"
        await limits.spend_gate(usd, what, cfg)
        await ledger.add_entry(entry)
        return Hold(entry, charged=False)

    if entry.credits > 0:
        ok, balance = await ledger.debit(
            principal.tenant_id, entry.credits, kind="hold", entry_id=entry.entry_id, note=what)
        if not ok:
            raise PaymentRequiredError(entry.credits, balance, what)
    try:
        await limits.spend_gate(usd, what, cfg)
    except HTTPException:
        if entry.credits > 0:
            await ledger.credit(
                principal.tenant_id, entry.credits, kind="refund", entry_id=entry.entry_id,
                note=f"{what}: daily limit reached")
        raise
    await ledger.add_entry(entry)
    return Hold(entry, charged=entry.credits > 0)


async def settle(
    hold: Hold | None, actual_usd: float | None = None, *, units: float | None = None,
    settings: PlatformSettings | None = None, store: BillingStore | None = None,
) -> None:
    """Close a hold at the actual cost (the reserved estimate when actual_usd is None).

    The credits above the actual price are returned; the platform absorbs an overrun. An
    actual cost of zero returns the whole hold and marks the entry refunded. Never raises:
    a ledger fault is logged and must not mask the action's own result.
    """
    if hold is None or not hold.recorded:
        return
    try:
        cfg = settings or get_platform_settings()
        ledger = store or get_billing_store()
        entry = await ledger.get_entry(hold.entry_id)
        if entry is None or entry.status not in ("held", "exempt", "metered"):
            return
        actual = hold.raw_usd if actual_usd is None else max(actual_usd, 0.0)
        entry.actual_usd = actual
        if units is not None:
            entry.units = units
        entry.closed_at = datetime.now(UTC)
        if entry.status == "held":
            held = entry.credits
            final = min(price_credits(actual, cfg), held)
            returned = held - final
            if returned > 0:
                await ledger.credit(
                    entry.tenant_id, returned, kind="settle", entry_id=entry.entry_id,
                    note=f"{entry.what}: settled at the actual cost")
            entry.credits = final
            entry.status = "settled" if (final > 0 or held == 0) else "refunded"
        elif entry.status == "metered":
            entry.credits = price_credits(actual, cfg)
        await ledger.update_entry(entry)
    except Exception:
        _logger.exception("billing: could not settle entry %s", getattr(hold, "entry_id", "?"))


async def refund(
    hold: Hold | None, reason: str = "", *, store: BillingStore | None = None,
) -> None:
    """Return a hold in full because the action failed. Never raises (a ledger fault is logged)."""
    if hold is None or not hold.recorded:
        return
    try:
        ledger = store or get_billing_store()
        entry = await ledger.get_entry(hold.entry_id)
        if entry is None or entry.status not in ("held", "exempt", "metered"):
            return
        if entry.status == "held" and entry.credits > 0:
            await ledger.credit(
                entry.tenant_id, entry.credits, kind="refund", entry_id=entry.entry_id,
                note=f"{entry.what}: {reason or 'failed'}")
        entry.status = "refunded"
        entry.note = reason[:500]
        entry.closed_at = datetime.now(UTC)
        await ledger.update_entry(entry)
    except Exception:
        _logger.exception("billing: could not refund entry %s", getattr(hold, "entry_id", "?"))


async def grant_signup_credits(tenant_id: str, settings: PlatformSettings | None = None, store: BillingStore | None = None) -> bool:
    """Give a new account its SIGNUP_CREDITS once (0 means none). True when credits were granted."""
    cfg = settings or get_platform_settings()
    credits = int(setting(cfg, "SIGNUP_CREDITS"))
    if credits <= 0:
        return False
    return await (store or get_billing_store()).grant_signup(tenant_id, credits)


async def topup(
    tenant_id: str, credits: int, note: str = "", actor: str = "", store: BillingStore | None = None,
) -> int:
    """Add (positive) or remove (negative) credits as the owner. Returns the new balance.

    A removal larger than the balance is refused with 409 — a balance never goes below zero.
    """
    ledger = store or get_billing_store()
    if credits == 0:
        return await ledger.balance(tenant_id)
    if credits > 0:
        return await ledger.credit(tenant_id, credits, kind="topup", note=note, actor=actor)
    ok, balance = await ledger.debit(tenant_id, -credits, kind="adjustment", note=note, actor=actor)
    if not ok:
        raise HTTPException(
            status_code=409, detail=f"That would take the balance below zero: {balance} credits left, {-credits} asked.")
    return balance


async def my_account(settings: PlatformSettings | None = None, store: BillingStore | None = None, history: int = 30) -> dict[str, Any]:
    """What the signed-in user sees: balance, whether charging is on and their recent priced actions."""
    cfg = settings or get_platform_settings()
    ledger = store or get_billing_store()
    principal = _charging_principal()
    if principal is None or principal.is_owner:
        return {"enabled": False, "balance": 0, "history": [], "exempt": principal is not None}
    entries = await ledger.list_entries(principal.tenant_id, limit=history)
    return {
        "enabled": billing_enabled(cfg),
        "exempt": False,
        "balance": await ledger.balance(principal.tenant_id),
        "history": [
            {
                "when": e.created_at, "what": e.what, "kind": e.kind, "credits": e.credits,
                "status": e.status, "run_id": e.run_id,
            }
            for e in entries
        ],
    }


async def refund_stale_holds(
    older_than_minutes: int | None = None, settings: PlatformSettings | None = None, store: BillingStore | None = None,
) -> int:
    """Refund every hold still open after BILLING_HOLD_TTL_MINUTES (or older_than_minutes). Returns how many.

    A hold is closed by the background job that took it; if the server restarted mid-job
    nothing closes it, and the user's credits would stay held for ever. The owner runs this
    from the admin view (or a scheduled call) — the job's own result is not known, so the
    safe side is to give the credits back.
    """
    cfg = settings or get_platform_settings()
    ledger = store or get_billing_store()
    minutes = older_than_minutes if older_than_minutes is not None else int(setting(cfg, "BILLING_HOLD_TTL_MINUTES"))
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    stale = await ledger.list_entries(status="held", before=cutoff, limit=1000)
    for entry in stale:
        await refund(
            Hold(entry, charged=True), f"the action never finished (held more than {minutes} minutes)", store=ledger)
    return len(stale)
