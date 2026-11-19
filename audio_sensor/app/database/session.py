from collections.abc import AsyncIterator

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import PROJECT_ROOT, settings

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


class SchemaOutOfDateError(RuntimeError):
    """The database hasn't had the latest Alembic migrations applied."""


async def check_db_schema() -> None:
    """Fail fast at startup if the database isn't at the latest migration.

    The schema is managed only by Alembic (alembic/versions); the app never
    creates or alters tables itself. Apply migrations with:
        uv run alembic upgrade head
    Also fails immediately if the database is unreachable.
    """
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()

    async with engine.connect() as conn:
        current = await conn.run_sync(
            lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
        )

    if current != head:
        raise SchemaOutOfDateError(
            f"Database schema is at revision {current or '<none>'}, but the latest "
            f"migration is {head}. Run: uv run alembic upgrade head"
        )


async def close_db() -> None:
    """Close all pooled connections (call on app shutdown)."""
    await engine.dispose()
