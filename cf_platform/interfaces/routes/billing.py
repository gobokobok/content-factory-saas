"""Credits: what a user sees of their balance, and the owner's top-up and usage view (Sprint P-BILL-1, D123).

    GET  /billing/me                         balance, whether charging is on, prices, recent actions (own tenant only)
    GET  /admin/billing/users                every account with its balance and usage        (owner)
    POST /admin/billing/topup                add or remove credits on an account             (owner)
    GET  /admin/billing/usage                the priced action list, filterable              (owner)
    POST /admin/billing/refund-stale         give back holds whose job never finished        (owner)

The user route is open to Basic (listed in gating.py) and answers for the caller's own
tenant only — there is no tenant parameter to change. The admin routes are closed to
everyone but the owner's tenant. Routes are thin: the arithmetic is in core/billing.py.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cf_platform.core import billing
from cf_platform.core.accounts import OWNER_TENANT_ID, AccountStore, Principal
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.interfaces.dependencies import get_account_store
from cf_platform.interfaces.guards import require_owner

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_owner)])


def action_prices(settings: PlatformSettings) -> dict[str, int]:
    """The credit price of each flat-priced action, so the page can show it before the user confirms.

    Images are priced by the scene count and the model, so they come from the images plan
    (``estimated_credits``) instead.
    """
    return {
        "storyboard": billing.price_credits(billing.setting(settings, "EST_LLM_CALL_USD"), settings),
        "voice": billing.price_credits(billing.setting(settings, "EST_TTS_CALL_USD"), settings),
        "render": billing.price_credits(billing.setting(settings, "EST_RENDER_USD"), settings),
        "scene_prompt": billing.price_credits(billing.setting(settings, "EST_LLM_CALL_USD"), settings),
        "transcription": billing.price_credits(billing.setting(settings, "EST_TRANSCRIPTION_USD"), settings),
        "ideas": billing.price_credits(billing.setting(settings, "EST_IDEAS_USD"), settings),
    }


@router.get("/billing/me")
async def billing_me(
    settings: PlatformSettings = Depends(get_platform_settings),
    store: billing.BillingStore = Depends(billing.get_billing_store),
) -> dict[str, Any]:
    """The caller's balance, the flat prices and their last priced actions.

    ``enabled`` is false while BILLING_ENABLED is off (the page then shows nothing about
    credits) and for the owner, who is never charged.
    """
    account = await billing.my_account(settings, store)
    account["prices"] = action_prices(settings)
    account["credit_value_usd"] = billing.setting(settings, "CREDIT_VALUE_USD")
    return account


class TopupRequest(BaseModel):
    """POST /admin/billing/topup — exactly one of tenant_id / email names the account."""

    tenant_id: str | None = None
    email: str | None = None
    credits: int = Field(description="Credits to add; negative removes (never below zero)", ge=-1_000_000, le=1_000_000)
    note: str = Field(default="", max_length=300)


async def _tenant_for(body: TopupRequest, accounts: AccountStore) -> str:
    """Resolve the account a top-up is for; 404 when it does not exist (credits never go to a tenant nobody owns)."""
    users = await accounts.list_users()
    if body.tenant_id:
        match = next((u for u in users if u.tenant_id == body.tenant_id), None)
    elif body.email:
        match = next((u for u in users if u.email == body.email.strip().lower()), None)
    else:
        raise HTTPException(status_code=422, detail="Name the account by tenant_id or email.")
    if match is None:
        raise HTTPException(status_code=404, detail="No such account.")
    return match.tenant_id


@admin_router.get("/admin/billing/users")
async def billing_users(
    accounts: AccountStore = Depends(get_account_store),
    store: billing.BillingStore = Depends(billing.get_billing_store),
) -> list[dict[str, Any]]:
    """Every account (not the owner's) with its balance, credits spent, raw provider cost and last action."""
    summary = {row["tenant_id"]: row for row in await store.summary()}
    rows = []
    for user in await accounts.list_users():
        if user.tenant_id == OWNER_TENANT_ID:
            continue
        row = summary.get(user.tenant_id) or {
            "balance": 0, "credits_spent": 0, "raw_cost_usd": 0.0, "actions": 0, "last_action_at": None,
        }
        rows.append({
            "tenant_id": user.tenant_id,
            "email": user.email,
            "name": user.name,
            "account_type": user.account_type,
            "disabled": user.disabled_at is not None,
            **{k: row[k] for k in ("balance", "credits_spent", "raw_cost_usd", "actions", "last_action_at")},
        })
    return rows


@admin_router.post("/admin/billing/topup")
async def billing_topup(
    body: TopupRequest,
    principal: Principal = Depends(require_owner),
    accounts: AccountStore = Depends(get_account_store),
    store: billing.BillingStore = Depends(billing.get_billing_store),
) -> dict[str, Any]:
    """Add credits to (or take them from) an account and return its new balance."""
    tenant = await _tenant_for(body, accounts)
    balance = await billing.topup(tenant, body.credits, body.note, actor=principal.email or principal.user_id, store=store)
    return {"tenant_id": tenant, "balance": balance}


@admin_router.get("/admin/billing/usage")
async def billing_usage(
    tenant_id: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    store: billing.BillingStore = Depends(billing.get_billing_store),
) -> list[dict[str, Any]]:
    """The newest priced actions, optionally one tenant's, one kind's and since a time."""
    entries = await store.list_entries(tenant_id, kind=kind, since=since, limit=limit, offset=offset)
    return [e.model_dump(mode="json") for e in entries]


@admin_router.post("/admin/billing/refund-stale")
async def billing_refund_stale(
    minutes: int | None = Query(default=None, ge=1),
    settings: PlatformSettings = Depends(get_platform_settings),
    store: billing.BillingStore = Depends(billing.get_billing_store),
) -> dict[str, int]:
    """Refund holds still open after BILLING_HOLD_TTL_MINUTES (or `minutes`); returns how many were given back."""
    return {"refunded": await billing.refund_stale_holds(minutes, settings, store)}
