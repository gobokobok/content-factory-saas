"""Tests for P14-S1: ImageProvider clients (kie.ai, OpenAI), secret box, tenant settings.

External APIs are replaced with httpx.MockTransport; nothing here touches a network.
"""

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet

import cf_platform.core.migrations as migrations
from cf_platform.core.image_provider import (
    ImageGenerationError,
    KieImageProvider,
    OpenAIImageProvider,
    build_image_provider,
)
from cf_platform.core.postgres_tenant_settings import PostgresTenantSettingsRepository
from cf_platform.core.secret_box import SecretBoxError, decrypt_secret, encrypt_secret, key_hint
from cf_platform.core.tenant_settings import (
    InMemoryTenantSettingsRepository,
    TenantSettings,
    public_image_settings,
    resolve_image_config,
    save_image_settings,
)

PNG = b"\x89PNG\r\n\x1a\n-fake-image-bytes"
FERNET_KEY = Fernet.generate_key().decode()


def _settings(**over) -> SimpleNamespace:
    """PlatformSettings stand-in with the image fields."""
    base = dict(
        SETTINGS_ENCRYPTION_KEY=FERNET_KEY, IMAGE_PROVIDER="kie", KIE_API_KEY="", OPENAI_API_KEY="",
        KIE_IMAGE_MODEL="gpt-image-2-text-to-image", OPENAI_IMAGE_MODEL="gpt-image-1",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _kie(handler) -> KieImageProvider:
    """A KieImageProvider whose network is `handler`, polling without delay."""
    return KieImageProvider(
        "kie-secret-key", "gpt-image-2-text-to-image", poll_interval_s=0, timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


class TestKie:
    @pytest.mark.asyncio
    async def test_happy_path_creates_polls_and_downloads(self):
        polls = {"n": 0}
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/jobs/createTask":
                seen["create"] = json.loads(request.content)
                seen["auth"] = request.headers["authorization"]
                return httpx.Response(200, json={"code": 200, "msg": "success", "data": {"taskId": "t1"}})
            if request.url.path == "/api/v1/jobs/recordInfo":
                assert request.url.params["taskId"] == "t1"
                polls["n"] += 1
                if polls["n"] < 2:
                    return httpx.Response(200, json={"code": 200, "data": {"state": "generating"}})
                result = json.dumps({"resultUrls": ["https://files.example/img.png"]})
                return httpx.Response(200, json={"code": 200, "data": {"state": "success", "resultJson": result}})
            assert request.url.host == "files.example"
            assert "authorization" not in request.headers  # the key never goes to the file host
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

        image = await _kie(handler).generate("a house", "9:16")

        assert image.data == PNG and image.ext == ".png"
        assert polls["n"] == 2
        assert seen["create"] == {
            "model": "gpt-image-2-text-to-image",
            "input": {"prompt": "a house", "aspect_ratio": "9:16", "resolution": "1K"},
        }
        assert seen["auth"] == "Bearer kie-secret-key"

    @pytest.mark.asyncio
    async def test_failed_task_reports_the_providers_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("createTask"):
                return httpx.Response(200, json={"code": 200, "data": {"taskId": "t"}})
            return httpx.Response(200, json={"code": 200, "data": {"state": "fail", "failMsg": "content policy"}})

        with pytest.raises(ImageGenerationError, match="content policy"):
            await _kie(handler).generate("x", "9:16")

    @pytest.mark.asyncio
    async def test_rejected_key_says_so_without_leaking_it(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": 401, "msg": "unauthorized"})

        with pytest.raises(ImageGenerationError) as err:
            await _kie(handler).generate("x", "9:16")
        assert "API key" in str(err.value) and "kie-secret-key" not in str(err.value)

    @pytest.mark.asyncio
    async def test_no_credits_is_its_own_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 402, "msg": "Insufficient credits"})

        with pytest.raises(ImageGenerationError, match="no credits"):
            await _kie(handler).generate("x", "9:16")

    @pytest.mark.asyncio
    async def test_a_task_that_never_finishes_times_out(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("createTask"):
                return httpx.Response(200, json={"code": 200, "data": {"taskId": "t"}})
            return httpx.Response(200, json={"code": 200, "data": {"state": "waiting"}})

        provider = KieImageProvider("k", "m", poll_interval_s=0, timeout_s=0, transport=httpx.MockTransport(handler))
        with pytest.raises(ImageGenerationError, match="too long"):
            await provider.generate("x", "9:16")

    @pytest.mark.asyncio
    async def test_success_without_a_url_is_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("createTask"):
                return httpx.Response(200, json={"code": 200, "data": {"taskId": "t"}})
            return httpx.Response(200, json={"code": 200, "data": {"state": "success", "resultJson": "{}"}})

        with pytest.raises(ImageGenerationError, match="without an image"):
            await _kie(handler).generate("x", "9:16")


class TestOpenAI:
    @pytest.mark.asyncio
    async def test_happy_path_decodes_the_base64_image(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

        provider = OpenAIImageProvider("sk-openai", "gpt-image-1", "medium", transport=httpx.MockTransport(handler))
        image = await provider.generate("a house", "9:16")

        assert image.data == PNG
        assert seen["body"]["size"] == "1024x1536" and seen["body"]["quality"] == "medium"
        assert seen["auth"] == "Bearer sk-openai"

    @pytest.mark.asyncio
    async def test_landscape_uses_a_landscape_size(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["size"] = json.loads(request.content)["size"]
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

        await OpenAIImageProvider("k", "m", transport=httpx.MockTransport(handler)).generate("x", "16:9")
        assert seen["size"] == "1536x1024"

    @pytest.mark.asyncio
    async def test_rejected_key_and_api_errors(self):
        def bad_key(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "bad key"}})

        def blocked(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "safety system"}})

        with pytest.raises(ImageGenerationError, match="API key"):
            await OpenAIImageProvider("k", "m", transport=httpx.MockTransport(bad_key)).generate("x", "9:16")
        with pytest.raises(ImageGenerationError, match="safety system"):
            await OpenAIImageProvider("k", "m", transport=httpx.MockTransport(blocked)).generate("x", "9:16")


