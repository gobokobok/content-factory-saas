"""Sprint P-AUTH — sign-in, sessions, tenant isolation and Basic gating (S1–S6).

These tests run the real auth middleware (the global bypass in conftest is off for
``test_p_auth*``): every request carries a real session cookie made by the store,
exactly as production does, and a missing or foreign one is refused.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.accounts import (
    InMemoryAccountStore,
    OAuthState,
    create_session,
    hash_token,
    parse_email_list,
    provision_google_user,
)
from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.gating import basic_may
from cf_platform.core.google_oauth import (
    GoogleAuthError,
    GoogleIdentity,
    code_challenge,
    identity_from_claims,
    safe_next,
)
from cf_platform.core.projects import InMemoryProjectRepository
from cf_platform.core.run_manager import InMemoryRunRepository
from cf_platform.interfaces.dependencies import (
    get_account_store,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
)
from src.auth import AUTH_COOKIE_NAME
from src.config import Settings, get_settings
from src.main import app

ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "fake-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels",
    "REPLICATE_API_TOKEN": "fake-replicate",
    "FREESOUND_API_KEY": "fake-freesound",
    "OPERATOR_PASSWORD": "correct-horse-battery",
    "SESSION_SECRET_KEY": "test-hmac-secret-value",
    "GOOGLE_OAUTH_CLIENT_ID": "client-id.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
    "GOOGLE_OAUTH_REDIRECT_URI": "https://dev.example.com/auth/google/callback",
    "OWNER_EMAILS": "owner@example.com",
    "SUPER_EMAILS": "boss@example.com",
    "ALLOWED_EMAILS": "friend@example.com, other@example.com",
    "TERMS_VERSION": "v1",
    "AUTH_SECRET_MIN_LENGTH": "1",
}


class World:
    """Fresh in-memory stores wired into the app, plus helpers to sign users in."""

    def __init__(self, **overrides) -> None:
        self.settings = Settings.model_validate({**ENV, **overrides})
        self.accounts = InMemoryAccountStore()
        self.projects = InMemoryProjectRepository("operator")
        self.runs = InMemoryRunRepository()
        self.storage = InMemoryArtifactStorage()
        app.dependency_overrides[get_settings] = lambda: self.settings
        app.dependency_overrides[get_account_store] = lambda: self.accounts
        app.dependency_overrides[get_project_repository] = lambda: self.projects
        app.dependency_overrides[get_run_repository] = lambda: self.runs
        app.dependency_overrides[get_artifact_storage] = lambda: self.storage

    def client(self, cookie: str | None = None, **kwargs) -> TestClient:
        """A client, optionally carrying a session cookie."""
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False, **kwargs)
        if cookie:
            client.cookies.set(AUTH_COOKIE_NAME, cookie)
        return client

    async def sign_in(self, email: str, sub: str, *, terms: bool = True) -> tuple[str, object]:
        """Provision the user for a Google identity and open a session. Returns (cookie, user)."""
        user = await provision_google_user(
            self.accounts, self.projects, google_sub=sub, email=email, name=email.split("@")[0],
            owner_emails=parse_email_list(self.settings.OWNER_EMAILS),
            super_emails=parse_email_list(self.settings.SUPER_EMAILS),
            project_name="My videos",
        )
        if terms:
            user = await self.accounts.save_user(user.model_copy(update={"terms_version": "v1"}))
        cookie, _ = await create_session(self.accounts, user.user_id, ttl_days=14)
        return cookie, user

    def close(self) -> None:
        """Remove the overrides."""
        for key in (get_settings, get_account_store, get_project_repository, get_run_repository, get_artifact_storage):
            app.dependency_overrides.pop(key, None)


@pytest.fixture
def world():
    w = World()
    yield w
    w.close()


def run(coro):
    """Run a coroutine to completion."""
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


def make_run(w: World, cookie: str, title: str = "Rent vs buy") -> str:
    """Create a Creator run as the cookie's user; returns its id."""
    r = w.client(cookie).post("/platform/creator/runs", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


# ── S1: sessions ─────────────────────────────────────────────────────────


class TestSessions:
    def test_no_cookie_is_refused(self, world):
        c = world.client()
        assert c.get("/platform/creator/config").status_code == 401
        page = c.get("/create", headers={"accept": "text/html"})
        assert page.status_code == 302 and page.headers["location"] == "/login"

    def test_a_garbage_or_unknown_session_cookie_is_refused(self, world):
        assert world.client("s1.not-a-real-token").get("/platform/creator/config").status_code == 401
        assert world.client("0" * 64).get("/platform/creator/config").status_code == 401

    def test_a_valid_session_is_accepted(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        assert world.client(cookie).get("/platform/creator/config").status_code == 200

    def test_an_expired_session_is_refused(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        token_hash = hash_token(cookie[3:])
        rec = run(world.accounts.get_session(token_hash))
        run(world.accounts.save_session(rec.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})))
        assert world.client(cookie).get("/platform/creator/config").status_code == 401

    def test_logout_revokes_the_session_server_side(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        c = world.client(cookie)
        assert c.get("/platform/creator/config").status_code == 200
        assert c.post("/auth/logout").status_code == 200
        # The very same cookie value, replayed, no longer works.
        assert world.client(cookie).get("/platform/creator/config").status_code == 401

    def test_a_disabled_user_loses_access(self, world):
        cookie, user = run(world.sign_in("friend@example.com", "sub-friend"))
        run(world.accounts.save_user(user.model_copy(update={"disabled_at": datetime.now(UTC)})))
        assert world.client(cookie).get("/platform/creator/config").status_code == 401

    def test_owner_password_login_makes_a_rotating_revocable_session(self, world):
        c = world.client()
        a = c.post("/auth/login", json={"password": "correct-horse-battery"}).cookies[AUTH_COOKIE_NAME]
        b = world.client().post("/auth/login", json={"password": "correct-horse-battery"}).cookies[AUTH_COOKIE_NAME]
        assert a != b and a.startswith("s1.")
        me = world.client(a).get("/auth/me").json()
        assert me["is_owner"] and me["account_type"] == "super"

    def test_the_legacy_constant_cookie_is_the_owner_only_while_accepted(self, world):
        from src.auth import sign_cookie

        legacy = sign_cookie(world.settings.SESSION_SECRET_KEY)
        assert world.client(legacy).get("/auth/me").json()["is_owner"] is True
        world.settings = world.settings.model_copy(update={"ACCEPT_LEGACY_COOKIE": False})
        assert world.client(legacy).get("/auth/me").status_code == 401


class TestOriginCheck:
    def test_a_foreign_origin_on_a_mutating_request_is_refused(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        r = world.client(cookie).post(
            "/platform/creator/runs", json={"title": "x"}, headers={"origin": "https://evil.example"}
        )
        assert r.status_code == 403

    def test_the_sites_own_origin_is_allowed(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        r = world.client(cookie).post(
            "/platform/creator/runs", json={"title": "x"}, headers={"origin": "http://testserver"}
        )
        assert r.status_code == 201

    def test_a_foreign_origin_on_a_read_is_not_blocked_by_the_origin_rule(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-friend"))
        r = world.client(cookie).get("/platform/creator/config", headers={"origin": "https://evil.example"})
        assert r.status_code == 200


# ── S1: Google OAuth ─────────────────────────────────────────────────────


class TestGoogleHelpers:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("/create", "/create"),
            ("/create?run=1", "/create?run=1"),
            ("/studio#run/abc/script", "/studio#run/abc/script"),
            ("https://evil.example/", "/"),
            ("//evil.example/x", "/"),
            ("/\\evil.example", "/"),
            ("/login", "/"),
            ("/platform/version", "/"),
            ("", "/"),
            (None, "/"),
        ],
    )
    def test_next_is_an_allow_list(self, value, expected):
        assert safe_next(value) == expected

    def test_pkce_challenge_is_s256(self):
        # RFC 7636 appendix B
        assert code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    def _claims(self, **over):
        base = {"iss": "https://accounts.google.com", "aud": "cid", "exp": 2_000_000_000, "sub": "123",
                "email": "a@b.c", "email_verified": True, "name": "A"}
        base.update(over)
        return base

    def test_valid_claims(self):
        assert identity_from_claims(self._claims(), client_id="cid", now=1.0) == GoogleIdentity("123", "a@b.c", "A")

    @pytest.mark.parametrize(
        "over",
        [{"iss": "https://evil"}, {"aud": "other"}, {"exp": 5}, {"email_verified": False}, {"sub": ""}, {"email": ""}],
    )
    def test_bad_claims_are_refused(self, over):
        with pytest.raises(GoogleAuthError):
            identity_from_claims(self._claims(**over), client_id="cid", now=1000.0)


class TestGoogleFlow:
    def test_start_redirects_to_google_with_state_pkce_and_the_configured_redirect(self, world):
        r = world.client().get("/auth/google/start?next=/create")
        assert r.status_code == 302
        url = urlparse(r.headers["location"])
        q = parse_qs(url.query)
        assert url.netloc == "accounts.google.com"
        assert q["redirect_uri"] == [world.settings.GOOGLE_OAUTH_REDIRECT_URI]
        assert q["code_challenge_method"] == ["S256"] and q["state"] and q["code_challenge"]
        stored = run(world.accounts.pop_oauth_state(hash_token(q["state"][0])))
        assert stored is not None and stored.next_path == "/create"
        assert code_challenge(stored.code_verifier) == q["code_challenge"][0]

    def test_start_ignores_the_host_header_for_the_redirect_uri(self, world):
        r = world.client().get("/auth/google/start", headers={"host": "evil.example", "x-forwarded-host": "evil.example"})
        q = parse_qs(urlparse(r.headers["location"]).query)
        assert q["redirect_uri"] == [world.settings.GOOGLE_OAUTH_REDIRECT_URI]

    def _pending(self, world, next_path="/create") -> str:
        state = "s-" + "x" * 20
        run(world.accounts.save_oauth_state(
            OAuthState(state_hash=hash_token(state), code_verifier="v" * 50, next_path=next_path,
                       created_at=datetime.now(UTC))
        ))
        return state

    def _callback(self, world, state, identity):
        with patch("cf_platform.core.google_oauth.exchange_code", return_value=identity):
            return world.client().get(f"/auth/google/callback?code=abc&state={state}")

    def test_an_invited_user_gets_a_session_a_tenant_and_a_hidden_project(self, world):
        state = self._pending(world)
        r = self._callback(world, state, GoogleIdentity("sub-friend", "Friend@Example.com", "Friend"))
        assert r.status_code == 302 and r.headers["location"] == "/create"
        cookie = r.cookies.get(AUTH_COOKIE_NAME)
        assert cookie and cookie.startswith("s1.")
        user = run(world.accounts.get_user_by_sub("sub-friend"))
        assert user.account_type == "basic" and user.tenant_id.startswith("u_") and user.tenant_id != "operator"
        project = run(world.projects.get(f"default-{user.tenant_id}"))
        assert project.tenant_id == user.tenant_id and project.config["hidden"] is True

    def test_the_state_is_single_use(self, world):
        state = self._pending(world)
        ident = GoogleIdentity("sub-friend", "friend@example.com", "F")
        assert self._callback(world, state, ident).headers["location"] == "/create"
        again = self._callback(world, state, ident)
        assert again.headers["location"].startswith("/login?error=expired")

    def test_an_unknown_state_is_refused(self, world):
        r = self._callback(world, "never-issued", GoogleIdentity("s", "friend@example.com", "F"))
        assert r.headers["location"].startswith("/login?error=expired")

    def test_a_stranger_is_not_let_in_while_signup_is_closed(self, world):
        state = self._pending(world)
        r = self._callback(world, state, GoogleIdentity("sub-x", "stranger@example.com", "S"))
        assert r.headers["location"].startswith("/login?error=not_invited")
        assert run(world.accounts.get_user_by_sub("sub-x")) is None

    def test_a_stranger_is_let_in_once_signup_is_open(self):
        w = World(SIGNUP_OPEN="true")
        try:
            r = self._callback(w, self._pending(w), GoogleIdentity("sub-x", "stranger@example.com", "S"))
            assert r.headers["location"] == "/create"
        finally:
            w.close()

    def test_the_owner_maps_onto_the_legacy_tenant_and_is_super(self, world):
        r = self._callback(world, self._pending(world, "/"), GoogleIdentity("sub-owner", "owner@example.com", "O"))
        assert r.headers["location"] == "/"
        user = run(world.accounts.get_user_by_sub("sub-owner"))
        assert user.tenant_id == "operator" and user.account_type == "super"

    def test_users_are_keyed_by_sub_so_a_changed_email_is_the_same_account(self, world):
        self._callback(world, self._pending(world), GoogleIdentity("sub-friend", "friend@example.com", "F"))
        first = run(world.accounts.get_user_by_sub("sub-friend"))
        self._callback(world, self._pending(world), GoogleIdentity("sub-friend", "other@example.com", "F"))
        second = run(world.accounts.get_user_by_sub("sub-friend"))
        assert first.user_id == second.user_id and second.email == "other@example.com"

    def test_the_open_redirect_in_next_is_neutralised(self, world):
        r = self._callback(world, self._pending(world, "https://evil.example"), GoogleIdentity("s", "friend@example.com", "F"))
        assert r.headers["location"] == "/create"

    def test_a_failed_exchange_goes_back_to_login(self, world):
        with patch("cf_platform.core.google_oauth.exchange_code", side_effect=GoogleAuthError("x")):
            r = world.client().get(f"/auth/google/callback?code=abc&state={self._pending(world)}")
        assert r.headers["location"].startswith("/login?error=google_failed")

    def test_google_off_when_not_configured(self):
        w = World(GOOGLE_OAUTH_CLIENT_ID="")
        try:
            assert w.client().get("/auth/google/start").headers["location"].startswith("/login?error=google_off")
            assert w.client().get("/auth/providers").json()["google"] is False
        finally:
            w.close()


# ── S3 / S5: isolation ───────────────────────────────────────────────────


class TestIsolation:
    @pytest.fixture
    def two(self, world):
        a, ua = run(world.sign_in("friend@example.com", "sub-a"))
        b, ub = run(world.sign_in("other@example.com", "sub-b"))
        return world, a, b, ua, ub

    def test_each_user_has_their_own_tenant(self, two):
        _, _, _, ua, ub = two
        assert ua.tenant_id != ub.tenant_id

    def test_user_b_cannot_read_user_as_run(self, two):
        w, a, b, _, _ = two
        rid = make_run(w, a)
        for path in (
            f"/platform/studio/runs/{rid}/script",
            f"/platform/studio/runs/{rid}/storyboard",
            f"/platform/studio/runs/{rid}/voice",
            f"/platform/studio/runs/{rid}/video",
            f"/platform/studio/runs/{rid}/render/status",
            f"/platform/studio/runs/{rid}/context",
            f"/runs/{rid}/settings",
        ):
            assert w.client(b).get(path).status_code == 404, path
        # The owner of the run sees it (the 404 above is ownership, not a missing route).
        assert w.client(a).get(f"/runs/{rid}/settings").status_code == 200

    def test_user_b_cannot_write_user_as_run(self, two):
        w, a, b, _, _ = two
        rid = make_run(w, a)
        c = w.client(b)
        assert c.post(f"/runs/{rid}/settings", json={"aspect_ratio": "16:9"}).status_code == 404
        assert c.delete(f"/runs/{rid}").status_code in (403, 404)
        assert c.post("/platform/workers/voice", json={"run_id": rid, "script": "hello world"}).status_code == 404
        assert c.post("/platform/workers/storyboard", json={"run_id": rid, "script": "hello world"}).status_code == 404
        assert c.post("/platform/workers/render", json={"run_id": rid}).status_code == 404
        assert c.patch(f"/platform/studio/runs/{rid}/storyboard/scenes/1", json={"voiceover_line": "x"}).status_code == 404
        assert c.post(f"/platform/studio/runs/{rid}/images/generate", json={}).status_code == 404

    def test_a_super_user_cannot_delete_or_archive_another_tenants_run(self, world):
        friend, uf = run(world.sign_in("friend@example.com", "sub-a"))
        boss, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        rid = make_run(world, friend)
        c = world.client(boss)
        assert c.delete(f"/runs/{rid}").status_code == 404
        assert c.delete(f"/platform/projects/default-{uf.tenant_id}/runs/{rid}").status_code == 404
        assert c.get(f"/platform/runs/{rid}").status_code == 404
        assert c.post(f"/platform/runs/{rid}/resume", json={"decision": "approve"}).status_code == 404
        assert c.get(f"/platform/studio/runs/{rid}/providers").status_code == 404
        assert run(world.runs.get(rid)).archived_at is None

    def test_the_other_users_run_is_indistinguishable_from_a_missing_one(self, two):
        w, a, b, _, _ = two
        rid = make_run(w, a)
        mine = w.client(b).get(f"/platform/studio/runs/{rid}/script")
        gone = w.client(b).get("/platform/studio/runs/00000000-0000-0000-0000-000000000000/script")
        assert mine.status_code == gone.status_code == 404

    def test_user_b_cannot_list_or_import_user_as_projects_runs(self, two):
        w, a, b, ua, _ = two
        rid = make_run(w, a)
        pid = f"default-{ua.tenant_id}"
        assert w.client(a).get(f"/platform/projects/{pid}/runs").json()[0]["run_id"] == rid
        assert w.client(b).get(f"/platform/projects/{pid}/runs").status_code == 404

    def test_a_users_creator_config_is_their_own_project(self, two):
        w, a, b, ua, ub = two
        assert w.client(a).get("/platform/creator/config").json()["project_id"] == f"default-{ua.tenant_id}"
        assert w.client(b).get("/platform/creator/config").json()["project_id"] == f"default-{ub.tenant_id}"

    def test_run_lists_are_per_tenant(self, two):
        w, a, b, ua, ub = two
        ra, rb = make_run(w, a), make_run(w, b, "Mine")
        la = w.client(a).get(f"/platform/projects/default-{ua.tenant_id}/runs").json()
        lb = w.client(b).get(f"/platform/projects/default-{ub.tenant_id}/runs").json()
        assert [r["run_id"] for r in la] == [ra] and [r["run_id"] for r in lb] == [rb]

    def test_a_project_is_not_visible_to_another_tenant(self, world):
        sup, usup = run(world.sign_in("boss@example.com", "sub-boss"))
        other, _ = run(world.sign_in("friend@example.com", "sub-a"))
        pid = world.client(sup).post("/platform/projects", json={"name": "Secret"}).json()["project_id"]
        assert world.client(sup).get(f"/platform/projects/{pid}").status_code == 200
        assert world.client(other).get(f"/platform/projects/{pid}").status_code in (403, 404)
        # And a second Super user does not see it in their list or in theirs library.
        boss2, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        names = [p["name"] for p in world.client(boss2).get("/platform/projects").json()]
        assert "Secret" not in names

    def test_a_run_created_by_user_a_is_not_in_user_bs_library(self, world):
        sup1, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        rid = make_run(world, sup1, "Boss video")
        items = world.client(owner).get("/platform/library/videos").json()["items"]
        assert all(rid not in str(i) for i in items)

    def test_importing_a_run_id_another_tenant_owns_claims_nothing(self, world):
        sup, usup = run(world.sign_in("boss@example.com", "sub-boss"))
        owner, uowner = run(world.sign_in("owner@example.com", "sub-owner"))
        rid = make_run(world, sup)
        # The owner's tenant "operator" has the legacy default project.
        r = world.client(owner).post(
            "/platform/projects/default/runs/import", json={"runs": [{"id": rid, "name": "stolen", "ts": 0}]}
        )
        assert r.status_code == 200 and r.json()["imported"] == 0
        assert run(world.runs.get(rid)).tenant_id == usup.tenant_id

    def test_the_owner_keeps_runs_that_were_never_registered(self, world):
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        friend, _ = run(world.sign_in("friend@example.com", "sub-a"))
        legacy_id = "2025-01-01_old-run"
        # No row exists for this id (pre-P12). The owner may use it; a Basic user may not.
        assert world.client(owner).get(f"/runs/{legacy_id}/settings").status_code == 200
        assert world.client(friend).get(f"/runs/{legacy_id}/settings").status_code == 404


# ── S4 / S6: account type and gating ─────────────────────────────────────


class TestBasicGating:
    def test_basic_reaches_the_creator_and_not_the_studio(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        c = world.client(cookie)
        assert c.get("/create", headers={"accept": "text/html"}).status_code == 200
        for page in ("/", "/studio", "/project", "/library", "/settings"):
            r = c.get(page, headers={"accept": "text/html"})
            assert r.status_code == 302 and r.headers["location"] == "/create", page

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/platform/version"),
            ("GET", "/platform/health"),
            ("POST", "/platform/echo"),
            ("POST", "/platform/pipeline/produce"),
            ("POST", "/platform/blocks/niche-to-ideas"),
            ("POST", "/platform/blocks/idea-to-script"),
            ("GET", "/platform/tenant/integrations"),
            ("PUT", "/platform/tenant/integrations/pexels"),
            ("GET", "/platform/tenant/defaults"),
            ("GET", "/platform/library/videos"),
            ("GET", "/platform/projects"),
            ("POST", "/platform/projects"),
            ("GET", "/platform/runs"),
            ("POST", "/platform/workers/acquisition"),
            ("POST", "/platform/workers/metadata"),
            ("GET", "/platform/studio/sfx-library"),
            ("GET", "/prototype/"),
        ],
    )
    def test_basic_is_refused_on_everything_it_does_not_have(self, world, method, path):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        r = world.client(cookie).request(method, path, json={} if method != "GET" else None)
        assert r.status_code == 403, (path, r.status_code)

    def test_super_reaches_the_studio_routes(self, world):
        cookie, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        c = world.client(cookie)
        assert c.get("/platform/projects").status_code == 200
        assert c.get("/platform/tenant/defaults").status_code == 200
        assert c.get("/platform/version").status_code == 200

    def test_every_route_not_on_the_basic_list_is_closed_to_basic(self, world):
        """Deny by default: walk the whole app; anything not allowed answers 403 to a Basic session."""
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        c = world.client(cookie)
        checked = 0
        exempt = {"/health", "/login", "/terms", "/auth/login", "/auth/logout", "/auth/providers",
                  "/auth/google/start", "/auth/google/callback", "/platform/telegram/webhook"}
        import re

        for path, ops in app.openapi()["paths"].items():
            concrete = re.sub(r"\{[^}]+\}", "x", path)
            if concrete in exempt:
                continue
            for method in ops:
                verb = method.upper()
                if basic_may(verb, concrete):
                    continue
                r = c.request(verb, concrete, json={})
                assert r.status_code in (302, 403), (verb, concrete, r.status_code)
                checked += 1
        assert checked > 60

    def test_the_basic_allow_list_is_what_the_creator_needs(self):
        """A snapshot: opening a route to Basic must be a deliberate edit of this list."""
        allowed = [
            ("GET", "/create"),
            ("GET", "/platform/creator/config"),
            ("POST", "/platform/creator/runs"),
            ("GET", "/platform/projects/p/runs"),
            ("POST", "/platform/workers/voice"),
            ("POST", "/platform/workers/storyboard"),
            ("POST", "/platform/workers/render"),
            ("GET", "/platform/studio/runs/r/video"),
            ("POST", "/platform/studio/runs/r/images/generate"),
            ("GET", "/runs/r/settings"),
            ("POST", "/runs/r/settings"),
        ]
        assert all(basic_may(m, p) for m, p in allowed)
        refused = [
            ("DELETE", "/runs/r"),
            ("GET", "/platform/version"),
            ("POST", "/platform/workers/acquisition"),
            ("PUT", "/platform/tenant/integrations/pexels"),
            ("POST", "/platform/projects"),
            ("GET", "/studio"),
            ("GET", "/platform/library/ai"),
        ]
        assert not any(basic_may(m, p) for m, p in refused)


class TestViewAs:
    def test_a_super_account_can_view_as_basic_and_back(self, world):
        cookie, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        c = world.client(cookie)
        assert c.get("/platform/version").status_code == 200
        assert c.post("/auth/view-as", json={"basic": True}).json()["view_as_basic"] is True
        assert c.get("/platform/version").status_code == 403
        me = c.get("/auth/me").json()
        assert me["account_type"] == "super" and me["effective_type"] == "basic"
        assert c.post("/auth/view-as", json={"basic": False}).status_code == 200
        assert c.get("/platform/version").status_code == 200

    def test_view_as_changes_only_that_session(self, world):
        cookie, user = run(world.sign_in("boss@example.com", "sub-boss"))
        other, _ = run(create_session(world.accounts, user.user_id, ttl_days=14))
        world.client(cookie).post("/auth/view-as", json={"basic": True})
        assert world.client(other).get("/platform/version").status_code == 200

    def test_a_basic_account_cannot_use_view_as(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        assert world.client(cookie).post("/auth/view-as", json={"basic": False}).status_code == 403

    def test_super_account_type_cannot_be_self_assigned(self, world):
        cookie, user = run(world.sign_in("friend@example.com", "sub-a"))
        assert user.account_type == "basic"
        assert world.client(cookie).post("/auth/view-as", json={"basic": True}).status_code == 403

    def test_the_account_type_follows_the_lists_at_every_sign_in(self, world):
        run(world.sign_in("boss@example.com", "sub-boss"))
        world.settings = world.settings.model_copy(update={"SUPER_EMAILS": ""})
        _, demoted = run(world.sign_in("boss@example.com", "sub-boss"))
        assert demoted.account_type == "basic"


# ── S6: fail closed ──────────────────────────────────────────────────────


class TestFailClosed:
    def test_repositories_refuse_to_use_process_memory_on_a_server(self, monkeypatch):
        from fastapi import HTTPException

        from cf_platform.core.config import PlatformSettings
        from cf_platform.interfaces import dependencies

        monkeypatch.setattr(dependencies, "get_platform_settings", lambda: PlatformSettings.model_validate(
            {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "a", "R2_BUCKET_NAME": "a",
             "DATABASE_URL": "", "ALLOW_IN_MEMORY_STORE": False}))
        for getter in (dependencies.get_run_repository, dependencies.get_project_repository,
                       dependencies.get_account_store, dependencies.get_tenant_settings_repository):
            with pytest.raises(HTTPException) as exc:
                getter()
            assert exc.value.status_code == 503

    def test_no_principal_means_no_tenant(self, monkeypatch):
        from contextvars import ContextVar

        from cf_platform.core import accounts

        monkeypatch.setattr(accounts, "_principal_var", ContextVar("p", default=None))
        with pytest.raises(accounts.NotAuthenticatedError):
            accounts.current_tenant_id()

    def test_telegram_is_unmounted_unless_enabled(self):
        import importlib
        import os

        import cf_platform.interfaces.api as api

        old = os.environ.pop("TELEGRAM_ROUTES_ENABLED", None)
        try:
            reloaded = importlib.reload(api)
            assert not any("/telegram" in getattr(r, "path", "") for r in reloaded.router.routes)
        finally:
            if old is not None:
                os.environ["TELEGRAM_ROUTES_ENABLED"] = old
            importlib.reload(api)


# ── S9 hook: terms ───────────────────────────────────────────────────────


class TestTerms:
    def test_a_user_who_has_not_accepted_is_sent_to_the_terms(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a", terms=False))
        c = world.client(cookie)
        assert c.get("/create", headers={"accept": "text/html"}).headers["location"] == "/terms"
        r = c.get("/platform/creator/config")
        assert r.status_code == 403 and r.json()["detail"] == "terms_required"
        assert c.get("/terms", headers={"accept": "text/html"}).status_code == 200

    def test_accepting_opens_the_product(self, world):
        cookie, user = run(world.sign_in("friend@example.com", "sub-a", terms=False))
        c = world.client(cookie)
        assert c.post("/auth/terms/accept").status_code == 200
        assert c.get("/platform/creator/config").status_code == 200
        assert run(world.accounts.get_user(user.user_id)).terms_version == "v1"

    def test_the_owner_is_not_asked(self, world):
        r = world.client().post("/auth/login", json={"password": "correct-horse-battery"})
        c = world.client(r.cookies[AUTH_COOKIE_NAME])
        assert c.get("/platform/creator/config").status_code == 200


# ── S9 / S7: owner administration, the Super menu ────────────────────────


class TestAdmin:
    def test_only_the_owner_reaches_admin_routes(self, world):
        sup, _ = run(world.sign_in("boss@example.com", "sub-boss"))      # Super, own tenant
        friend, _ = run(world.sign_in("friend@example.com", "sub-a"))    # Basic
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))  # owner tenant
        assert world.client(friend).get("/platform/admin/users").status_code == 403
        assert world.client(sup).get("/platform/admin/users").status_code == 403
        assert world.client(owner).get("/platform/admin/users").status_code == 200

    def test_disabling_an_account_ends_its_sessions_at_once(self, world):
        friend, user = run(world.sign_in("friend@example.com", "sub-a"))
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        assert world.client(friend).get("/platform/creator/config").status_code == 200
        r = world.client(owner).post(f"/platform/admin/users/{user.user_id}/disable")
        assert r.status_code == 200 and r.json()["disabled"] is True
        assert world.client(friend).get("/platform/creator/config").status_code == 401
        world.client(owner).post(f"/platform/admin/users/{user.user_id}/enable")
        assert world.client(friend).get("/platform/creator/config").status_code == 200

    def test_the_owner_account_cannot_be_disabled(self, world):
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        assert world.client(owner).post("/platform/admin/users/operator/disable").status_code == 409

    def test_the_owner_reads_the_prompt_log(self, world):
        friend, user = run(world.sign_in("friend@example.com", "sub-a"))
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        world.client(friend).post("/platform/creator/runs", json={"title": "Rent versus buy"})
        rows = world.client(owner).get(f"/platform/admin/prompt-log?tenant_id={user.tenant_id}").json()
        assert rows and rows[0]["tenant_id"] == user.tenant_id and rows[0]["kind"] == "creator_run"


class TestSuperMenuPage:
    def test_a_basic_page_does_not_contain_supers_menu_and_the_script_is_mounted_on_demand(self):
        from pathlib import Path

        html = Path("src/static/creator.html").read_text()
        js = Path("src/static/ui/creator.js").read_text()
        menu = Path("src/static/ui/super-menu.js").read_text()
        for needle in ("Integrations", "Defaults", "Libraries", "BG music"):
            assert needle not in html and needle not in js
            assert needle in menu
        assert "/ui/super-menu.js" in js and "me.effective_type === 'super'" in js
        assert "/auth/me" in js and "/auth/view-as" in js

    def test_the_menu_script_is_served(self, world):
        cookie, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        r = world.client(cookie).get("/ui/super-menu.js")
        assert r.status_code == 200 and "SuperMenu" in r.text


class TestBasicCanUseTheCreator:
    """Every call creator.js makes must be open to a Basic session (a 403 here breaks the product)."""

    def test_every_creator_call_is_allowed_for_basic(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        c = world.client(cookie)
        rid = make_run(world, cookie)
        base = f"/platform/studio/runs/{rid}"
        calls = [
            ("GET", "/platform/creator/config"), ("GET", f"{base}/context"), ("GET", f"/runs/{rid}/settings"),
            ("POST", f"/runs/{rid}/settings"), ("GET", f"{base}/script"), ("GET", f"{base}/voice"),
            ("GET", f"{base}/voice/status"), ("GET", f"{base}/storyboard"), ("GET", f"{base}/storyboard/status"),
            ("GET", f"{base}/manifest"), ("GET", f"{base}/video"), ("GET", f"{base}/images/status"),
            ("GET", f"{base}/images/plan"), ("GET", f"{base}/render/status"), ("GET", f"{base}/ai-spend"),
            ("POST", f"{base}/images/generate"), ("POST", f"{base}/scenes/1/generate"),
            ("PATCH", f"{base}/storyboard/scenes/1"), ("POST", f"{base}/storyboard/scenes/1/write-prompt"),
            ("POST", f"{base}/storyboard/scenes/1/split"), ("POST", f"{base}/storyboard/scenes/1/merge"),
            ("PUT", f"{base}/storyboard/boundaries"), ("POST", f"{base}/storyboard/continuity"),
            ("PATCH", f"{base}/storyboard/continuity/e1"), ("DELETE", f"{base}/storyboard/continuity/e1"),
            ("POST", "/platform/workers/voice"), ("POST", "/platform/workers/storyboard"),
            ("POST", "/platform/workers/render"), ("GET", "/auth/me"),
        ]
        for method, path in calls:
            r = c.request(method, path, json={"run_id": rid} if method != "GET" else None)
            assert r.status_code != 403, (method, path, r.text)
            assert r.status_code != 401, (method, path)


class TestEmptyVariables:
    def test_an_empty_variable_means_not_set(self, monkeypatch):
        """DEV crashed at start-up on SIGNUP_OPEN="" (an empty Railway variable)."""
        from src.config import Settings

        monkeypatch.setenv("SIGNUP_OPEN", "")
        monkeypatch.setenv("SESSION_TTL_DAYS", "")
        monkeypatch.setenv("ALLOW_IN_MEMORY_STORE", "")
        settings = Settings()
        assert settings.SIGNUP_OPEN is False and settings.SESSION_TTL_DAYS == 14


class TestCreatorConfigByAccount:
    def test_script_limit_follows_the_account_type(self, world):
        friend, _ = run(world.sign_in("friend@example.com", "sub-a"))
        boss, _ = run(world.sign_in("boss@example.com", "sub-boss"))
        owner, _ = run(world.sign_in("owner@example.com", "sub-owner"))
        assert world.client(friend).get("/platform/creator/config").json()["script_max_words"] == 450
        assert world.client(boss).get("/platform/creator/config").json()["script_max_words"] == 1200
        assert world.client(owner).get("/platform/creator/config").json()["script_max_words"] == 20000

    def test_realistic_and_a_chosen_project_need_super(self, world):
        friend, uf = run(world.sign_in("friend@example.com", "sub-a"))
        boss, ub = run(world.sign_in("boss@example.com", "sub-boss"))
        c = world.client(friend)
        assert c.post("/platform/creator/runs", json={"title": "T", "look": "realistic"}).status_code == 403
        assert c.post("/platform/creator/runs", json={"title": "T", "project_id": "default"}).status_code == 403
        b = world.client(boss)
        r = b.post("/platform/creator/runs", json={"title": "T", "look": "realistic"})
        assert r.status_code == 201
        stored = run(world.storage.get_json(f"runs/{r.json()['run_id']}/settings.json"))
        assert stored["visual_mode"] == "stock" and stored["look"] == "realistic"
        # A Super user's project choice is still scoped to their own tenant.
        pid = b.post("/platform/projects", json={"name": "Mine"}).json()["project_id"]
        assert b.post("/platform/creator/runs", json={"title": "T", "project_id": pid}).status_code == 201
        foreign = f"default-{uf.tenant_id}"
        assert b.post("/platform/creator/runs", json={"title": "T", "project_id": foreign}).status_code == 404
