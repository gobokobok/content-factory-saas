"""Accounts, sessions and the request principal (Sprint P-AUTH, D114, D118).

A *user* signs in with Google (keyed by the Google ``sub``, never the e-mail) and
owns exactly one personal *tenant* — every run, project, library item, setting and
stored key belongs to that tenant. The owner's pre-P-AUTH data lives under the
tenant ``operator`` (``OWNER_TENANT_ID``), so the owner's account maps onto it and
keeps everything.

An account is **Basic** or **Super** (D118). The owner can flip *View as Basic* on
one session: the server then treats that session as Basic and never charges.

The principal of the current request travels in a ContextVar set by the auth
middleware (src/main.py) and read by the routes — unset means "not authenticated"
and every reader fails closed. Persistence sits behind in-memory and Postgres
stores (cf_platform/core/postgres_accounts.py) like the other repositories (D048).
"""

import hashlib
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from cf_platform.core.projects import CREATOR_CONFIG_FLAG, Project, ProjectNotFoundError, ProjectRepository
from cf_platform.core.schemas import DEFAULT_PROJECT_ID

OWNER_TENANT_ID = "operator"
OWNER_USER_ID = "operator"

AccountType = Literal["basic", "super"]
ACCOUNT_BASIC: AccountType = "basic"
ACCOUNT_SUPER: AccountType = "super"

# Value of the session cookie: a version prefix plus the opaque token. The token is
# random; only its SHA-256 is stored, so a database read never yields a usable cookie.
SESSION_COOKIE_PREFIX = "s1."


class User(BaseModel):
    """One signed-in person: Google identity, tenant, account type and consent state."""

    user_id: str
    tenant_id: str
    google_sub: str | None = None
    email: str = ""
    name: str = ""
    account_type: AccountType = ACCOUNT_BASIC
    created_at: datetime
    last_login_at: datetime | None = None
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None
    disabled_at: datetime | None = None


class SessionRecord(BaseModel):
    """One server-side session: revocable, expiring, tied to a user."""

    token_hash: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    view_as_basic: bool = False


class OAuthState(BaseModel):
    """A pending Google sign-in: the single-use state, its PKCE verifier and where to land."""

    state_hash: str
    code_verifier: str
    next_path: str = "/"
    created_at: datetime


@dataclass(frozen=True)
class Principal:
    """Who the current request acts as, resolved by the auth middleware from the session."""

    user_id: str
    tenant_id: str
    email: str = ""
    account_type: AccountType = ACCOUNT_BASIC
    view_as_basic: bool = False
    # False until the user has accepted the terms in force (S9); the owner is exempt.
    terms_accepted: bool = True

    @property
    def effective_type(self) -> AccountType:
        """The type the server enforces: Basic while View-as-Basic is on, else the account's own."""
        return ACCOUNT_BASIC if self.view_as_basic else self.account_type

    @property
    def is_super(self) -> bool:
        """True when this request may use Super features (and View-as is not narrowing it)."""
        return self.effective_type == ACCOUNT_SUPER

    @property
    def is_owner(self) -> bool:
        """True for the owner's tenant — the operator whose Railway keys are the platform's."""
        return self.tenant_id == OWNER_TENANT_ID


class NotAuthenticatedError(Exception):
    """Raised by current_principal() when no principal was set for this request."""


_principal_var: ContextVar[Principal | None] = ContextVar("cf_principal", default=None)


def set_principal(principal: Principal | None):
    """Set the request's principal; returns the token for reset_principal."""
    return _principal_var.set(principal)


def reset_principal(token) -> None:
    """Restore the principal to what it was before set_principal returned token."""
    _principal_var.reset(token)


def get_principal() -> Principal | None:
    """The request's principal, or None when the request is not authenticated."""
    return _principal_var.get()


def current_principal() -> Principal:
    """The request's principal. Raises NotAuthenticatedError when there is none (fail closed)."""
    principal = _principal_var.get()
    if principal is None:
        raise NotAuthenticatedError("No authenticated principal for this request")
    return principal


def current_tenant_id() -> str:
    """The tenant every read and write of this request is scoped to (fail closed)."""
    return current_principal().tenant_id


def owner_principal() -> Principal:
    """The principal of the owner's legacy password login: Super, tenant ``operator``."""
    return Principal(user_id=OWNER_USER_ID, tenant_id=OWNER_TENANT_ID, account_type=ACCOUNT_SUPER)


def default_project_id(tenant_id: str) -> str:
    """The id of a tenant's default project: the legacy ``default`` for the owner, else per tenant."""
    if tenant_id == OWNER_TENANT_ID:
        return DEFAULT_PROJECT_ID
    return f"{DEFAULT_PROJECT_ID}-{tenant_id}"


