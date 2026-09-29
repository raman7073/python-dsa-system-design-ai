"""Append missing local secrets without displaying or replacing existing values."""
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values

path = Path(__file__).resolve().parents[1] / ".env"
values = dotenv_values(path) if path.exists() else {}
additions = {}
if not values.get("JWT_SECRET"):
    additions["JWT_SECRET"] = secrets.token_urlsafe(48)
if not values.get("ENCRYPTION_KEY"):
    additions["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
if additions:
    with path.open("a", encoding="utf-8") as file:
        file.write("\n" + "\n".join(f"{k}={v}" for k, v in additions.items()) + "\n")
print("Local secrets configured; existing values preserved. Keep .env private and backed up.")
