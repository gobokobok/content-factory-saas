"""Postgres-backed account store (Sprint P-AUTH) — rows of migration 0005_accounts.sql."""

from psycopg_pool import AsyncConnectionPool

from cf_platform.core.accounts import OAuthState, SessionRecord, User
from cf_platform.core.postgres_repos import _ensure_open

_USER_COLUMNS = (
    "user_id, tenant_id, google_sub, email, name, account_type, created_at, last_login_at, "
    "terms_version, terms_accepted_at, disabled_at"
)
_SESSION_COLUMNS = "token_hash, user_id, created_at, expires_at, revoked_at, view_as_basic"


def _user_from_row(row: tuple) -> User:
    """Build a User from a row selected with _USER_COLUMNS."""
    keys = _USER_COLUMNS.replace(" ", "").split(",")
    return User(**dict(zip(keys, row, strict=True)))


def _session_from_row(row: tuple) -> SessionRecord:
    """Build a SessionRecord from a row selected with _SESSION_COLUMNS."""
    keys = _SESSION_COLUMNS.replace(" ", "").split(",")
    return SessionRecord(**dict(zip(keys, row, strict=True)))


class PostgresAccountStore:
    """AccountStore on Postgres — users, sessions and pending OAuth states."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def _fetchone(self, sql: str, params: tuple) -> tuple | None:
        """Run a SELECT and return its first row, or None."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchone()

    async def _execute(self, sql: str, params: tuple) -> int:
        """Run a write, commit, and return the affected row count."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                count = cur.rowcount
            await conn.commit()
        return count

    async def get_user(self, user_id: str) -> User | None:
        """Return the user, or None."""
        row = await self._fetchone(f"SELECT {_USER_COLUMNS} FROM users WHERE user_id = %s", (user_id,))
        return _user_from_row(row) if row else None

    async def get_user_by_sub(self, google_sub: str) -> User | None:
        """Return the user with this Google ``sub``, or None."""
        row = await self._fetchone(f"SELECT {_USER_COLUMNS} FROM users WHERE google_sub = %s", (google_sub,))
        return _user_from_row(row) if row else None

    async def save_user(self, user: User) -> User:
        """Insert or overwrite the user keyed on user_id."""
        await self._execute(
            f"""
            INSERT INTO users ({_USER_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                google_sub = EXCLUDED.google_sub, email = EXCLUDED.email, name = EXCLUDED.name,
                account_type = EXCLUDED.account_type, last_login_at = EXCLUDED.last_login_at,
                terms_version = EXCLUDED.terms_version, terms_accepted_at = EXCLUDED.terms_accepted_at,
                disabled_at = EXCLUDED.disabled_at
            """,
            (
                user.user_id, user.tenant_id, user.google_sub, user.email, user.name, user.account_type,
                user.created_at, user.last_login_at, user.terms_version, user.terms_accepted_at, user.disabled_at,
            ),
        )
        return user

    async def list_users(self) -> list[User]:
        """Every user, newest first."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT {_USER_COLUMNS} FROM users ORDER BY created_at DESC")
                rows = await cur.fetchall()
        return [_user_from_row(row) for row in rows]

    async def save_session(self, session: SessionRecord) -> SessionRecord:
        """Insert or overwrite the session keyed on token_hash."""
        await self._execute(
            f"""
            INSERT INTO sessions ({_SESSION_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (token_hash) DO UPDATE SET
                expires_at = EXCLUDED.expires_at, revoked_at = EXCLUDED.revoked_at,
                view_as_basic = EXCLUDED.view_as_basic
            """,
            (session.token_hash, session.user_id, session.created_at, session.expires_at,
             session.revoked_at, session.view_as_basic),
        )
        return session

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        """Return the session, or None."""
        row = await self._fetchone(f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE token_hash = %s", (token_hash,))
        return _session_from_row(row) if row else None

    async def revoke_session(self, token_hash: str) -> None:
        """Mark the session revoked (idempotent)."""
        await self._execute(
            "UPDATE sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL", (token_hash,)
        )

    async def save_oauth_state(self, state: OAuthState) -> None:
        """Store a pending sign-in."""
        await self._execute(
            "INSERT INTO oauth_states (state_hash, code_verifier, next_path, created_at) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (state_hash) DO NOTHING",
            (state.state_hash, state.code_verifier, state.next_path, state.created_at),
        )

    async def pop_oauth_state(self, state_hash: str) -> OAuthState | None:
        """Return and delete a pending sign-in (single use), or None."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM oauth_states WHERE state_hash = %s "
                    "RETURNING state_hash, code_verifier, next_path, created_at",
                    (state_hash,),
                )
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            return None
        return OAuthState(state_hash=row[0], code_verifier=row[1], next_path=row[2], created_at=row[3])
