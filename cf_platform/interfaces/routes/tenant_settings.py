"""Tenant settings routes — image provider, model and API key (P14, D104).

    GET /tenant/settings/image    provider, model and key hints (never a key)
    PUT /tenant/settings/image    change provider / model, save or clear a key

Thin wrappers over cf_platform/core/tenant_settings.py (D040).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.secret_box import SecretBoxError
from cf_platform.core.tenant_settings import (
    TenantSettingsRepository,
    public_image_settings,
    save_image_settings,
)
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID, get_tenant_settings_repository

router = APIRouter()


class ImageSettingsPatch(BaseModel):
    """Request body for PUT /tenant/settings/image — only supplied fields change."""

    provider: str | None = None
    model: str | None = None
    # Saved for `provider` (or the provider already chosen). Never echoed back.
    api_key: str | None = None
    clear_key_for: str | None = None


@router.get("/tenant/settings/image")
async def get_image_settings(
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Return the tenant's image settings with key hints only."""
    return await public_image_settings(repo, PLATFORM_USER_ID, settings)


@router.put("/tenant/settings/image")
async def put_image_settings(
    body: ImageSettingsPatch,
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Save provider / model / key; 422 for an unknown provider, 409 when keys cannot be encrypted."""
    try:
        await save_image_settings(
            repo, PLATFORM_USER_ID, settings,
            provider=body.provider, model=body.model,
            api_key=body.api_key, clear_key_for=body.clear_key_for,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SecretBoxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await public_image_settings(repo, PLATFORM_USER_ID, settings)
