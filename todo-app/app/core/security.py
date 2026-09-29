from datetime import datetime, timedelta, timezone
import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash
from app.core.config import get_settings

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash("dummy password for timing protection")

def create_token(user_id: int):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=15),
                       "iss": "todo-api", "aud": "todo-api"},
                      get_settings().jwt_secret, algorithm="HS256")

def encrypt(value: str | None):
    return None if value is None else Fernet(get_settings().encryption_key.encode()).encrypt(value.encode()).decode()

def decrypt(value: str | None):
    return None if value is None else Fernet(get_settings().encryption_key.encode()).decrypt(value.encode()).decode()
