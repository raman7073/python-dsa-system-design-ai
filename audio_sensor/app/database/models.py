from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class AudioFile(SQLModel, table=True):
    __tablename__ = "audio"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Relative to STORAGE_DIR, e.g. "uploads/<id>.mp3" (see app.storage).
    file_path: str
    censored_file_path: str
    # Timezone-aware (UTC): SQLModel rejects naive datetimes, and the column
    # is TIMESTAMP WITH TIME ZONE.
    created_at: datetime = Field(default_factory=utc_now)
