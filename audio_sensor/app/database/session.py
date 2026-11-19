from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings

# DB_URL must use an async driver, e.g. postgresql+asyncpg://...
engine = create_async_engine(settings.DB_URL, echo=settings.DB_ECHO)

# expire_on_commit=False: keep loaded attributes usable after commit. With
# async sessions an expired attribute can't lazily reload (that would need
# an implicit await), so accessing e.g. record.id after commit would fail.
async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request (used by app.api.dependencies.SessionDep)."""
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    # create_all only knows about tables whose model classes have been
    # imported, so import the models here to register them first.
    from app.database import models  # noqa: F401

    # metadata.create_all is synchronous; run_sync runs it on the async
    # connection.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def close_db() -> None:
    """Close all pooled connections (call on app shutdown)."""
    await engine.dispose()
