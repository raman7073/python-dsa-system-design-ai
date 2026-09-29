import os
from functools import lru_cache
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

class Settings:
    def __init__(self):
        self.jwt_secret = os.getenv("JWT_SECRET", "")
        self.encryption_key = os.getenv("ENCRYPTION_KEY", "")
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("replace_"):
            raise ValueError("Set JWT_SECRET to a random secret of at least 32 characters")
        try:
            Fernet(self.encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("Set ENCRYPTION_KEY to a generated Fernet key") from exc
        self.cors_origins = [x.strip() for x in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",") if x.strip()]
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must list explicit browser origins")

@lru_cache
def get_settings():
    return Settings()

