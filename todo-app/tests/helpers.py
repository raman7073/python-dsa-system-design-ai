from io import BytesIO
from openpyxl import Workbook

PASSWORD = "strong test password 123"

def sign_in(client, name="alice"):
    registered = client.post("/auth/register", json={"username": name, "password": PASSWORD})
    assert registered.status_code == 201
    response = client.post("/auth/token", data={"username": name, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}

def workbook(rows, headers=None):
    book = Workbook()
    book.active.append(headers or ["title", "description", "completed"])
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()

def upload(client, content, filename="todos.xlsx"):
    return client.post("/todos/import", files={"file": (filename, content)})
