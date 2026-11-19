"""Password hashing (Argon2id via pwdlib)."""

from pwdlib import PasswordHash

# Argon2id with pwdlib's recommended parameters. Hashes embed their own
# algorithm and parameters, so these can be tuned later without breaking
# existing hashes.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)
