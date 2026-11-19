from datetime import UTC, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


# Relationship loading: the app uses AsyncSession, where an unloaded
# relationship can't be fetched implicitly on attribute access. With
# "raise_on_sql", reading one that isn't loaded yet raises a clear error
# instead of the confusing MissingGreenlet; load it in the query instead:
#     select(AudioFile).options(selectinload(AudioFile.user))
#     select(User).options(selectinload(User.audios))
# It still resolves without a query when the related object is already in
# the session (e.g. the User loaded by get_current_user in the same request).
_EXPLICIT_LOAD = {"lazy": "raise_on_sql"}


class AudioFile(SQLModel, table=True):
    # SQLModel types __tablename__ as a declared_attr, so a plain string trips
    # type checkers even though it's the documented way to set the name.
    __tablename__ = "audio"  # pyright: ignore[reportAssignmentType]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Owner. Only they can read this record (see AudioService). Nullable
    # because rows created before uploads required login have no owner;
    # those rows can't be read through the API.
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    # Relative to STORAGE_DIR, e.g. "uploads/<id>.mp3" (see app.storage).
    file_path: str
    censored_file_path: str
    # Timezone-aware (UTC): SQLModel rejects naive datetimes, and the column
    # is TIMESTAMP WITH TIME ZONE.
    created_at: datetime = Field(default_factory=utc_now)

    # ORM-only (no column): the owner, via user_id. Many audio -> one user.
    # Optional["User"] (a string) because User is defined below.
    user: Optional["User"] = Relationship(
        back_populates="audios", sa_relationship_kwargs=_EXPLICIT_LOAD
    )


class User(SQLModel, table=True):
    # "user" is a reserved word in PostgreSQL, so the table is "users".
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Stored lower-cased (see UserService), so uniqueness is case-insensitive.
    email: str = Field(max_length=254, unique=True, index=True)
    # Argon2 hash; the plain password is never stored.
    hashed_password: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    # ORM-only (no column): all audio rows whose user_id is this user.
    # One user -> many audio. Not loaded with the user (every authenticated
    # request loads the user); load it explicitly when needed.
    audios: list[AudioFile] = Relationship(
        back_populates="user", sa_relationship_kwargs=_EXPLICIT_LOAD
    )
