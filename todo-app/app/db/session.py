import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# URL.create safely handles special characters in your password.
database_url = os.getenv("DATABASE_URL") or URL.create(
    "postgresql+psycopg",
    username=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    database=os.getenv("POSTGRES_DB", "fastapi_learning"),
)
engine = create_engine(database_url, pool_pre_ping=True, connect_args=(
    {"check_same_thread": False} if str(database_url).startswith("sqlite")
    else {"connect_timeout": 5}
))
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    # Each request gets its own session, closed automatically afterward.
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
