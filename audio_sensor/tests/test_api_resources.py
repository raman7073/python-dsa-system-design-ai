"""Resource handling in the API: streamed downloads are always closed, and
pooled database connections survive a Postgres restart."""

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from app.api.dependencies import get_audio_service, get_current_user
from app.database.models import User
from app.database.session import engine
from app.main import app
from app.service.audio_service import AudioVariant, StoredAudioFile
from app.storage import Download
from tests.helpers import MakeUser, helper_engine


class FakeStream:
    """An S3-like download: chunks, and a close() that must be called."""

    def __init__(self, chunks: int, delay: float = 0.0):
        self.total = chunks
        self.delay = delay
        self.sent = 0
        self.closed = False

    def chunks(self) -> Iterator[bytes]:
        for _ in range(self.total):
            if self.delay:
                import time

                time.sleep(self.delay)
            self.sent += 1
            yield b"x" * 1024

    def close(self) -> None:
        self.closed = True


def serve(stream: FakeStream) -> None:
    """Make GET /audio/{id}/file stream `stream` for a logged-in user."""

    class Service:
        async def get_audio_file(self, audio_id, owner_id, variant=AudioVariant.CENSORED):
            return StoredAudioFile(
                download=Download(chunks=stream.chunks(), size=None, close=stream.close),
                media_type="audio/mpeg",
                download_filename="a_censored.mp3",
            )

    app.dependency_overrides[get_audio_service] = lambda: Service()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid4(), email="a@example.com", hashed_password="x"
    )


def unserve() -> None:
    app.dependency_overrides.pop(get_audio_service, None)
    app.dependency_overrides.pop(get_current_user, None)


async def test_finished_download_is_closed(client: httpx.AsyncClient) -> None:
    stream = FakeStream(chunks=3)
    serve(stream)
    try:
        r = await client.get(f"/audio/{uuid4()}/file")
    finally:
        unserve()
    assert r.status_code == 200 and len(r.content) == 3 * 1024
    assert stream.closed


async def test_download_is_closed_when_the_client_disconnects() -> None:
    """Drive the ASGI app directly: the client goes away after the first chunk."""
    stream = FakeStream(chunks=1000, delay=0.01)
    serve(stream)
    first_chunk = asyncio.Event()

    async def receive():
        await first_chunk.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": f"/audio/{uuid4()}/file", "raw_path": b"/", "query_string": b"",
        "root_path": "", "server": ("test", 80), "client": ("127.0.0.1", 1),
        "headers": [],
    }
    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=10)
    finally:
        unserve()
    assert stream.closed
    assert stream.sent < stream.total  # stopped early, not read to the end


async def test_pool_survives_postgres_dropping_its_connections(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    assert (await client.get("/audio", headers=user.headers)).status_code == 200

    # What a Postgres restart does to the pooled connections.
    async with helper_engine.connect() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )

    r = await client.get("/audio", headers=user.headers)
    assert r.status_code == 200  # the stale connection was replaced, not used
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.checkedout() == 0  # nothing left checked out
