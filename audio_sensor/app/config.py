from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (the folder containing pyproject.toml), resolved from this
# file's location so the .env file is found no matter which directory the
# app is started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """App settings.

    Each field is read from an environment variable of the same name, falling
    back to the .env file at the project root. Real environment variables
    take precedence over .env.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # allow unrelated keys in .env
    )

    DB_URL: str
    # Log every SQL statement (with parameters). Useful locally, noisy and
    # potentially sensitive elsewhere.
    DB_ECHO: bool = False

    # JWT signing. The secret is a SecretStr so it never shows up in logs or
    # reprs; generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"
    JWT_SECRET_KEY: SecretStr = Field(min_length=32)
    # HMAC algorithms only: they sign with the shared secret above. (RS*/ES*
    # would need a private/public key pair instead.)
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)

    # Where uploaded and censored audio files are kept. Relative paths are
    # resolved against the project root.
    STORAGE_DIR: Path = Path("storage")
    MAX_UPLOAD_MB: int = Field(default=50, gt=0)

    # Whisper model size: tiny, base, small, medium, large-v2, large-v3, ...
    WHISPER_MODEL: str = "small"
    # Extra words to censor on top of better_profanity's default list.
    # In .env, as JSON: CENSOR_WORDS=["word1", "word2"]
    CENSOR_WORDS: list[str] = []

    @property
    def storage_path(self) -> Path:
        if self.STORAGE_DIR.is_absolute():
            return self.STORAGE_DIR
        return PROJECT_ROOT / self.STORAGE_DIR

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


settings = Settings()
