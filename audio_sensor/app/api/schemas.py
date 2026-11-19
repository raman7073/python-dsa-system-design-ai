"""Response models for the API (what clients see, not the DB tables)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AudioRead(BaseModel):
    id: UUID
    created_at: datetime
    # Download links (GET /audio/{id}/file). Storage paths stay internal.
    censored_url: str
    original_url: str
