"""Invited accounts: the owner manages the sign-in list in the Studio; password login is off by default."""

from datetime import UTC, datetime
from unittest.mock import patch

from cf_platform.core.accounts import OAuthState, hash_token
from cf_platform.core.google_oauth import GoogleIdentity
from tests.test_p_auth_accounts import World, run


def _owner(w: World):
    cookie, _ = run(w.sign_in("owner@example.com", "sub-owner"))
    return w.client(cookie)


def _callback(w: World, email: str, sub: str):
    state = "s-" + "y" * 20
    run(w.accounts.save_oauth_state(
        OAuthState(state_hash=hash_token(state), code_verifier="v" * 50, next_path="/create", created_at=datetime.now(UTC))
    ))
    with patch("cf_platform.core.google_oauth.exchange_code", return_value=GoogleIdentity(sub, email, "N")):
        return w.client().get(f"/auth/google/callback?code=abc&state={state}")


def test_an_address_added_in_the_studio_can_sign_in():
    w = World()
    try:
        assert _callback(w, "new@example.com", "sub-new").headers["location"].startswith("/login?error=not_invited")
        r = _owner(w).post("/platform/admin/invites", json={"email": " New@Example.com "})
        assert r.status_code == 201 and r.json()["email"] == "new@example.com"
        assert _callback(w, "new@example.com", "sub-new").headers["location"] == "/create"
    finally:
        w.close()


def test_the_list_shows_who_has_signed_in():
    w = World()
    try:
        owner = _owner(w)
        owner.post("/platform/admin/invites", json={"email": "new@example.com"})
        owner.post("/platform/admin/invites", json={"email": "later@example.com"})
        _callback(w, "new@example.com", "sub-new")
        rows = {r["email"]: r for r in owner.get("/platform/admin/invites").json()}
        assert rows["new@example.com"]["signed_in"] is True and rows["later@example.com"]["signed_in"] is False
    finally:
        w.close()


def test_removing_an_address_switches_the_account_off_and_adding_it_back_switches_it_on():
    w = World()
    try:
        owner = _owner(w)
        owner.post("/platform/admin/invites", json={"email": "new@example.com"})
        cookie = _callback(w, "new@example.com", "sub-new").cookies.get("cf_session") or None
        user = run(w.accounts.get_user_by_sub("sub-new"))
        r = owner.delete("/platform/admin/invites/new@example.com")
        assert r.status_code == 200 and r.json()["switched_off"] is True
        assert run(w.accounts.get_user(user.user_id)).disabled_at is not None
        assert _callback(w, "new@example.com", "sub-new").headers["location"].startswith("/login?error=not_invited")
        owner.post("/platform/admin/invites", json={"email": "new@example.com"})
        assert run(w.accounts.get_user(user.user_id)).disabled_at is None
        assert cookie is None or isinstance(cookie, str)
    finally:
        w.close()


def test_owner_and_super_addresses_from_the_server_cannot_be_removed():
    w = World()
    try:
        assert _owner(w).delete("/platform/admin/invites/boss@example.com").status_code == 409
    finally:
        w.close()


def test_a_bad_address_is_refused_and_a_basic_user_is_locked_out():
    w = World()
    try:
        assert _owner(w).post("/platform/admin/invites", json={"email": "not-an-email"}).status_code == 422
        cookie, _ = run(w.sign_in("friend@example.com", "sub-friend"))
        assert w.client(cookie).get("/platform/admin/invites").status_code in (403, 404)
        assert w.client(cookie).post("/platform/admin/invites", json={"email": "x@example.com"}).status_code in (403, 404)
    finally:
        w.close()


def test_password_login_is_off_by_default():
    w = World(PASSWORD_LOGIN_ENABLED="false")
    try:
        assert w.client().get("/auth/providers").json()["password"] is False
        assert w.client().post("/auth/login", json={"password": "correct-horse-battery"}).status_code == 404
    finally:
        w.close()


def test_the_demo_access_address_reaches_the_login_page_and_can_be_switched_off():
    w = World(DEMO_ACCESS_EMAIL="demo@example.com")
    try:
        assert w.client().get("/auth/providers").json()["demo_access_email"] == "demo@example.com"
    finally:
        w.close()
    w = World(DEMO_ACCESS_EMAIL="")
    try:
        assert w.client().get("/auth/providers").json()["demo_access_email"] == ""
    finally:
        w.close()


def test_the_login_page_offers_a_demo_request_that_asks_for_a_gmail_account():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "src" / "static" / "login-v2.html").read_text(encoding="utf-8")
    assert "No access to the platform? Apply for the demo access" in page
    assert "p.demo_access_email" in page and "'mailto:'" in page
    assert "Gmail account I will sign in with" in page
    # An empty error line must not leave a blank band under the Google button.
    assert "#urlError:empty { display: none; }" in page


def test_password_login_works_when_switched_on():
    w = World(PASSWORD_LOGIN_ENABLED="true")
    try:
        assert w.client().get("/auth/providers").json()["password"] is True
        assert w.client().post("/auth/login", json={"password": "correct-horse-battery"}).status_code == 200
    finally:
        w.close()