class TestFactory:
    def test_builds_each_provider_and_rejects_unknown(self):
        assert isinstance(build_image_provider("kie", "k", "m"), KieImageProvider)
        assert isinstance(build_image_provider("openai", "k", "m"), OpenAIImageProvider)
        with pytest.raises(ValueError, match="Unknown image provider"):
            build_image_provider("midjourney", "k", "m")


class TestSecretBox:
    def test_round_trip_and_hint(self):
        token = encrypt_secret("sk-very-secret-1234", FERNET_KEY)
        assert "very-secret" not in token
        assert decrypt_secret(token, FERNET_KEY) == "sk-very-secret-1234"
        assert key_hint("sk-very-secret-1234") == "1234"
        assert key_hint("short") == ""

    def test_missing_or_wrong_key_raises(self):
        with pytest.raises(SecretBoxError, match="not set"):
            encrypt_secret("x", "")
        with pytest.raises(SecretBoxError, match="not a valid"):
            encrypt_secret("x", "not-a-fernet-key")
        token = encrypt_secret("x", FERNET_KEY)
        with pytest.raises(SecretBoxError, match="cannot be decrypted"):
            decrypt_secret(token, Fernet.generate_key().decode())


class TestTenantSettings:
    @pytest.mark.asyncio
    async def test_env_is_the_fallback_when_nothing_is_saved(self):
        repo = InMemoryTenantSettingsRepository()
        config = await resolve_image_config(repo, "operator", _settings(KIE_API_KEY="env-kie"))
        assert (config.provider, config.api_key, config.key_source) == ("kie", "env-kie", "env")
        assert config.model == "gpt-image-2-text-to-image"

    @pytest.mark.asyncio
    async def test_no_key_anywhere_resolves_to_an_empty_key(self):
        config = await resolve_image_config(InMemoryTenantSettingsRepository(), "operator", _settings())
        assert config.api_key == "" and config.key_source is None

    @pytest.mark.asyncio
    async def test_a_saved_key_beats_the_env_key_and_is_stored_encrypted(self):
        repo = InMemoryTenantSettingsRepository()
        settings = _settings(KIE_API_KEY="env-kie")
        await save_image_settings(repo, "operator", settings, provider="kie", api_key="tenant-key-9999")

        stored = await repo.get("operator")
        assert "tenant-key" not in json.dumps(stored.api_keys)
        assert stored.api_keys["kie"]["hint"] == "9999"
        config = await resolve_image_config(repo, "operator", settings)
        assert (config.api_key, config.key_source) == ("tenant-key-9999", "tenant")

    @pytest.mark.asyncio
    async def test_provider_and_model_choices_win_over_env(self):
        repo = InMemoryTenantSettingsRepository()
        settings = _settings(OPENAI_API_KEY="env-openai")
        await save_image_settings(repo, "operator", settings, provider="openai", model="gpt-image-1-mini")
        config = await resolve_image_config(repo, "operator", settings)
        assert (config.provider, config.model, config.api_key) == ("openai", "gpt-image-1-mini", "env-openai")

    @pytest.mark.asyncio
    async def test_a_key_is_saved_for_the_chosen_provider_and_can_be_cleared(self):
        repo = InMemoryTenantSettingsRepository()
        settings = _settings()
        await save_image_settings(repo, "operator", settings, provider="openai", api_key="openai-key-0001")
        assert list((await repo.get("operator")).api_keys) == ["openai"]
        await save_image_settings(repo, "operator", settings, clear_key_for="openai")
        assert (await repo.get("operator")).api_keys == {}

    @pytest.mark.asyncio
    async def test_unknown_provider_and_missing_encryption_key_are_refused(self):
        repo = InMemoryTenantSettingsRepository()
        with pytest.raises(ValueError):
            await save_image_settings(repo, "operator", _settings(), provider="nope")
        with pytest.raises(SecretBoxError):
            await save_image_settings(repo, "operator", _settings(SETTINGS_ENCRYPTION_KEY=""), api_key="abcd1234efgh")
        assert await repo.get("operator") is None  # nothing half-saved

    @pytest.mark.asyncio
    async def test_the_public_view_never_contains_a_key(self):
        repo = InMemoryTenantSettingsRepository()
        settings = _settings(OPENAI_API_KEY="env-openai")
        await save_image_settings(repo, "operator", settings, provider="kie", api_key="tenant-key-4242")
        view = await public_image_settings(repo, "operator", settings)

        assert "tenant-key" not in json.dumps(view) and "env-openai" not in json.dumps(view)
        assert view["providers"]["kie"] == {"key_source": "tenant", "key_hint": "4242"}
        assert view["providers"]["openai"] == {"key_source": "env", "key_hint": ""}
        assert view["can_save_keys"] is True

    @pytest.mark.asyncio
    async def test_a_changed_encryption_key_reports_instead_of_returning_garbage(self):
        repo = InMemoryTenantSettingsRepository()
        await save_image_settings(repo, "operator", _settings(), provider="kie", api_key="tenant-key-4242")
        with pytest.raises(SecretBoxError, match="cannot be decrypted"):
            await resolve_image_config(repo, "operator", _settings(SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode()))


