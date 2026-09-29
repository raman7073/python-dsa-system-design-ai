from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DatabaseSession

router = APIRouter(tags=["Health"])


@router.get("/")
def root():
    return {"message": "Todo API", "docs": "/docs"}


@router.get("/health")
def health(db: DatabaseSession):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
