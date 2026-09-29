from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile

from app.api.dependencies import CurrentUser, DatabaseSession
from app.schemas.excel import ExcelImportResult, ExcelRead
from app.services import excel, todos

router = APIRouter(tags=["Excel"])
ExcelUpload = Annotated[UploadFile, File(description="An .xlsx workbook, up to 2 MiB")]


def upload_content(file: UploadFile) -> bytes:
    """Consume and close the temporary upload even when validation fails."""
    try:
        return excel.read_upload(file.filename, file.file)
    finally:
        file.file.close()


@router.post("/excel/read", response_model=ExcelRead)
def read_excel(file: ExcelUpload, user: CurrentUser):
    """Upload one worksheet and return its data as JSON without saving any rows.

    The first row must contain unique, nonempty text headers. Supports up to
    50 columns and 1,000 data rows. Dates become ISO strings; formulas are rejected.
    """
    return excel.read_workbook(upload_content(file))


@router.get("/todos/import/template")
def import_template(user: CurrentUser):
    return Response(
        excel.create_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="todos-template.xlsx"'},
    )


@router.post("/todos/import", response_model=ExcelImportResult, status_code=201)
def import_todos(file: ExcelUpload, db: DatabaseSession, user: CurrentUser):
    records = excel.parse_workbook(upload_content(file))
    return ExcelImportResult(imported=todos.import_todos(records, db, user))
