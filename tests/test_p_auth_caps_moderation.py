"""Sprint P-AUTH S8 (server caps, per-tenant spend) and S9 (moderation gate, prompt log)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from cf_platform.core import limits, moderation
from cf_platform.core.accounts import Principal, owner_principal, reset_principal, set_principal
from cf_platform.core.config import PlatformSettings
from cf_platform.core.moderation import InMemoryPromptLog, ModerationResult, local_screen, moderate
from cf_platform.core.run_manager import InMemoryRunRepository, create_run

BASE = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a"}


def cfg(**over) -> PlatformSettings:
    """A PlatformSettings with the given overrides."""
    return PlatformSettings.model_validate({**BASE, **over})


@pytest.fixture
def friend():
    """A bound (non-owner) tenant for the duration of a test; unique so shared stores never collide."""
    tenant = f"u_{uuid.uuid4().hex[:10]}"
    token = set_principal(Principal(user_id=tenant, tenant_id=tenant, account_type="basic"))
    yield tenant
    reset_principal(token)


@pytest.fixture
def owner():
    token = set_principal(owner_principal())
    yield "operator"
    reset_principal(token)


def run(coro):
    """Run a coroutine to completion."""
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ── S8 ───────────────────────────────────────────────────────────────────


class TestTextCaps:
    def test_script_over_the_word_cap_is_refused(self, friend):
        with pytest.raises(HTTPException) as exc:
            limits.check_script("word " * 11, cfg(CAP_SCRIPT_WORDS=10))
        assert exc.value.status_code == 422 and "10 words" in exc.value.detail

    def test_script_at_the_cap_passes(self, friend):
        limits.check_script("word " * 10, cfg(CAP_SCRIPT_WORDS=10))

    def test_the_owner_is_not_capped(self, owner):
        limits.check_script("word " * 5000, cfg(CAP_SCRIPT_WORDS=10))

    @pytest.mark.parametrize(
        "fn,kwargs,field",
        [
            (limits.check_prompt, {}, "CAP_PROMPT_CHARS"),
            (limits.check_style, {}, "CAP_STYLE_CHARS"),
            (limits.check_character, {}, "CAP_CHARACTER_CHARS"),
        ],
    )
    def test_other_text_caps(self, friend, fn, kwargs, field):
        with pytest.raises(HTTPException) as exc:
            fn("x" * 11, settings=cfg(**{field: 10}), **kwargs)
        assert exc.value.status_code == 422
        fn("x" * 10, settings=cfg(**{field: 10}), **kwargs)


class TestRunsPerDay:
    def test_the_cap_counts_todays_runs_of_this_tenant_only(self, friend):
        runs = InMemoryRunRepository()
        settings = cfg(CAP_RUNS_PER_DAY=2)

        async def go():
            await limits.enforce_runs_per_day(runs, settings)
            await create_run(friend, "studio", {}, runs)
            await create_run(friend, "studio", {}, runs)
            await create_run("someone-else", "studio", {}, runs)
            with pytest.raises(HTTPException) as exc:
                await limits.enforce_runs_per_day(runs, settings)
            assert exc.value.status_code == 429

        run(go())

    def test_the_owner_is_exempt(self, owner):
        runs = InMemoryRunRepository()

        async def go():
            for _ in range(3):
                await create_run("operator", "studio", {}, runs)
            await limits.enforce_runs_per_day(runs, cfg(CAP_RUNS_PER_DAY=1))

        run(go())


class TestSpendGate:
    def test_spend_is_reserved_before_the_call_and_stops_at_the_cap(self, friend):
        settings = cfg(CAP_DAILY_SPEND_USD=0.10)

        async def go():
            await limits.spend_gate(0.05, "x", settings)
            await limits.spend_gate(0.05, "x", settings)
            with pytest.raises(HTTPException) as exc:
                await limits.spend_gate(0.01, "images", settings)
            assert exc.value.status_code == 429 and "images" in exc.value.detail

        run(go())

    def test_one_batch_larger_than_the_whole_cap_is_refused_at_once(self, friend):
        with pytest.raises(HTTPException):
            run(limits.spend_gate(5.0, "x", cfg(CAP_DAILY_SPEND_USD=1.0)))

    def test_each_tenant_has_its_own_budget(self):
        settings = cfg(CAP_DAILY_SPEND_USD=0.05)

        async def go():
            for _ in range(2):
                tenant = f"u_{uuid.uuid4().hex[:10]}"
                token = set_principal(Principal(user_id=tenant, tenant_id=tenant))
                try:
                    await limits.spend_gate(0.05, "x", settings)
                finally:
                    reset_principal(token)

        run(go())

    def test_the_owner_is_not_bound(self, owner):
        run(limits.spend_gate(1000.0, "x", cfg(CAP_DAILY_SPEND_USD=0.01)))

    def test_postgres_reservation_is_one_conditional_statement(self):
        from unittest.mock import AsyncMock

        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(0.07,))
        cursor.description = [("spend_usd",)]
        conn = MagicMock()
        conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cursor)
        conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)
        conn.commit = AsyncMock()
        pool = MagicMock(closed=False)
        pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.connection.return_value.__aexit__ = AsyncMock(return_value=False)
        ok, total = run(limits.PostgresUsageStore(pool).reserve_spend("t", datetime.now(UTC).date(), 0.02, 5.0))
        sql = cursor.execute.call_args[0][0]
        assert ok is True and total == 0.07
        assert "ON CONFLICT (tenant_id, day) DO UPDATE" in sql and "<= %s" in sql and "RETURNING" in sql


class TestRenderSlots:
    def test_only_the_cap_of_renders_run_at_once_per_tenant(self, friend):
        settings = cfg(CAP_CONCURRENT_RENDERS=1)
        slot = limits.claim_render_slot(settings)
        with pytest.raises(HTTPException) as exc:
            limits.claim_render_slot(settings)
        assert exc.value.status_code == 429
        limits.release_render_slot(slot)
        limits.release_render_slot(limits.claim_render_slot(settings))

    def test_the_slot_is_per_tenant(self, friend):
        settings = cfg(CAP_CONCURRENT_RENDERS=1)
        mine = limits.claim_render_slot(settings)
        try:
            token = set_principal(Principal(user_id="u_other", tenant_id="u_other_" + friend))
            try:
                other = limits.claim_render_slot(settings)
                limits.release_render_slot(other)
            finally:
                reset_principal(token)
        finally:
            limits.release_render_slot(mine)

    def test_the_context_manager_releases_on_error(self, friend):
        settings = cfg(CAP_CONCURRENT_RENDERS=1)

        async def go():
            with pytest.raises(RuntimeError):
                async with limits.render_slot(settings):
                    raise RuntimeError("boom")
            async with limits.render_slot(settings):
                pass

        run(go())


class TestStorageQuota:
    def test_uploads_count_against_the_quota(self, friend):
        settings = cfg(CAP_STORAGE_MB=1)

        async def go():
            await limits.reserve_upload(600 * 1024, settings)
            with pytest.raises(HTTPException) as exc:
                await limits.reserve_upload(600 * 1024, settings)
            assert exc.value.status_code == 413

        run(go())


# ── S9 ───────────────────────────────────────────────────────────────────


class TestLocalScreen:
    @pytest.mark.parametrize(
        "text",
        [
            "a naked child on a beach",
            "explicit story about a 14 year old girl",
            "nsfw scene with a schoolgirl",
            "Teen erotic fiction",
        ],
    )
    def test_sexual_content_involving_minors_is_blocked(self, text):
        assert local_screen(text).verdict == "blocked"

    @pytest.mark.parametrize(
        "text",
        [
            "Why starter homes vanished for first-time buyers",
            "A child waits at the school gate while her mother signs the mortgage papers",
            "Teenagers can't afford rent in major cities",
            "A couple argues about sex education funding in the school budget debate",
            "",
        ],
    )
    def test_ordinary_text_passes(self, text):
        assert local_screen(text).verdict == "allowed"

    def test_the_owners_blocklist_applies(self):
        assert local_screen("buy crypto now", "crypto, casino").verdict == "blocked"
        assert local_screen("a house", "crypto, casino").verdict == "allowed"


class TestProviderLayer:
    def _post(self, payload, status=200):
        response = MagicMock(status_code=status)
        response.json.return_value = payload
        return MagicMock(return_value=response)

    def test_a_blocking_category_blocks(self, friend):
        post = self._post({"results": [{"flagged": True, "categories": {"sexual/minors": True}}]})
        result = run(moderation.check_text("hello", cfg(MODERATION_PROVIDER="openai", OPENAI_API_KEY="k"), post))
        assert result.verdict == "blocked" and result.layer == "openai"

    def test_a_non_blocking_flag_only_flags(self, friend):
        post = self._post({"results": [{"flagged": True, "categories": {"violence": True}}]})
        result = run(moderation.check_text("hello", cfg(MODERATION_PROVIDER="openai", OPENAI_API_KEY="k"), post))
        assert result.verdict == "flagged"

    def test_a_provider_outage_does_not_block(self, friend):
        post = MagicMock(side_effect=RuntimeError("down"))
        result = run(moderation.check_text("hello", cfg(MODERATION_PROVIDER="openai", OPENAI_API_KEY="k"), post))
        assert result.verdict == "allowed"

    def test_the_provider_is_skipped_without_a_key_or_when_local(self, friend):
        post = self._post({})
        run(moderation.check_text("hello", cfg(MODERATION_PROVIDER="openai", OPENAI_API_KEY=""), post))
        run(moderation.check_text("hello", cfg(MODERATION_PROVIDER="local", OPENAI_API_KEY="k"), post))
        post.assert_not_called()


class TestGate:
    def test_a_blocked_text_is_refused_and_logged_for_the_tenant(self, friend):
        log = InMemoryPromptLog()
        with pytest.raises(HTTPException) as exc:
            run(moderate("a naked child", "script", run_id="r1", settings=cfg(), log=log))
        assert exc.value.status_code == 422
        rows = run(log.recent(friend))
        assert len(rows) == 1 and rows[0].verdict == "blocked" and rows[0].kind == "script" and rows[0].run_id == "r1"

    def test_an_allowed_text_is_logged_and_passes(self, friend):
        log = InMemoryPromptLog()
        result = run(moderate("Rent versus buy in 2026", "script", settings=cfg(), log=log))
        assert result.verdict == "allowed"
        assert run(log.recent(friend))[0].excerpt.startswith("Rent versus buy")

    def test_the_log_is_per_tenant(self, friend):
        log = InMemoryPromptLog()
        run(moderate("one", "script", settings=cfg(), log=log))
        token = set_principal(Principal(user_id="u_x", tenant_id="u_x_" + friend))
        try:
            run(moderate("two", "script", settings=cfg(), log=log))
        finally:
            reset_principal(token)
        assert [r.excerpt for r in run(log.recent(friend))] == ["one"]
        assert len(run(log.recent(None))) == 2

    def test_log_mode_records_but_never_blocks(self, friend):
        log = InMemoryPromptLog()
        result = run(moderate("a naked child", "script", settings=cfg(MODERATION_MODE="log"), log=log))
        assert result.verdict == "blocked"
        assert run(log.recent(friend))[0].verdict == "blocked"

    def test_the_owner_is_logged_but_not_blocked(self, owner):
        log = InMemoryPromptLog()
        run(moderate("a naked child", "script", settings=cfg(), log=log))
        assert len(run(log.recent("operator"))) == 1

    def test_empty_text_is_not_checked_or_logged(self, friend):
        log = InMemoryPromptLog()
        assert run(moderate("   ", "script", settings=cfg(), log=log)) == ModerationResult()
        assert run(log.recent(None)) == []

    def test_the_excerpt_is_bounded(self, friend):
        log = InMemoryPromptLog()
        run(moderate("word " * 1000, "script", settings=cfg(), log=log))
        assert len(run(log.recent(friend))[0].excerpt) <= 500


# ── through the real app ─────────────────────────────────────────────────


class TestOnTheRoutes:
    @pytest.fixture
    def env(self, monkeypatch):
        from tests.test_p_auth_accounts import World

        monkeypatch.setenv("CAP_SCRIPT_WORDS", "20")
        monkeypatch.setenv("CAP_RUNS_PER_DAY", "2")
        world = World()
        cookie, user = run(world.sign_in("friend@example.com", "sub-" + uuid.uuid4().hex[:6]))
        yield world, cookie, user
        world.close()

    def test_a_long_script_is_refused_by_the_server(self, env):
        world, cookie, _ = env
        c = world.client(cookie)
        rid = c.post("/platform/creator/runs", json={"title": "T"}).json()["run_id"]
        for path in ("/platform/workers/voice", "/platform/workers/storyboard"):
            r = c.post(path, json={"run_id": rid, "script": "word " * 21})
            assert r.status_code == 422 and "20 words" in r.json()["detail"], path

    def test_the_third_video_of_the_day_is_refused(self, env):
        world, cookie, _ = env
        c = world.client(cookie)
        assert c.post("/platform/creator/runs", json={"title": "One"}).status_code == 201
        assert c.post("/platform/creator/runs", json={"title": "Two"}).status_code == 201
        r = c.post("/platform/creator/runs", json={"title": "Three"})
        assert r.status_code == 429

    def test_a_blocked_character_description_creates_no_run_and_is_logged(self, env):
        world, cookie, user = env
        c = world.client(cookie)
        r = c.post(
            "/platform/creator/runs",
            json={"title": "T", "characters": [{"name": "Kid", "description": "a naked child, explicit"}]},
        )
        assert r.status_code == 422
        assert run(world.runs.list_runs(user.tenant_id)) == []
        rows = run(moderation.get_prompt_log().recent(user.tenant_id))
        assert rows and rows[0].verdict == "blocked"

    def test_a_blocked_scene_prompt_is_refused_before_any_provider_call(self, env):
        world, cookie, _ = env
        c = world.client(cookie)
        rid = c.post("/platform/creator/runs", json={"title": "T"}).json()["run_id"]
        r = c.post(f"/platform/studio/runs/{rid}/scenes/1/generate", json={"prompt": "naked teen, explicit"})
        assert r.status_code == 422 and "terms" in r.json()["detail"]

    def test_run_settings_are_moderated_and_capped(self, env):
        world, cookie, _ = env
        c = world.client(cookie)
        rid = c.post("/platform/creator/runs", json={"title": "T"}).json()["run_id"]
        r = c.post(f"/runs/{rid}/settings", json={"master_style": "naked child explicit"})
        assert r.status_code == 422
