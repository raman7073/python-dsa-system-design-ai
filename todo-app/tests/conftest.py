import os
import secrets
from cryptography.fernet import Fernet

# Set before application imports; tests never use development secrets or PostgreSQL.
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"


from contextlib import asynccontextmanager
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db.session import Base, get_db
from app.main import create_app
from tests.helpers import sign_in

@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def test_db():
        with Session(engine) as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise
    @asynccontextmanager
    async def lifespan(app):
        yield
    app = create_app()
    original = app.router.lifespan_context
    app.router.lifespan_context = lifespan
    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            client.test_engine = engine
            yield client
    finally:
        app.dependency_overrides.clear()
        app.router.lifespan_context = original
        engine.dispose()

@pytest.fixture
def auth(client):
    client.headers.update(sign_in(client))
    return client
