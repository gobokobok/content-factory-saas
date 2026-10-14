"""Owner-only account administration and the prompt log (Sprint P-AUTH S9, D115).

    GET  /admin/users                    every account: type, tenant, last sign-in, terms, state
    POST /admin/users/{user_id}/disable  switch an account off (its sessions stop working at once)
    POST /admin/users/{user_id}/enable   switch it back on
    GET  /admin/prompt-log               what was sent to paid models, with the moderation verdict

These routes exist so the owner can act on abuse the day it appears (the terms say
access can be revoked). They are closed to everyone but the owner's tenant.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from cf_platform.core.accounts import OWNER_USER_ID, AccountStore
from cf_platform.core.moderation import PromptLog, get_prompt_log
from cf_platform.interfaces.dependencies import get_account_store
from cf_platform.interfaces.guards import require_owner

router = APIRouter(dependencies=[Depends(require_owner)])


def _public(user) -> dict[str, Any]:
    """The fields of a user the owner sees (no Google ``sub``)."""
    return {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "account_type": user.account_type,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "terms_version": user.terms_version,
        "disabled": user.disabled_at is not None,
    }


@router.get("/admin/users")
async def list_users(store: AccountStore = Depends(get_account_store)) -> list[dict[str, Any]]:
    """Every account, newest first."""
    return [_public(u) for u in await store.list_users()]


async def _set_disabled(store: AccountStore, user_id: str, disabled: bool) -> dict[str, Any]:
    """Switch an account off or on. The owner's own account cannot be switched off (404 for an unknown id)."""
    if user_id == OWNER_USER_ID and disabled:
        raise HTTPException(status_code=409, detail="The owner's account cannot be switched off.")
    user = await store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
    updated = user.model_copy(update={"disabled_at": datetime.now(UTC) if disabled else None})
    await store.save_user(updated)
    return _public(updated)


@router.post("/admin/users/{user_id}/disable")
async def disable_user(user_id: str, store: AccountStore = Depends(get_account_store)) -> dict[str, Any]:
    """Switch an account off; every session of it stops working on its next request."""
    return await _set_disabled(store, user_id, True)


@router.post("/admin/users/{user_id}/enable")
async def enable_user(user_id: str, store: AccountStore = Depends(get_account_store)) -> dict[str, Any]:
    """Switch an account back on."""
    return await _set_disabled(store, user_id, False)


@router.get("/admin/prompt-log")
async def prompt_log(
    tenant_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    log: PromptLog = Depends(get_prompt_log),
) -> list[dict[str, Any]]:
    """The newest prompt-log rows, optionally one tenant's."""
    return [row.model_dump(mode="json") for row in await log.recent(tenant_id, limit)]
