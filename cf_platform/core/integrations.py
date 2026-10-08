"""Tenant integrations and defaults — one place for every service key and every default.

Builds on the tenant settings row (tenant_settings.py, P14/D104). Each service the
pipeline calls has an entry in SERVICES. A key the operator saves here wins over the
Railway variable of the same service; without one the Railway variable is used, so
nothing breaks while a tenant has saved nothing. Keys are stored Fernet-encrypted
(secret_box.py) and only ever shown as a four-character hint.

`effective_platform_settings` returns a copy of the platform settings with every
saved key overlaid, so a route or worker that already reads `settings.PEXELS_API_KEY`
picks the tenant's key up by being handed the copy.

Tenant defaults (language, format, captions, AI-image spend cap) are what a project
inherits unless it sets its own; a run copies the resolved values at creation.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cf_platform.core.secret_box import SecretBoxError, decrypt_secret, encrypt_secret, key_hint
from cf_platform.core.tenant_settings import TenantSettings, TenantSettingsRepository

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Service:
    """One external service the pipeline calls."""

    service_id: str
    name: str
    use: str
    env_attr: str
    saveable: bool = True


SERVICES: tuple[Service, ...] = (
    Service("anthropic", "Anthropic Claude", "Script, storyboard and metadata", "ANTHROPIC_API_KEY"),
    Service("gemini", "Google Gemini TTS", "Generated voice", "GEMINI_API_KEY"),
    Service("deepgram", "Deepgram", "Transcribing voiceovers and word timing", "DEEPGRAM_API_KEY"),
    Service("openai", "OpenAI Images", "AI images per scene", "OPENAI_API_KEY"),
    Service("kie", "kie.ai", "AI images per scene", "KIE_API_KEY"),
    Service("pexels", "Pexels", "Stock footage and images", "PEXELS_API_KEY"),
    Service("pixabay", "Pixabay", "Stock footage and images", "PIXABAY_API_KEY"),
    Service("youtube", "YouTube Data API", "Trend research (planned)", "YOUTUBE_API_KEY", saveable=False),
)
SERVICE_IDS = tuple(s.service_id for s in SERVICES)
_BY_ID = {s.service_id: s for s in SERVICES}

# Built-in fallbacks, used when neither tenant nor project says anything.
BUILTIN_LANGUAGE = "en"
BUILTIN_FORMAT = "9:16"
BUILTIN_CAPTIONS = "standard"
FORMATS = ("9:16", "16:9")
CAPTION_CHOICES = ("standard", "punch", "none")
DEFAULT_KEYS = ("language", "format", "captions", "spend_cap")


class UnknownServiceError(ValueError):
    """Raised for a service id that is not in SERVICES or cannot hold a saved key."""


def _service(service_id: str) -> Service:
    """Return the Service for service_id; UnknownServiceError when it is not one."""
    try:
        return _BY_ID[service_id]
    except KeyError:
        raise UnknownServiceError(f"Unknown service {service_id!r} — expected one of {list(SERVICE_IDS)}") from None


def _env_value(platform_settings: Any, service: Service) -> str:
    """The Railway variable's value for the service, or ''."""
    return getattr(platform_settings, service.env_attr, "") or ""


async def resolve_service_key(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any, service_id: str
) -> str:
    """Return the key to call the service with: the tenant's saved key, else the Railway variable.

    Raises SecretBoxError when a saved key cannot be decrypted. Returns '' when no key exists.
    """
    service = _service(service_id)
    row = await repo.get(tenant_id)
    stored = (row.api_keys.get(service_id) if row else None) or None
    if stored and service.saveable:
        return decrypt_secret(stored["encrypted"], platform_settings.SETTINGS_ENCRYPTION_KEY)
    return _env_value(platform_settings, service)


