from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.config import settings

engine = create_engine(settings.DB_URL, echo=settings.DB_ECHO)


def get_session():
    """One session per request (used by app.api.dependencies.SessionDep)."""
    with Session(engine) as session:
        yield session


def init_db():
    # create_all only knows about tables whose model classes have been
    # imported, so import the models here to register them first.
    from app.database import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
