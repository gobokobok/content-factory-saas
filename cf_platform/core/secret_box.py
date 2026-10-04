"""Encrypt and decrypt tenant-level secrets (provider API keys) for storage (D104).

Plain Fernet from `cryptography`, keyed by the SETTINGS_ENCRYPTION_KEY Railway
variable. Nothing here logs or returns a secret; callers show `key_hint` only.
"""

from cryptography.fernet import Fernet, InvalidToken


class SecretBoxError(Exception):
    """Raised when a secret cannot be encrypted or decrypted (missing or wrong key)."""


def _fernet(key: str) -> Fernet:
    """Build a Fernet from the configured key; SecretBoxError when it is empty or malformed."""
    if not key:
        raise SecretBoxError("SETTINGS_ENCRYPTION_KEY is not set — API keys cannot be saved or read.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretBoxError("SETTINGS_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def encrypt_secret(plain: str, key: str) -> str:
    """Return `plain` encrypted with `key` as a URL-safe token string."""
    return _fernet(key).encrypt(plain.encode()).decode()


def decrypt_secret(token: str, key: str) -> str:
    """Return the secret hidden in `token`; SecretBoxError when `key` does not match."""
    try:
        return _fernet(key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretBoxError(
            "Stored API key cannot be decrypted — SETTINGS_ENCRYPTION_KEY changed. Save the key again."
        ) from exc


def key_hint(plain: str) -> str:
    """Return the last four characters of a key, the only part Studio ever shows."""
    return plain[-4:] if len(plain) >= 8 else ""
