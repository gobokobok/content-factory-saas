"""The moderation gate and the prompt log (Sprint P-AUTH S9, D115, F13).

Every text a stranger can send to a paid model passes :func:`moderate` first: the
script (storyboard, voice), a scene's prompt (generate, write-with-the-director), the
Creator's style, characters and title. Two layers, cheapest first:

1. a **local screen** — rules for the one category that must never get through
   (sexual content involving minors) plus the operator's own blocklist;
2. an optional **provider check** — OpenAI's moderation endpoint (free) when
   ``MODERATION_PROVIDER=openai`` and a key exists. A provider outage lets the text
   through (the local screen already ran) and is logged — a moderation outage must not
   take generation down.

Each check is written to the per-tenant prompt log with its verdict, so the owner can
see what was asked and what was refused. The owner's own tenant is not blocked (the
channel's content is the owner's), only logged.

``MODERATION_MODE=log`` records and never blocks — for tuning the rules on real use.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import requests
from fastapi import HTTPException
from pydantic import BaseModel

from cf_platform.core.accounts import OWNER_TENANT_ID, NotAuthenticatedError, current_principal
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import get_pool

_logger = logging.getLogger(__name__)

Verdict = Literal["allowed", "blocked", "flagged"]

OPENAI_MODERATION_URL = "https://api.openai.com/v1/moderations"
# Provider categories that block. Others (e.g. plain "violence") only flag.
_BLOCKING_CATEGORIES = (
    "sexual/minors",
    "self-harm/instructions",
    "self-harm/intent",
    "violence/graphic",
    "harassment/threatening",
    "hate/threatening",
    "illicit/violent",
)

_MINOR = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|under-age|toddler|infant|preteen|pre-teen|teen|teens|"
    r"teenager|teenagers|schoolgirl|schoolboy|little girl|little boy|young girl|young boy|"
    r"(?:[0-9]|1[0-7])[- ]?(?:year|yr)s?[- ]?old)\b",
    re.IGNORECASE,
)
_SEXUAL = re.compile(
    r"\b(sex|sexual|sexually|nude|naked|nudity|porn|porno|pornographic|erotic|explicit|nsfw|fetish|"
    r"lingerie|topless|molest|molestation|rape|raped)\b",
    re.IGNORECASE,
)
_EXCERPT_CHARS = 500


class ModerationResult(BaseModel):
    """What the gate decided about one text."""

    verdict: Verdict = "allowed"
    reason: str = ""
    layer: str = ""


class PromptLogEntry(BaseModel):
    """One row of the per-tenant prompt log."""

    tenant_id: str
    user_id: str = ""
    run_id: str = ""
    kind: str
    excerpt: str = ""
    verdict: Verdict = "allowed"
    reason: str = ""
    created_at: datetime


class PromptLog(Protocol):
    """Storage for the prompt log."""

    async def add(self, entry: PromptLogEntry) -> None:
        """Append one entry."""
        ...

    async def recent(self, tenant_id: str | None, limit: int = 100) -> list[PromptLogEntry]:
        """The newest entries (one tenant's, or everyone's when tenant_id is None)."""
        ...


class InMemoryPromptLog:
    """In-memory PromptLog — process-local; the local-development fallback."""

    def __init__(self) -> None:
        """Start empty."""
        self._rows: list[PromptLogEntry] = []

    async def add(self, entry: PromptLogEntry) -> None:
        """Append one entry."""
        self._rows.append(entry)

    async def recent(self, tenant_id: str | None, limit: int = 100) -> list[PromptLogEntry]:
        """The newest entries, newest first."""
        rows = [r for r in self._rows if tenant_id is None or r.tenant_id == tenant_id]
        return list(reversed(rows))[:limit]


class PostgresPromptLog:
    """PromptLog on the ``prompt_log`` table (migration 0005)."""

    def __init__(self, pool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def add(self, entry: PromptLogEntry) -> None:
        """Insert one entry."""
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO prompt_log (tenant_id, user_id, run_id, kind, excerpt, verdict, reason, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (entry.tenant_id, entry.user_id, entry.run_id, entry.kind, entry.excerpt,
                     entry.verdict, entry.reason, entry.created_at),
                )
            await conn.commit()

    async def recent(self, tenant_id: str | None, limit: int = 100) -> list[PromptLogEntry]:
        """The newest entries, newest first."""
        from cf_platform.core.postgres_repos import _ensure_open

        where, params = ("WHERE tenant_id = %s ", (tenant_id, limit)) if tenant_id else ("", (limit,))
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT tenant_id, user_id, run_id, kind, excerpt, verdict, reason, created_at "
                    f"FROM prompt_log {where}ORDER BY id DESC LIMIT %s",
                    params,
                )
                rows = await cur.fetchall()
        keys = ("tenant_id", "user_id", "run_id", "kind", "excerpt", "verdict", "reason", "created_at")
        return [PromptLogEntry(**dict(zip(keys, row, strict=True))) for row in rows]


_memory_log = InMemoryPromptLog()


def get_prompt_log() -> PromptLog:
    """Postgres prompt log when DATABASE_URL is set, else the in-memory one."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresPromptLog(pool)
    return _memory_log