class TestMigration0003:
    def test_listed_after_0002_and_idempotent(self):
        names = [p.name for p in migrations.list_migrations()]
        assert names.index("0003_tenant_settings.sql") > names.index("0002_projects_shortlist.sql")
        sql = (migrations.MIGRATIONS_DIR / "0003_tenant_settings.sql").read_text()
        assert "CREATE TABLE IF NOT EXISTS tenant_settings" in sql
        assert "tenant_id      TEXT PRIMARY KEY" in sql and "api_keys" in sql


def _mock_pool(fetchone=None):
    """MagicMock AsyncConnectionPool whose cursor returns fetchone."""
    cursor = AsyncMock()
    cursor.fetchone.return_value = fetchone
    conn = MagicMock()
    conn.cursor.return_value.__aenter__.return_value = cursor
    conn.cursor.return_value.__aexit__.return_value = None
    conn.commit = AsyncMock()
    pool = MagicMock()
    pool.closed = False
    pool.connection.return_value.__aenter__.return_value = conn
    pool.connection.return_value.__aexit__.return_value = None
    return pool, cursor


class TestPostgresRepository:
    @pytest.mark.asyncio
    async def test_get_maps_a_row_and_returns_none_when_absent(self):
        now = datetime.now(UTC)
        pool, cursor = _mock_pool(("operator", "kie", "m", {"kie": {"encrypted": "x", "hint": "1234"}}, {"language": "ru"}, now))
        row = await PostgresTenantSettingsRepository(pool).get("operator")
        assert row.image_provider == "kie" and row.api_keys["kie"]["hint"] == "1234"
        assert row.defaults == {"language": "ru"}
        assert "FROM tenant_settings WHERE tenant_id" in cursor.execute.call_args.args[0]

        pool, _ = _mock_pool(None)
        assert await PostgresTenantSettingsRepository(pool).get("nobody") is None

    @pytest.mark.asyncio
    async def test_save_upserts_by_tenant(self):
        pool, cursor = _mock_pool()
        row = TenantSettings(tenant_id="operator", image_provider="openai")
        await PostgresTenantSettingsRepository(pool).save(row)
        sql = cursor.execute.call_args.args[0]
        assert "INSERT INTO tenant_settings" in sql and "ON CONFLICT (tenant_id) DO UPDATE" in sql
