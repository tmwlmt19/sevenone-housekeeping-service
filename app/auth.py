import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()

# Per-hotel PMS API keys. The visible prefix (below) doubles as a human-readable
# label in the admin UI and is stored alongside the hash so a key can be
# identified without ever persisting its secret.
API_KEY_PREFIX = "so_pms_"
# How many leading characters of the full key we keep for display (prefix + a
# few token chars, e.g. "so_pms_Ab12Cd"). Never enough to reconstruct the key.
API_KEY_DISPLAY_LEN = len(API_KEY_PREFIX) + 6

# bcrypt operates on at most 72 bytes; longer inputs raise in bcrypt 5.x, so we
# truncate consistently for both hashing and verification.
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/invalid hash stored in the DB.
        return False


def generate_temp_password() -> str:
    """A random temporary password (e.g. for a newly provisioned or admin-added
    user). Readable enough to communicate, but not guessable. The recipient must
    change it on first login."""
    return "Sev-" + secrets.token_urlsafe(9)


def generate_api_key() -> str:
    """A high-entropy per-hotel PMS API key. Shown to the admin exactly once;
    only its SHA-256 hash is stored (see `hash_api_key`)."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Deterministic SHA-256 hash of an API key, for storage and lookup.

    Unlike passwords, API keys are long and random, so a fast unsalted hash is
    both safe and *necessary*: the hotel is derived from the key, so we must be
    able to find the matching row by hashing the presented key and doing a single
    indexed equality lookup (bcrypt's per-hash salt would make that impossible)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> str:
    """Create a signed JWT. `subject` becomes the `sub` claim (the user id)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns the claims, or None if invalid/expired."""
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
