"""Password hashing (Argon2id via pwdlib) and JWT access tokens (PyJWT)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.config import settings

# Argon2id with pwdlib's recommended parameters. Hashes embed their own
# algorithm and parameters, so these can be tuned later without breaking
# existing hashes.
_password_hash = PasswordHash.recommended()

# Verified against when a login email doesn't exist, so that path costs the
# same time as a wrong password and response timing doesn't reveal which
# emails are registered.
_DUMMY_HASH = _password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)


def verify_and_update_password(password: str, hashed: str) -> tuple[bool, str | None]:
    """Verify, and return a new hash if the stored one uses outdated parameters."""
    return _password_hash.verify_and_update(password, hashed)


def burn_dummy_verify(password: str) -> None:
    """Spend the same time as a real verify (for unknown emails)."""
    _password_hash.verify(password, _DUMMY_HASH)


class InvalidTokenError(Exception):
    """The token is malformed, expired, or not signed by us."""


def create_access_token(user_id: UUID) -> tuple[str, int]:
    """Signed JWT for this user. Returns (token, lifetime in seconds)."""
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + lifetime,
        "type": "access",
    }
    token = jwt.encode(
        payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> UUID:
    """The user ID in a valid access token. Raises InvalidTokenError."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            # Pin the algorithm: never trust the one named in the token header.
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        if payload.get("type") != "access":
            raise InvalidTokenError("not an access token")
        return UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
