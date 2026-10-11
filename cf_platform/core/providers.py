"""Providers grouped into blocks, with a default per block (P-INT1, EPIC 58, D112).

The pipeline calls services of five kinds. A **block** is one kind — Thinking
models, Audio models, Image generation, Stock acquisition, Destination — and a
block can hold several **providers**, each with its own key (the key store of
integrations.py) and, where it makes sense, its own model. The tenant picks one
default provider per block (per role in the Audio block, whose providers do
different jobs: Gemini speaks, Deepgram transcribes).

Where a provider is used today:

- **Image generation** — kie.ai and OpenAI, both fully wired (image_provider.py).
- **Stock acquisition** — Pexels and Pixabay are searched together and ranked; the
  default only decides which one is listed first.
- **Thinking models** — Claude runs every worker. OpenAI is wired through the
  `LLMClient` adapter (llm.py) for the workers that use it (YouTube metadata
  today); the other workers stay on their pinned Claude models until they are
  moved onto the adapter. The registry says so per provider (`wired`).

This module is data and pure functions; storage of the choice is a JSON document in
the tenant settings row (`defaults["blocks"]`), so no migration is needed.
"""

from dataclasses import dataclass, field
from typing import Any

from cf_platform.core.integrations import SERVICES
from cf_platform.core.tenant_settings import TenantSettings, TenantSettingsRepository

BLOCKS_KEY = "blocks"
# Blocks whose providers are used together, not one instead of another: there is no default to choose.
_UNCHOOSABLE_BLOCKS = ("stock",)


@dataclass(frozen=True)
class Provider:
    """One provider inside a block."""

    provider_id: str
    service_id: str            # the key store entry (integrations.SERVICES)
    name: str
    block: str
    role: str = ""             # audio block: "voice" | "transcription"
    models: tuple[str, ...] = ()
    default_model: str = ""
    # What the pipeline can do with it today, shown to the operator as it is.
    wired: str = "full"        # "full" | "partial" | "planned"
    note: str = ""


@dataclass(frozen=True)
class Block:
    """One kind of service the pipeline calls."""

    block_id: str
    name: str
    description: str
    roles: tuple[str, ...] = ("",)
    providers: tuple[Provider, ...] = field(default=())


