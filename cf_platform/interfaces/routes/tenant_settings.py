"""Tenant settings routes — image provider, model and API key (P14, D104).

    GET /tenant/settings/image          provider, model and key hints (never a key)
    PUT /tenant/settings/image          change provider / model, save or clear a key
    GET /tenant/integrations            every service with where its key comes from
    PUT /tenant/integrations/{service}  save or remove one service's key
    GET /tenant/blocks                  the five blocks, their providers, defaults and models
    PUT /tenant/blocks/{block}          choose a block's default provider and/or a provider's model
    GET /tenant/defaults                language, format, captions, spend cap
    PUT /tenant/defaults                change any of them

Thin wrappers over cf_platform/core/tenant_settings.py (D040).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.integrations import (
    UnknownServiceError,
    public_integrations,
    resolve_defaults,
    save_defaults,
    save_integration_key,
)
from cf_platform.core.providers import UnknownProviderError, public_blocks, set_block_choice
from cf_platform.core.secret_box import SecretBoxError
from cf_platform.core.tenant_settings import (
    TenantSettingsRepository,
    public_image_settings,
    save_image_settings,
)
from cf_platform.interfaces.dependencies import current_tenant_id, get_tenant_settings_repository

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
    return await public_image_settings(repo, current_tenant_id(), settings)


@router.put("/tenant/settings/image")
async def put_image_settings(
    body: ImageSettingsPatch,
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Save provider / model / key; 422 for an unknown provider, 409 when keys cannot be encrypted."""
    try:
        await save_image_settings(
            repo, current_tenant_id(), settings,
            provider=body.provider, model=body.model,
            api_key=body.api_key, clear_key_for=body.clear_key_for,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SecretBoxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await public_image_settings(repo, current_tenant_id(), settings)


class IntegrationPatch(BaseModel):
    """Request body for PUT /tenant/integrations/{service} — save a key or remove the saved one."""

    api_key: str | None = None
    clear_key: bool = False


@router.get("/tenant/integrations")
async def get_integrations(
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Return every service with its key source and hint (never a key)."""
    return await public_integrations(repo, current_tenant_id(), settings)


@router.put("/tenant/integrations/{service_id}")
async def put_integration(
    service_id: str,
    body: IntegrationPatch,
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Save or remove one service's key; 422 for an unknown service or empty key, 409 when keys cannot be encrypted."""
    try:
        await save_integration_key(
            repo, current_tenant_id(), settings, service_id, api_key=body.api_key, clear_key=body.clear_key
        )
    except (UnknownServiceError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SecretBoxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await public_integrations(repo, current_tenant_id(), settings)


class BlockPatch(BaseModel):
    """Request body for PUT /tenant/blocks/{block} — only supplied fields change."""

    default: str | None = None
    # A provider's model: {"provider": "openai_llm", "model": "gpt-4.1"}; an empty model resets it.
    model: dict[str, str] | None = None


@router.get("/tenant/blocks")
async def get_blocks(
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Return every block with its providers, key state, default and model (never a key)."""
    return await public_blocks(repo, current_tenant_id(), settings)


@router.put("/tenant/blocks/{block_id}")
async def put_block(
    block_id: str,
    body: BlockPatch,
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Choose the block's default provider and/or one provider's model; 422 for an unknown block or provider."""
    model = None
    if body.model is not None:
        model = (str(body.model.get("provider") or ""), str(body.model.get("model") or ""))
    try:
        await set_block_choice(repo, current_tenant_id(), settings, block_id, default=body.default, model=model)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await public_blocks(repo, current_tenant_id(), settings)


@router.get("/tenant/defaults")
async def get_defaults(
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Return the tenant's defaults over the built-in ones."""
    return await resolve_defaults(repo, current_tenant_id(), settings)


@router.put("/tenant/defaults")
async def put_defaults(
    body: dict[str, Any],
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Change any of language, format, captions, spend_cap; 422 names the first bad field."""
    try:
        await save_defaults(repo, current_tenant_id(), body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await resolve_defaults(repo, current_tenant_id(), settings)
