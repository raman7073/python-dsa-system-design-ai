from pydantic import BaseModel


class ExcelRow(BaseModel):
    row_number: int
    values: dict[str, str | bool | int | float | None]


class ExcelRead(BaseModel):
    sheet: str
    columns: list[str]
    total: int
    rows: list[ExcelRow]


class ExcelImportResult(BaseModel):
    imported: int