def local_screen(text: str, blocklist: str = "") -> ModerationResult:
    """The local rules. Blocks sexual content involving minors and the operator's own phrases."""
    lowered = text.lower()
    for phrase in (p.strip().lower() for p in blocklist.split(",")):
        if phrase and phrase in lowered:
            return ModerationResult(verdict="blocked", reason="matches a blocked phrase", layer="local")
    if _MINOR.search(text) and _SEXUAL.search(text):
        return ModerationResult(
            verdict="blocked", reason="sexual content involving minors is not allowed", layer="local"
        )
    return ModerationResult()


def interpret_provider(payload: dict[str, Any]) -> ModerationResult:
    """Map an OpenAI moderation response onto a verdict (blocking categories block, other flags flag)."""
    results = payload.get("results") or []
    if not results:
        return ModerationResult()
    first = results[0]
    categories = first.get("categories") or {}
    hit = [name for name in _BLOCKING_CATEGORIES if categories.get(name)]
    if hit:
        return ModerationResult(verdict="blocked", reason=f"provider: {', '.join(hit)}", layer="openai")
    if first.get("flagged"):
        flagged = [name for name, on in categories.items() if on]
        return ModerationResult(verdict="flagged", reason=f"provider: {', '.join(flagged)}", layer="openai")
    return ModerationResult()


def _provider_check(text: str, api_key: str, model: str, post=requests.post) -> ModerationResult:
    """Blocking call to the provider's moderation endpoint. Raises requests.RequestException / ValueError."""
    response = post(
        OPENAI_MODERATION_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "input": text},
        timeout=10,
    )
    if response.status_code != 200:
        raise ValueError(f"moderation provider answered {response.status_code}")
    return interpret_provider(response.json())


async def check_text(text: str, settings: PlatformSettings, provider_post=requests.post) -> ModerationResult:
    """Run the layers over text and return the first non-allowed result (or allowed)."""
    local = local_screen(text, settings.MODERATION_BLOCKLIST)
    if local.verdict == "blocked":
        return local
    if settings.MODERATION_PROVIDER == "openai" and settings.OPENAI_API_KEY and text.strip():
        try:
            result = await asyncio.to_thread(
                _provider_check, text[:20000], settings.OPENAI_API_KEY, settings.MODERATION_MODEL, provider_post
            )
        except Exception:  # an outage must not stop generation; the local screen already ran
            _logger.warning("moderation provider unavailable — local screen only", exc_info=True)
            return local
        if result.verdict != "allowed":
            return result
    return local


async def moderate(
    text: str,
    kind: str,
    *,
    run_id: str = "",
    settings: PlatformSettings | None = None,
    log: PromptLog | None = None,
    provider_post=requests.post,
) -> ModerationResult:
    """Gate one text: log it, and raise 422 when it is blocked (MODERATION_MODE=block, non-owner).

    ``kind`` names where the text came from (``script``, ``scene_prompt``, ``style`` …)
    for the log. Empty text is allowed without a log row.
    """
    if not text or not text.strip():
        return ModerationResult()
    cfg = settings or get_platform_settings()
    try:
        principal = current_principal()
    except NotAuthenticatedError:
        principal = None
    tenant = principal.tenant_id if principal else ""
    result = await check_text(text, cfg, provider_post)
    entry = PromptLogEntry(
        tenant_id=tenant,
        user_id=principal.user_id if principal else "",
        run_id=run_id,
        kind=kind,
        excerpt=text.strip()[:_EXCERPT_CHARS],
        verdict=result.verdict,
        reason=result.reason,
        created_at=datetime.now(UTC),
    )
    try:
        await (log or get_prompt_log()).add(entry)
    except Exception:  # losing a log row must not take the request down
        _logger.warning("prompt log write failed", exc_info=True)
    if result.verdict == "blocked" and cfg.MODERATION_MODE == "block" and tenant != OWNER_TENANT_ID:
        raise HTTPException(
            status_code=422,
            detail="This text can't be used: it goes against the terms (for example sexual content "
                   "involving minors). Change it and try again.",
        )
    return result


async def moderate_many(texts: list[str], kind: str, *, run_id: str = "") -> None:
    """moderate() each non-empty text in turn (the first block raises)."""
    for text in texts:
        await moderate(text, kind, run_id=run_id)
