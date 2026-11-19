"""Opaque cursors for keyset ("seek") pagination of GET /audio.

A cursor encodes the (created_at, id) of the last record on a page; the next
page is the records ordered before it. Unlike OFFSET, the database doesn't
read and skip the earlier rows, so every page costs the same however deep.
"""

import base64
from datetime import datetime
from uuid import UUID

from app.database.models import AudioFile

Cursor = tuple[datetime, UUID]


def encode_cursor(record: AudioFile) -> str:
    raw = f"{record.created_at.isoformat()}|{record.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> Cursor:
    """Raises ValueError if `token` isn't a cursor from encode_cursor()."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        created_at, audio_id = raw.split("|")
        parsed = datetime.fromisoformat(created_at)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc
    if parsed.tzinfo is None:
        raise ValueError("Invalid cursor")
    return parsed, UUID(audio_id)