def hash_token(token: str) -> str:
    """SHA-256 hex of a session token or OAuth state — what the stores keep."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> str:
    """A fresh unguessable session token (256 bits)."""
    return secrets.token_urlsafe(32)


def cookie_value(token: str) -> str:
    """The cookie value that carries token."""
    return f"{SESSION_COOKIE_PREFIX}{token}"


def token_from_cookie(value: str) -> str | None:
    """The session token inside a cookie value, or None when it is not a session cookie."""
    if value.startswith(SESSION_COOKIE_PREFIX) and len(value) > len(SESSION_COOKIE_PREFIX):
        return value[len(SESSION_COOKIE_PREFIX):]
    return None


class AccountStore(Protocol):
    """Persistence for users, sessions and pending OAuth states."""

    async def get_user(self, user_id: str) -> User | None:
        """Return the user, or None."""
        ...

    async def get_user_by_sub(self, google_sub: str) -> User | None:
        """Return the user with this Google ``sub``, or None."""
        ...

    async def save_user(self, user: User) -> User:
        """Insert or overwrite the user."""
        ...

    async def list_users(self) -> list[User]:
        """Every user, newest first (the owner's admin view)."""
        ...

    async def save_session(self, session: SessionRecord) -> SessionRecord:
        """Insert or overwrite the session."""
        ...

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        """Return the session, or None."""
        ...

    async def revoke_session(self, token_hash: str) -> None:
        """Mark the session revoked (idempotent)."""
        ...

    async def save_oauth_state(self, state: OAuthState) -> None:
        """Store a pending sign-in."""
        ...

    async def pop_oauth_state(self, state_hash: str) -> OAuthState | None:
        """Return and delete a pending sign-in (single use), or None."""
        ...

    async def list_invites(self) -> list[dict]:
        """Invited e-mails (lower case) with who added them and when, newest first."""
        ...

    async def add_invite(self, email: str, added_by: str = "") -> None:
        """Invite an e-mail (idempotent)."""
        ...

    async def remove_invite(self, email: str) -> bool:
        """Remove an invite; True when it existed."""
        ...


class InMemoryAccountStore:
    """In-memory AccountStore — process-local; the local-development fallback (D048)."""

    def __init__(self) -> None:
        """Start empty."""
        self._users: dict[str, User] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._states: dict[str, OAuthState] = {}
        self._invites: dict[str, dict] = {}

    async def get_user(self, user_id: str) -> User | None:
        """Return the user, or None."""
        return self._users.get(user_id)

    async def get_user_by_sub(self, google_sub: str) -> User | None:
        """Return the user with this Google ``sub``, or None."""
        return next((u for u in self._users.values() if u.google_sub == google_sub), None)

    async def save_user(self, user: User) -> User:
        """Insert or overwrite the user."""
        self._users[user.user_id] = user
        return user

    async def list_users(self) -> list[User]:
        """Every user, newest first."""
        return sorted(self._users.values(), key=lambda u: u.created_at, reverse=True)

    async def save_session(self, session: SessionRecord) -> SessionRecord:
        """Insert or overwrite the session."""
        self._sessions[session.token_hash] = session
        return session

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        """Return the session, or None."""
        return self._sessions.get(token_hash)

    async def revoke_session(self, token_hash: str) -> None:
        """Mark the session revoked (idempotent)."""
        session = self._sessions.get(token_hash)
        if session and session.revoked_at is None:
            self._sessions[token_hash] = session.model_copy(update={"revoked_at": datetime.now(UTC)})

    async def save_oauth_state(self, state: OAuthState) -> None:
        """Store a pending sign-in."""
        self._states[state.state_hash] = state

    async def pop_oauth_state(self, state_hash: str) -> OAuthState | None:
        """Return and delete a pending sign-in (single use), or None."""
        return self._states.pop(state_hash, None)

    async def purge_expired(self, now: datetime, state_max_age: timedelta) -> tuple[int, int]:
        """Delete sessions that expired or were revoked, and sign-in states older than state_max_age."""
        dead = [h for h, s in self._sessions.items() if s.expires_at <= now or s.revoked_at is not None]
        for token_hash in dead:
            del self._sessions[token_hash]
        old = [h for h, st in self._states.items() if st.created_at <= now - state_max_age]
        for state_hash in old:
            del self._states[state_hash]
        return len(dead), len(old)

    async def list_invites(self) -> list[dict]:
        """Invited e-mails, newest first."""
        return sorted(self._invites.values(), key=lambda i: i["created_at"], reverse=True)

    async def add_invite(self, email: str, added_by: str = "") -> None:
        """Invite an e-mail (idempotent)."""
        self._invites.setdefault(email, {"email": email, "added_by": added_by, "created_at": datetime.now(UTC)})

    async def remove_invite(self, email: str) -> bool:
        """Remove an invite; True when it existed."""
        return self._invites.pop(email, None) is not None


def parse_email_list(raw: str) -> set[str]:
    """A comma or whitespace separated e-mail list, lower-cased, as a set."""
    return {part.strip().lower() for part in raw.replace(";", ",").replace("\n", ",").split(",") if part.strip()}


async def create_session(
    store: AccountStore, user_id: str, *, ttl_days: int, now: datetime | None = None
) -> tuple[str, SessionRecord]:
    """Create a session for user_id. Returns (cookie value, record). A new token every login (rotation)."""
    moment = now or datetime.now(UTC)
    token = new_session_token()
    record = SessionRecord(
        token_hash=hash_token(token),
        user_id=user_id,
        created_at=moment,
        expires_at=moment + timedelta(days=max(1, ttl_days)),
    )
    await store.save_session(record)
    return cookie_value(token), record


async def principal_from_cookie(
    store: AccountStore, value: str, *, now: datetime | None = None, terms_version: str = ""
) -> tuple[Principal, SessionRecord] | None:
    """Resolve a session cookie to its principal, or None when it is unknown, expired, revoked or disabled.

    terms_version is the version currently in force; a user who has not accepted it
    gets a principal with terms_accepted=False (the middleware then asks them to).
    """
    token = token_from_cookie(value)
    if token is None:
        return None
    session = await store.get_session(hash_token(token))
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= (now or datetime.now(UTC)):
        return None
    user = await store.get_user(session.user_id)
    if user is None or user.disabled_at is not None:
        return None
    principal = Principal(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        email=user.email,
        account_type=user.account_type,
        # View-as only narrows a Super account; a Basic one has nothing to narrow.
        view_as_basic=bool(session.view_as_basic) and user.account_type == ACCOUNT_SUPER,
        terms_accepted=(
            user.tenant_id == OWNER_TENANT_ID or not terms_version or user.terms_version == terms_version
        ),
    )
    return principal, session


async def ensure_owner_user(store: AccountStore, *, email: str = "") -> User:
    """Return the owner's user row (the legacy password login), creating it on first use."""
    existing = await store.get_user(OWNER_USER_ID)
    if existing is not None:
        return existing
    user = User(
        user_id=OWNER_USER_ID,
        tenant_id=OWNER_TENANT_ID,
        email=email,
        name="Owner",
        account_type=ACCOUNT_SUPER,
        created_at=datetime.now(UTC),
    )
    return await store.save_user(user)


def build_personal_default_project(tenant_id: str, name: str) -> Project:
    """The hidden default project a new tenant starts with; it is also the Creator's project."""
    now = datetime.now(UTC)
    return Project(
        project_id=default_project_id(tenant_id),
        tenant_id=tenant_id,
        name=name,
        config={CREATOR_CONFIG_FLAG: True, "hidden": True},
        created_at=now,
        updated_at=now,
    )


async def ensure_personal_project(projects: ProjectRepository, tenant_id: str, name: str) -> Project:
    """Make sure tenant_id has its hidden default project (idempotent) and return it."""
    project_id = default_project_id(tenant_id)
    try:
        return await projects.get(project_id)
    except ProjectNotFoundError:
        return await projects.save(build_personal_default_project(tenant_id, name))


async def provision_google_user(
    store: AccountStore,
    projects: ProjectRepository,
    *,
    google_sub: str,
    email: str,
    name: str,
    owner_emails: set[str],
    super_emails: set[str],
    project_name: str,
) -> User:
    """Find or create the user for a verified Google identity, with their tenant and hidden project.

    Users are keyed by ``sub``. The owner's e-mail maps to the legacy tenant so the
    owner keeps their data; e-mails in super_emails are Super; everyone else is Basic.
    Account type is re-derived from the lists at every sign-in, so removing an
    address demotes the account without a manual step.
    """
    lowered = email.strip().lower()
    now = datetime.now(UTC)
    account_type: AccountType = ACCOUNT_SUPER if (lowered in owner_emails or lowered in super_emails) else ACCOUNT_BASIC
    user = await store.get_user_by_sub(google_sub)
    if user is None:
        if lowered in owner_emails and await store.get_user(OWNER_USER_ID) is None:
            user_id, tenant_id = OWNER_USER_ID, OWNER_TENANT_ID
        elif lowered in owner_emails:
            # The owner row already exists (legacy login): attach the Google identity to it.
            existing = await store.get_user(OWNER_USER_ID)
            assert existing is not None
            user = existing.model_copy(update={"google_sub": google_sub})
            user_id = tenant_id = ""
        else:
            user_id = tenant_id = f"u_{secrets.token_hex(12)}"
        if user is None:
            user = User(user_id=user_id, tenant_id=tenant_id, google_sub=google_sub, created_at=now)
    user = user.model_copy(
        update={"email": lowered, "name": name or user.name, "account_type": account_type, "last_login_at": now}
    )
    await store.save_user(user)
    if user.tenant_id != OWNER_TENANT_ID:
        await ensure_personal_project(projects, user.tenant_id, project_name)
    return user