PROVIDERS: tuple[Provider, ...] = (
    Provider("anthropic", "anthropic", "Anthropic Claude", "llm",
             models=("claude-sonnet-5-5", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
             default_model="claude-haiku-4-5-20251001", wired="full",
             note="Runs every script, storyboard and metadata worker."),
    Provider("openai_llm", "openai", "OpenAI", "llm",
             models=("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"), default_model="gpt-4.1-mini", wired="partial",
             note="Used for YouTube metadata when it is the default; script and storyboard workers still run on Claude. "
                  "The same OpenAI key also serves OpenAI Images."),
    Provider("gemini", "gemini", "Google Gemini TTS", "audio", role="voice", wired="full",
             note="Generates the voiceover."),
    Provider("deepgram", "deepgram", "Deepgram", "audio", role="transcription", wired="full",
             note="Transcribes uploaded voiceovers and times the words of a generated one."),
    Provider("kie", "kie", "kie.ai", "image", wired="full"),
    Provider("openai_image", "openai", "OpenAI Images", "image", wired="full",
             note="The same OpenAI key also serves OpenAI in Thinking models."),
    Provider("pexels", "pexels", "Pexels", "stock", wired="full",
             note="Searched together with the other stock providers; results are ranked as one list."),
    Provider("pixabay", "pixabay", "Pixabay", "stock", wired="full",
             note="Searched together with the other stock providers; results are ranked as one list."),
    Provider("youtube", "youtube", "YouTube Data API", "destination", wired="planned",
             note="Publishing arrives with P16."),
)

BLOCKS: tuple[Block, ...] = tuple(
    Block(b[0], b[1], b[2], b[3], tuple(p for p in PROVIDERS if p.block == b[0]))
    for b in (
        ("llm", "Thinking models", "Write scripts, storyboards and metadata.", ("",)),
        ("audio", "Audio models", "Speak the voiceover and transcribe it.", ("voice", "transcription")),
        ("image", "Image generation", "Generate an AI image for a scene.", ("",)),
        ("stock", "Stock acquisition", "Find stock footage and images.", ("",)),
        ("destination", "Destination", "Where finished videos are published.", ("",)),
    )
)
_BLOCK_BY_ID = {b.block_id: b for b in BLOCKS}
_PROVIDER_BY_ID = {p.provider_id: p for p in PROVIDERS}
_SERVICE_ENV = {s.service_id: s.env_attr for s in SERVICES}


class UnknownProviderError(ValueError):
    """Raised for a block or provider that does not exist, or a choice the block cannot take."""


def get_block(block_id: str) -> Block:
    """The block for block_id; UnknownProviderError when there is none."""
    try:
        return _BLOCK_BY_ID[block_id]
    except KeyError:
        raise UnknownProviderError(f"Unknown block {block_id!r} — expected one of {list(_BLOCK_BY_ID)}") from None


def get_provider(provider_id: str) -> Provider:
    """The provider for provider_id; UnknownProviderError when there is none."""
    try:
        return _PROVIDER_BY_ID[provider_id]
    except KeyError:
        raise UnknownProviderError(f"Unknown provider {provider_id!r}") from None


def _stored(row: TenantSettings | None) -> dict[str, Any]:
    """The tenant's saved block choices: {block_id: {"default": {role: provider_id}, "models": {provider_id: model}}}."""
    raw = (row.defaults.get(BLOCKS_KEY) if row else None) or {}
    return raw if isinstance(raw, dict) else {}


def has_key(row: TenantSettings | None, platform_settings: Any, provider: Provider) -> tuple[bool, str | None]:
    """(a key exists, where it comes from: "tenant" | "env" | None) for the provider's service."""
    if row and row.api_keys.get(provider.service_id) and _saveable(provider.service_id):
        return True, "tenant"
    env_attr = _SERVICE_ENV.get(provider.service_id)
    if env_attr and getattr(platform_settings, env_attr, ""):
        return True, "env"
    return False, None


def _saveable(service_id: str) -> bool:
    """True when the service can hold a saved key (YouTube cannot yet)."""
    return next((s.saveable for s in SERVICES if s.service_id == service_id), False)


def default_provider(block: Block, role: str, row: TenantSettings | None, platform_settings: Any) -> Provider | None:
    """The block's default provider for a role: the saved choice, else the first with a key, else the first.

    The image block's choice lives in the tenant row's `image_provider` (the P14
    setting), so the Image card and this view can never disagree.
    """
    candidates = [p for p in block.providers if p.role == role or not role]
    if not candidates:
        return None
    if block.block_id == "image":
        wanted = (row.image_provider if row and row.image_provider else None) or getattr(platform_settings, "IMAGE_PROVIDER", "kie")
        for p in candidates:
            if (p.provider_id == "kie" and wanted == "kie") or (p.provider_id == "openai_image" and wanted == "openai"):
                return p
    saved = (_stored(row).get(block.block_id, {}).get("default") or {}).get(role or "")
    for p in candidates:
        if p.provider_id == saved and p.wired != "planned":
            return p
    for p in candidates:
        if p.wired != "planned" and has_key(row, platform_settings, p)[0]:
            return p
    return candidates[0]


def model_for(provider: Provider, row: TenantSettings | None, platform_settings: Any) -> str:
    """The model to use with the provider: the saved one, else the platform's default for it."""
    saved = (_stored(row).get(provider.block, {}).get("models") or {}).get(provider.provider_id)
    if isinstance(saved, str) and saved.strip():
        return saved.strip()
    if provider.block == "image":
        attr = "KIE_IMAGE_MODEL" if provider.provider_id == "kie" else "OPENAI_IMAGE_MODEL"
        if row and row.image_model:
            return row.image_model
        return str(getattr(platform_settings, attr, "") or "")
    if provider.provider_id == "openai_llm":
        return str(getattr(platform_settings, "OPENAI_LLM_MODEL", "") or provider.default_model)
    return provider.default_model


async def public_blocks(
    repo: TenantSettingsRepository, tenant_id: str, platform_settings: Any
) -> dict[str, Any]:
    """Every block with its providers, key state, default and model — never a key."""
    row = await repo.get(tenant_id)
    out: list[dict[str, Any]] = []
    for block in BLOCKS:
        defaults = {role: (default_provider(block, role, row, platform_settings) or Provider("", "", "", "")).provider_id
                    for role in block.roles}
        providers = []
        for p in block.providers:
            present, source = has_key(row, platform_settings, p)
            hint = ""
            if source == "tenant":
                hint = (row.api_keys.get(p.service_id) or {}).get("hint", "") if row else ""
            providers.append({
                "provider_id": p.provider_id, "service_id": p.service_id, "name": p.name, "role": p.role,
                "key_source": source, "key_hint": hint, "has_key": present,
                "can_save_key": _saveable(p.service_id),
                "is_default": block.block_id not in _UNCHOOSABLE_BLOCKS and defaults.get(p.role or "") == p.provider_id,
                "can_be_default": p.wired != "planned" and block.block_id not in _UNCHOOSABLE_BLOCKS,
                "model": model_for(p, row, platform_settings) if (p.models or p.block == "image") else "",
                "models": list(p.models), "wired": p.wired, "note": p.note,
            })
        out.append({"block_id": block.block_id, "name": block.name, "description": block.description,
                    "roles": [r for r in block.roles if r], "providers": providers})
    return {"blocks": out, "can_save_keys": bool(getattr(platform_settings, "SETTINGS_ENCRYPTION_KEY", ""))}


async def set_block_choice(
    repo: TenantSettingsRepository,
    tenant_id: str,
    platform_settings: Any,
    block_id: str,
    *,
    default: str | None = None,
    model: tuple[str, str] | None = None,
) -> TenantSettings:
    """Make `default` (a provider id) the block's default for its role, and/or save a provider's model.

    UnknownProviderError when the provider is not in the block or cannot be a
    default (planned). A choice for the image block is also written to the tenant's
    `image_provider` / `image_model`, the P14 fields the image routes already read.
    """
    block = get_block(block_id)
    row = await repo.get(tenant_id) or TenantSettings(tenant_id=tenant_id)
    blocks = dict(_stored(row))
    entry = {"default": {}, "models": {}, **blocks.get(block_id, {})}
    entry["default"], entry["models"] = dict(entry.get("default") or {}), dict(entry.get("models") or {})
    if default is not None:
        provider = get_provider(default)
        if provider.block != block_id:
            raise UnknownProviderError(f"{provider.name} is not in the {block.name} block.")
        if block_id in _UNCHOOSABLE_BLOCKS:
            raise UnknownProviderError(f"{block.name} providers are searched together — there is no single default to choose.")
        if provider.wired == "planned":
            raise UnknownProviderError(f"{provider.name} cannot be a default yet — {provider.note}")
        entry["default"][provider.role or ""] = provider.provider_id
        if block_id == "image":
            row.image_provider = "kie" if provider.provider_id == "kie" else "openai"
            row.image_model = None   # a model belongs to its provider
    if model is not None:
        provider = get_provider(model[0])
        if provider.block != block_id:
            raise UnknownProviderError(f"{provider.name} is not in the {block.name} block.")
        if not provider.models and block_id != "image":
            raise UnknownProviderError(f"{provider.name} has no model to choose.")
        clean = model[1].strip()
        if block_id == "image":
            row.image_model = clean or None
        elif clean:
            entry["models"][provider.provider_id] = clean
        else:
            entry["models"].pop(provider.provider_id, None)
    blocks[block_id] = entry
    row.defaults = {**row.defaults, BLOCKS_KEY: blocks}
    from datetime import UTC, datetime
    row.updated_at = datetime.now(UTC)
    return await repo.save(row)


async def resolve_block(
    repo: TenantSettingsRepository,
    tenant_id: str,
    platform_settings: Any,
    block_id: str,
    role: str = "",
) -> dict[str, Any]:
    """What a worker needs from a block: {provider, provider_id, service_id, model, api_key, key_source}.

    `api_key` comes from the effective platform settings (a tenant key already
    overlaid on the Railway variable), so it is '' only when no key exists anywhere.
    """
    row = await repo.get(tenant_id)
    block = get_block(block_id)
    provider = default_provider(block, role, row, platform_settings)
    if provider is None:
        raise UnknownProviderError(f"The {block.name} block has no provider for role {role!r}.")
    _, source = has_key(row, platform_settings, provider)
    env_attr = _SERVICE_ENV.get(provider.service_id, "")
    return {
        "provider": provider.name,
        "provider_id": provider.provider_id,
        "service_id": provider.service_id,
        "model": model_for(provider, row, platform_settings),
        "api_key": getattr(platform_settings, env_attr, "") if env_attr else "",
        "key_source": source,
    }
