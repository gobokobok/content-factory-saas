"""Invited accounts: the owner adds and removes the Google addresses that may sign in.

    GET    /admin/invites          invited addresses with whether each has signed in
    POST   /admin/invites          invite an address; switches a removed account back on
    DELETE /admin/invites/{email}  remove an invite; the account (if any) is switched off

Sign-in checks this list in addition to the ALLOWED_EMAILS variable. The owner's and Super
addresses from the variables are never listed or removed here. Owner only (guards.py).
"""

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cf_platform.core.accounts import AccountStore, Principal, parse_email_list
from cf_platform.interfaces.dependencies import get_account_store
from cf_platform.interfaces.guards import require_owner
from src.config import Settings, get_settings

admin_router = APIRouter(dependencies=[Depends(require_owner)])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteRequest(BaseModel):
    """POST /admin/invites."""

    email: str = Field(max_length=254)


def _protected(settings: Settings) -> set[str]:
    """Addresses set by variable as owner or Super: they cannot be removed from the Studio."""
    return parse_email_list(settings.OWNER_EMAILS) | parse_email_list(settings.SUPER_EMAILS)


@admin_router.get("/admin/invites")
async def list_invites(accounts: AccountStore = Depends(get_account_store)) -> list[dict[str, Any]]:
    """Invited addresses, newest first, each with whether that person has signed in yet."""
    signed_in = {u.email.lower(): u for u in await accounts.list_users() if u.email}
    rows = []
    for inv in await accounts.list_invites():
        user = signed_in.get(inv["email"])
        rows.append({
            "email": inv["email"],
            "added_at": inv["created_at"],
            "signed_in": user is not None,
            "switched_off": bool(user and user.disabled_at is not None),
        })
    return rows


@admin_router.post("/admin/invites", status_code=201)
async def add_invite(
    body: InviteRequest,
    principal: Principal = Depends(require_owner),
    accounts: AccountStore = Depends(get_account_store),
) -> dict[str, Any]:
    """Invite a Google address. An account that was switched off by a removal is switched back on."""
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(status_code=422, detail="That is not an e-mail address.")
    await accounts.add_invite(email, principal.email or "")
    for user in await accounts.list_users():
        if user.email.lower() == email and user.disabled_at is not None:
            await accounts.save_user(user.model_copy(update={"disabled_at": None}))
    return {"email": email}


@admin_router.delete("/admin/invites/{email}")
async def remove_invite(
    email: str,
    accounts: AccountStore = Depends(get_account_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Remove an invite and switch the person's account off, so they are signed out at their next request.

    Their runs and credits are kept; inviting the address again switches the account back on.
    """
    email = email.strip().lower()
    if email in _protected(settings):
        raise HTTPException(status_code=409, detail="This address is an owner or Super account set on the server.")
    existed = await accounts.remove_invite(email)
    switched_off = False
    for user in await accounts.list_users():
        if user.email.lower() == email and user.disabled_at is None and user.account_type != "super":
            await accounts.save_user(user.model_copy(update={"disabled_at": datetime.now(UTC)}))
            switched_off = True
    if not existed and not switched_off:
        raise HTTPException(status_code=404, detail="No such invite.")
    return {"email": email, "switched_off": switched_off}
