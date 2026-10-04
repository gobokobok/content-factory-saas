"""Tenant-level settings — image provider, model and API keys (P14, D104).

There is one tenant for now (D092), but the settings are keyed by tenant_id so a
second tenant needs no redesign. Resolution order for image generation: the
tenant's saved setting, then the Railway ENV fallback (`KIE_API_KEY`,
`OPENAI_API_KEY`, `IMAGE_PROVIDER`, `KIE_IMAGE_MODEL` / `OPENAI_IMAGE_MODEL`).
Keys are stored encrypted (cf_platform/core/secret_box.py) and only ever shown as
a four-character hint.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from cf_platform.core.image_provider import IMAGE_PROVIDERS
from cf_platform.core.secret_box import SecretBoxError, decrypt_secret, encrypt_secret, key_hint


class TenantSettings(BaseModel):
    """A tenant's saved settings row."""

    tenant_id: str
    image_provider: str | None = None
    image_model: str | None = None
    # provider -> {"encrypted": Fernet token, "hint": last four characters}
    api_keys: dict[str, dict[str, str]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TenantSettingsRepository(Protocol):
    """Persistence interface for tenant settings — in-memory or Postgres (D048)."""

    async def get(self, tenant_id: str) -> TenantSettings | None:
        """Return the tenant's settings row, or None when nothing was saved yet."""
        ...

    async def save(self, settings: TenantSettings) -> TenantSettings:
        """Insert or overwrite the row for settings.tenant_id; returns the stored row."""
        ...


class InMemoryTenantSettingsRepository:
    """Process-local fallback used when DATABASE_URL is unset (D048)."""

    def __init__(self) -> None:
        """Start with no rows."""
        self._rows: dict[str, TenantSettings] = {}

    async def get(self, tenant_id: str) -> TenantSettings | None:
        """Return a copy of the tenant's row, or None."""
        row = self._rows.get(tenant_id)
        return row.model_copy(deep=True) if row else None

    async def save(self, settings: TenantSettings) -> TenantSettings:
        """Store a copy of the row; returns it."""
        self._rows[settings.tenant_id] = settings.model_copy(deep=True)
        return settings


@dataclass
class ImageConfig:
    """What generation needs: provider, model and key, plus where the key came from."""

    provider: str
    model: str
    api_key: str
    key_source: str | None  # "tenant" | "env" | None (no key anywhere)


def _env_key(provider: str, platform_settings: Any) -> str:
    """The Railway ENV key for `provider`, or ''."""
    return getattr(platform_settings, "KIE_API_KEY" if provider == "kie" else "OPENAI_API_KEY", "") or ""


def _env_model(provider: str, platform_settings: Any) -> str:
    """The Railway ENV default model for `provider`."""
    return getattr(platform_settings, "KIE_IMAGE_MODEL" if provider == "kie" else "OPENAI_IMAGE_MODEL", "") or ""


async def resolve_image_config(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> ImageConfig:
    """Return the provider, model and key to generate with: tenant setting first, ENV second.

    Raises SecretBoxError when the tenant's stored key cannot be decrypted. A missing
    key is not an error here — api_key is '' and key_source None; the caller says so.
    """
    row = await repo.get(tenant_id)
    provider = (row.image_provider if row and row.image_provider else None) or platform_settings.IMAGE_PROVIDER
    if provider not in IMAGE_PROVIDERS:
        provider = "kie"
    model = (row.image_model if row and row.image_model else None) or _env_model(provider, platform_settings)

    stored = (row.api_keys.get(provider) if row else None) or None
    if stored:
        key = decrypt_secret(stored["encrypted"], platform_settings.SETTINGS_ENCRYPTION_KEY)
        return ImageConfig(provider, model, key, "tenant")
    env_key = _env_key(provider, platform_settings)
    return ImageConfig(provider, model, env_key, "env" if env_key else None)


async def save_image_settings(
    repo: TenantSettingsRepository,
    tenant_id: str,
    platform_settings: Any,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_key_for: str | None = None,
) -> TenantSettings:
    """Update the tenant's image settings; only the fields supplied change.

    `provider` must be one of IMAGE_PROVIDERS (ValueError otherwise). `model` of ''
    means "use the default". `api_key` is saved for `provider` (or the already-chosen
    provider) encrypted; SecretBoxError when SETTINGS_ENCRYPTION_KEY is unusable.
    `clear_key_for` deletes that provider's saved key.
    """
    row = await repo.get(tenant_id) or TenantSettings(tenant_id=tenant_id)
    if provider is not None:
        if provider not in IMAGE_PROVIDERS:
            raise ValueError(f"Unknown image provider {provider!r} — expected one of {list(IMAGE_PROVIDERS)}")
        row.image_provider = provider
    if model is not None:
        row.image_model = model.strip() or None
    if api_key is not None and api_key.strip():
        target = row.image_provider or platform_settings.IMAGE_PROVIDER
        plain = api_key.strip()
        row.api_keys[target] = {
            "encrypted": encrypt_secret(plain, platform_settings.SETTINGS_ENCRYPTION_KEY),
            "hint": key_hint(plain),
        }
    if clear_key_for:
        row.api_keys.pop(clear_key_for, None)
    row.updated_at = datetime.now(UTC)
    return await repo.save(row)


async def public_image_settings(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> dict[str, Any]:
    """The tenant's image settings as Studio may see them — never a key, only hints."""
    row = await repo.get(tenant_id)
    provider = (row.image_provider if row and row.image_provider else None) or platform_settings.IMAGE_PROVIDER
    if provider not in IMAGE_PROVIDERS:
        provider = "kie"
    providers: dict[str, dict[str, Any]] = {}
    for name in IMAGE_PROVIDERS:
        stored = (row.api_keys.get(name) if row else None) or None
        if stored:
            providers[name] = {"key_source": "tenant", "key_hint": stored.get("hint", "")}
        elif _env_key(name, platform_settings):
            providers[name] = {"key_source": "env", "key_hint": ""}
        else:
            providers[name] = {"key_source": None, "key_hint": ""}
    return {
        "provider": provider,
        "model": (row.image_model if row and row.image_model else None) or "",
        "default_models": {name: _env_model(name, platform_settings) for name in IMAGE_PROVIDERS},
        "providers": providers,
        "can_save_keys": bool(platform_settings.SETTINGS_ENCRYPTION_KEY),
    }


__all__ = [
    "ImageConfig",
    "InMemoryTenantSettingsRepository",
    "SecretBoxError",
    "TenantSettings",
    "TenantSettingsRepository",
    "public_image_settings",
    "resolve_image_config",
    "save_image_settings",
]
