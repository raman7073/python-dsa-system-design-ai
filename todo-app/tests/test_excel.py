from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

from tests.helpers import workbook


def read(client, content, filename="report.xlsx"):
    return client.post("/excel/read", files={"file": (filename, content)})


def test_read_generic_excel_without_importing(auth):
    content = workbook(
        [["Alice", 42, True, datetime(2026, 9, 18)], ["Bob", None, False, None]],
        ["name", "score", "active", "date"],
    )
    response = read(auth, content)
    assert response.status_code == 200
    data = response.json()
    assert data["columns"] == ["name", "score", "active", "date"]
    assert data["total"] == 2
    assert data["rows"][0] == {
        "row_number": 2,
        "values": {"name": "Alice", "score": 42, "active": True, "date": "2026-09-18T00:00:00"},
    }
    assert data["rows"][1]["values"]["score"] is None
    assert auth.get("/todos").json()["total"] == 0


def test_read_requires_authentication(client):
    assert read(client, workbook([["Task", None, False]])).status_code == 401


@pytest.mark.parametrize("headers, rows", [
    (["name", "name"], [["one", "two"]]),
    (["name", " "], [["one", "two"]]),
    (["name"], [["=1+1"]]),
    (["name"], [["#DIV/0!"]]),
    (["name"], [["one", "extra"]]),
    (["name"], [["x" * 5001]]),
    (["=1+1"], [["one"]]),
])
def test_invalid_read(auth, headers, rows):
    assert read(auth, workbook(rows, headers)).status_code == 422


def test_read_file_and_table_limits(auth):
    assert read(auth, b"corrupt").status_code == 422
    assert read(auth, b"csv", "report.csv").status_code == 415
    assert read(auth, b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert read(auth, workbook([["row"]] * 1001, ["name"])).status_code == 413
    assert read(auth, workbook([], [f"column_{i}" for i in range(51)])).status_code == 413


def test_read_blank_rows_and_empty_sheet(auth):
    response = read(auth, workbook([["first"], [], ["last"]], ["name"]))
    assert [r["row_number"] for r in response.json()["rows"]] == [2, 4]
    headers_only = read(auth, workbook([], ["name"]))
    assert headers_only.status_code == 200
    assert headers_only.json()["total"] == 0
    book = Workbook()
    output = BytesIO()
    book.save(output)
    book.close()
    assert read(auth, output.getvalue()).status_code == 422


def test_read_is_documented(auth):
    operation = auth.get("/openapi.json").json()["paths"]["/excel/read"]["post"]
    assert operation["security"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
