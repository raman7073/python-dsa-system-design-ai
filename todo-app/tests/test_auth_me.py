from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import User
from tests.helpers import sign_in


def test_me_returns_only_the_authenticated_users_public_fields(client):
    alice = sign_in(client, "alice")
    bob = sign_in(client, "bob")
    for headers, username in [(alice, "alice"), (bob, "bob")]:
        response = client.get("/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"id", "username"}
        assert data["username"] == username
        with Session(client.test_engine) as db:
            assert db.get(User, data["id"]).username == username


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid"])
def test_me_rejects_missing_or_invalid_credentials(client, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_expired_token(client):
    headers = sign_in(client)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now - timedelta(minutes=20),
         "exp": now - timedelta(minutes=5), "iss": "todo-api", "aud": "todo-api"},
        get_settings().jwt_secret, algorithm="HS256",
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_rejects_token_for_deleted_user(client):
    headers = sign_in(client)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    with Session(client.test_engine) as db:
        db.delete(db.get(User, user_id))
        db.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401