async def effective_platform_settings(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> Any:
    """Return a copy of the platform settings with the tenant's saved keys overlaid.

    A key that cannot be decrypted (the encryption key changed) is skipped with a
    warning, so the Railway variable keeps working instead of the call failing.
    """
    row = await repo.get(tenant_id)
    if not row or not row.api_keys:
        return platform_settings
    overlay: dict[str, str] = {}
    for service in SERVICES:
        stored = row.api_keys.get(service.service_id)
        if not stored or not service.saveable:
            continue
        try:
            overlay[service.env_attr] = decrypt_secret(stored["encrypted"], platform_settings.SETTINGS_ENCRYPTION_KEY)
        except SecretBoxError:
            _logger.warning("Saved %s key cannot be decrypted — using the Railway variable", service.service_id)
    return platform_settings.model_copy(update=overlay) if overlay else platform_settings


async def public_integrations(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> dict[str, Any]:
    """Every service with where its key comes from — never a key, only a hint."""
    row = await repo.get(tenant_id)
    out: list[dict[str, Any]] = []
    for service in SERVICES:
        stored = (row.api_keys.get(service.service_id) if row else None) or None
        if stored and service.saveable:
            source, hint = "tenant", stored.get("hint", "")
        elif _env_value(platform_settings, service):
            source, hint = "env", ""
        else:
            source, hint = None, ""
        out.append({
            "service_id": service.service_id, "name": service.name, "use": service.use,
            "key_source": source, "key_hint": hint, "can_save": service.saveable,
        })
    return {"services": out, "can_save_keys": bool(platform_settings.SETTINGS_ENCRYPTION_KEY)}


async def save_integration_key(
    repo: TenantSettingsRepository,
    tenant_id: str,
    platform_settings: Any,
    service_id: str,
    *,
    api_key: str | None = None,
    clear_key: bool = False,
) -> TenantSettings:
    """Save or remove the tenant's key for one service.

    UnknownServiceError for an unknown or unsaveable service; SecretBoxError when
    SETTINGS_ENCRYPTION_KEY is unusable; ValueError when neither a key nor clear_key is given.
    """
    service = _service(service_id)
    if not service.saveable:
        raise UnknownServiceError(f"{service.name} cannot hold a saved key yet — it uses the Railway variable.")
    if not clear_key and not (api_key and api_key.strip()):
        raise ValueError("Paste a key to save, or choose to remove the saved one.")
    row = await repo.get(tenant_id) or TenantSettings(tenant_id=tenant_id)
    if clear_key:
        row.api_keys.pop(service_id, None)
    else:
        plain = (api_key or "").strip()
        row.api_keys[service_id] = {
            "encrypted": encrypt_secret(plain, platform_settings.SETTINGS_ENCRYPTION_KEY),
            "hint": key_hint(plain),
        }
    row.updated_at = datetime.now(UTC)
    return await repo.save(row)


# ── Defaults ──────────────────────────────────────────────────────────────


def builtin_defaults(platform_settings: Any) -> dict[str, Any]:
    """The built-in defaults: what applies when the tenant has saved nothing."""
    return {
        "language": BUILTIN_LANGUAGE,
        "format": BUILTIN_FORMAT,
        "captions": BUILTIN_CAPTIONS,
        "spend_cap": float(getattr(platform_settings, "IMAGE_RUN_SPEND_CAP_USD", 2.0)),
    }


async def resolve_defaults(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> dict[str, Any]:
    """The tenant's defaults over the built-in ones — always every key in DEFAULT_KEYS."""
    row = await repo.get(tenant_id)
    merged = builtin_defaults(platform_settings)
    for key in DEFAULT_KEYS:
        if row and row.defaults.get(key) not in (None, ""):
            merged[key] = row.defaults[key]
    return merged


def validate_defaults(patch: dict[str, Any]) -> dict[str, Any]:
    """Check a defaults patch and return it cleaned. ValueError names the first bad field."""
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULT_KEYS:
            raise ValueError(f"Unknown default {key!r} — expected one of {list(DEFAULT_KEYS)}")
        if key == "language":
            if not (isinstance(value, str) and len(value) == 2 and value.isalpha() and value.islower()):
                raise ValueError("Language must be a two-letter ISO 639-1 code, such as 'en'.")
        elif key == "format" and value not in FORMATS:
            raise ValueError(f"Format must be one of {list(FORMATS)}.")
        elif key == "captions" and value not in CAPTION_CHOICES:
            raise ValueError(f"Captions must be one of {list(CAPTION_CHOICES)}.")
        elif key == "spend_cap":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError("Spend cap must be a number of dollars.") from None
            if value < 0:
                raise ValueError("Spend cap cannot be negative.")
        clean[key] = value
    return clean


async def save_defaults(
    repo: TenantSettingsRepository, tenant_id: str, patch: dict[str, Any]
) -> TenantSettings:
    """Merge a validated defaults patch into the tenant's row. ValueError on a bad field."""
    clean = validate_defaults(patch)
    row = await repo.get(tenant_id) or TenantSettings(tenant_id=tenant_id)
    row.defaults = {**row.defaults, **clean}
    row.updated_at = datetime.now(UTC)
    return await repo.save(row)


def project_run_defaults(project_config: dict[str, Any] | None) -> dict[str, Any]:
    """The run defaults a project sets, in tenant-default vocabulary (language, format, captions).

    Projects store `config.language` and `config.run_defaults` (aspect_ratio, subtitles,
    caption_style — the keys a run's settings.json uses). Only what the project set appears.
    """
    config = project_config or {}
    out: dict[str, Any] = {}
    if config.get("language"):
        out["language"] = str(config["language"])
    rd = config.get("run_defaults") or {}
    if rd.get("aspect_ratio") in FORMATS:
        out["format"] = rd["aspect_ratio"]
    if rd.get("subtitles") == "none":
        out["captions"] = "none"
    elif rd.get("caption_style") in ("standard", "punch"):
        out["captions"] = rd["caption_style"]
    return out


def resolve_run_values(
    tenant_defaults: dict[str, Any],
    project_config: dict[str, Any] | None,
    *,
    language: str | None = None,
    aspect_ratio: str | None = None,
) -> dict[str, Any]:
    """Language and format for a new run: the run's own choice, else project, else tenant."""
    project = project_run_defaults(project_config)
    return {
        "language": language or project.get("language") or tenant_defaults["language"],
        "format": aspect_ratio or project.get("format") or tenant_defaults["format"],
    }
