import httpx
import pytest

from tests.helpers import MakeUser


async def test_signup_returns_user_without_password(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/signup", json={"email": "Jane@Example.com", "password": "correct-horse-42"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "jane@example.com"  # stored lower-cased
    assert body["is_active"] is True
    assert "password" not in r.text and "hashed" not in r.text


async def test_signup_same_email_any_case_is_409(client: httpx.AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "correct-horse-42"}
    assert (await client.post("/auth/signup", json=payload)).status_code == 201
    payload["email"] = "DUP@example.com"
    r = await client.post("/auth/signup", json=payload)
    assert r.status_code == 409


@pytest.mark.parametrize(
    "password",
    ["short1", "no-digits-here", "1234567890", " leading-space-1"],
    ids=["too-short", "no-digit", "no-letter", "whitespace"],
)
async def test_signup_rejects_weak_password(client: httpx.AsyncClient, password: str) -> None:
    r = await client.post("/auth/signup", json={"email": "a@example.com", "password": password})
    assert r.status_code == 422


async def test_signup_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/signup",
        json={"email": "a@example.com", "password": "correct-horse-42", "is_active": False},
    )
    assert r.status_code == 422


async def test_login_token_works_for_me(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    r = await client.post("/auth/login", data={"username": user.email, "password": user.password})
    assert r.status_code == 200
    token = r.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_login_failures_look_the_same(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    wrong_password = await client.post(
        "/auth/login", data={"username": user.email, "password": "not-it-1"}
    )
    unknown_email = await client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": "whatever-1"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}], ids=["none", "bad"])
async def test_me_requires_valid_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    r = await client.get("/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
