from datetime import datetime, timedelta, timezone
from io import BytesIO

import jwt
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Todo, User
from app.core.security import password_hasher

from tests.helpers import PASSWORD, sign_in, workbook, upload






def test_crud_and_encryption(auth):
    assert auth.get("/todos").json()["items"] == []
    result = auth.post("/todos", json={"title": " Learn FastAPI ", "description": "Private information"})
    assert result.status_code == 201
    todo = result.json()
    assert todo["title"] == "Learn FastAPI"
    path = f"/todos/{todo['id']}"
    assert auth.get(path).json() == todo
    with Session(auth.test_engine) as db:
        stored = db.scalar(select(Todo))
        assert "Private information" not in stored.description_encrypted
        assert stored.description_encrypted
        user = db.scalar(select(User))
        assert user.password_hash != PASSWORD
        assert password_hasher.verify(PASSWORD, user.password_hash)
    patched = auth.patch(path, json={"completed": True})
    assert patched.json()["description"] == "Private information"
    replaced = auth.put(path, json={"title": "Replaced"})
    assert replaced.json()["description"] is None
    assert replaced.json()["completed"] is False
    assert auth.delete(path).status_code == 204
    assert auth.get(path).status_code == 404

def test_auth_and_ownership(client):
    alice = sign_in(client)
    bob = sign_in(client, "bob")
    item = client.post("/todos", json={"title": "Alice only"}, headers=alice).json()
    path = f"/todos/{item['id']}"
    assert client.get("/todos").status_code == 401
    assert client.get("/todos", headers=bob).json()["total"] == 0
    for method, payload in [("get", None), ("put", {"title": "stolen"}), ("patch", {"completed": True}), ("delete", None)]:
        kwargs = {"headers": bob}
        if payload is not None:
            kwargs["json"] = payload
        assert getattr(client, method)(path, **kwargs).status_code == 404
    assert client.get(path, headers=alice).status_code == 200
    assert client.post("/auth/register", json={"username": "ALICE", "password": PASSWORD}).status_code == 409
    assert client.post("/auth/token", data={"username": "alice", "password": "wrong"}).status_code == 401
    assert client.get("/auth/me", headers=alice).json()["username"] == "alice"

@pytest.mark.parametrize("kind", ["expired", "signature", "audience", "missing_exp", "subject"])
def test_invalid_tokens(client, kind):
    sign_in(client)
    now = datetime.now(timezone.utc)
    claims = {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5), "iss": "todo-api", "aud": "todo-api"}
    secret = get_settings().jwt_secret
    if kind == "expired":
        claims["exp"] = now - timedelta(seconds=1)
    if kind == "signature":
        secret = "wrong-secret-" * 5
    if kind == "audience":
        claims["aud"] = "another-api"
    if kind == "missing_exp":
        del claims["exp"]
    if kind == "subject":
        claims["sub"] = "9" * 100
    token = jwt.encode(claims, secret, algorithm="HS256")
    assert client.get("/todos", headers={"Authorization": f"Bearer {token}"}).status_code == 401

@pytest.mark.parametrize("payload", [{}, {"title": " "}, {"title": "x" * 201}, {"title": "valid", "owner_id": 2}])
def test_invalid_todos(auth, payload):
    assert auth.post("/todos", json=payload).status_code == 422
    assert auth.get("/todos").json()["total"] == 0

def test_patch_validation(auth):
    todo = auth.post("/todos", json={"title": "Keep", "description": "secret"}).json()
    path = f"/todos/{todo['id']}"
    for payload in [{}, {"title": None}, {"completed": None}]:
        assert auth.patch(path, json=payload).status_code == 422
    assert auth.patch(path, json={"description": None}).json()["description"] is None

def test_pagination_sort_filter(auth):
    for title, done in [("Zulu", False), ("Alpha", True), ("Alpha", False)]:
        assert auth.post("/todos", json={"title": title, "completed": done}).status_code == 201
    page = auth.get("/todos?sort_by=title&order=asc&offset=1&limit=1").json()
    assert page["total"] == 3
    assert page["items"][0]["id"] == 3
    assert auth.get("/todos?completed=true").json()["total"] == 1
    assert auth.get("/todos?order=desc").json()["items"][0]["id"] == 3
    assert auth.get("/todos?offset=99").json()["items"] == []
    for query in ["limit=101", "offset=-1", "sort_by=password_hash", "order=invalid"]:
        assert auth.get("/todos?" + query).status_code == 422

def test_excel_success_and_template(auth):
    template = auth.get("/todos/import/template")
    assert template.status_code == 200
    assert upload(auth, template.content).json() == {"imported": 1}
    assert upload(auth, workbook([["One", "secret", True], ["Two", None, None]])).json() == {"imported": 2}
    assert auth.get("/todos").json()["total"] == 3

@pytest.mark.parametrize("rows", [
    [["Valid", None, False], [None, "missing title", False]],
    [["=1+1", None, False]],
    [["Valid", None, False, "unexpected"]],
    [],
])
def test_excel_atomic_validation(auth, rows):
    response = upload(auth, workbook(rows))
    assert response.status_code == 422
    assert auth.get("/todos").json()["total"] == 0

def test_excel_limits_and_corruption(auth):
    assert upload(auth, b"not a zip").status_code == 422
    assert upload(auth, b"x", "todos.csv").status_code == 415
    assert upload(auth, b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert upload(auth, workbook([["Task", None, False]] * 1001)).status_code == 413
    assert upload(auth, workbook([["Task", None, False]], ["wrong"])).status_code == 422

def test_request_body_limit(client):
    response = client.post("/auth/register", content=b"x" * (3 * 1024 * 1024 + 1))
    assert response.status_code == 413

def test_excel_archive_limits_and_sheets(auth):
    from zipfile import ZIP_DEFLATED, ZipFile
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", b"x" * (20 * 1024 * 1024 + 1))
    assert upload(auth, stream.getvalue()).status_code == 413
    book = Workbook()
    book.create_sheet("Extra")
    stream = BytesIO()
    book.save(stream)
    book.close()
    assert upload(auth, stream.getvalue()).status_code == 422

def test_openapi(client):
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/todos"]["get"]["security"]
    assert "/todos/import" in schema["paths"]

def test_cors_and_error_redaction(client):
    allowed = client.options("/todos", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = client.options("/todos", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"})
    assert denied.status_code == 400
    response = client.post("/auth/register", json={"username": "alice", "password": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text
    assert "x-request-id" in response.headers
    assert client.get("/health").status_code == 200

