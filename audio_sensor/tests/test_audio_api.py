from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from app.database.models import AudioFile, AudioStatus, CensorMode
from tests.helpers import (
    FakeQueue,
    MakeUser,
    get_audio_row,
    helper_sessions,
    make_audio,
    read_stored,
    stored_keys,
)


def mp3(content: bytes = b"fake mp3 bytes") -> dict:
    return {"file": ("song.mp3", content, "audio/mpeg")}


async def test_censor_stores_upload_and_queues_job(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    r = await client.post(
        "/censor", headers=user.headers, files=mp3(), data={"beep": "true", "padding_ms": "200"}
    )

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert body["censored_url"] is None
    assert r.headers["Location"].endswith(f"/audio/{body['id']}")
    assert queue.jobs == [UUID(body["id"])]

    row = await get_audio_row(UUID(body["id"]))
    assert row is not None and row.user_id == user.id
    # Options live on the row, so a lost job can be queued again.
    assert (row.padding_ms, row.censor_mode) == (200, CensorMode.BEEP)
    assert row.queued_at is not None and row.attempts == 0
    assert row.file_path == f"uploads/{body['id']}.mp3"  # a key, not a path
    assert read_stored(row.file_path) == b"fake mp3 bytes"


async def test_censor_requires_login(client: httpx.AsyncClient, queue: FakeQueue) -> None:
    r = await client.post("/censor", files=mp3())
    assert r.status_code == 401
    assert queue.jobs == []


async def test_censor_rejects_too_large_upload(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()  # MAX_UPLOAD_MB is 1 in tests
    r = await client.post("/censor", headers=user.headers, files=mp3(b"x" * (1024 * 1024 + 1)))

    assert r.status_code == 413
    assert queue.jobs == []
    assert stored_keys("uploads") == []  # partial file removed


async def test_censor_with_queue_down_returns_503_and_keeps_nothing(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    queue.available = False
    r = await client.post("/censor", headers=user.headers, files=mp3())

    assert r.status_code == 503
    assert stored_keys("uploads") == []
    listing = await client.get("/audio", headers=user.headers)
    assert listing.json() == []


async def test_censored_file_is_409_until_completed(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.PROCESSING)

    censored = await client.get(f"/audio/{record.id}/file", headers=user.headers)
    original = await client.get(f"/audio/{record.id}/file?variant=original", headers=user.headers)

    assert censored.status_code == 409
    assert "still processing" in censored.json()["detail"]
    assert original.status_code == 200
    assert original.content == b"original audio bytes"


async def test_completed_job_can_be_downloaded(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(
        user.id, AudioStatus.COMPLETED, censored=b"beeped", words_count=5, flagged_count=2
    )

    body = (await client.get(f"/audio/{record.id}", headers=user.headers)).json()
    assert body["status"] == "completed"
    assert (body["words_count"], body["flagged_count"]) == (5, 2)
    assert body["censored_url"].endswith(f"/audio/{record.id}/file?variant=censored")

    r = await client.get(body["censored_url"].removeprefix("http://test"), headers=user.headers)
    assert r.status_code == 200
    assert r.content == b"beeped"
    assert r.headers["content-type"] == "audio/mpeg"
    assert "_censored.mp3" in r.headers["content-disposition"]


async def test_failed_job_reports_error(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.FAILED, error="Could not decode the upload as audio.")

    body = (await client.get(f"/audio/{record.id}", headers=user.headers)).json()
    assert body["status"] == "failed"
    assert body["error"] == "Could not decode the upload as audio."
    assert body["censored_url"] is None

    r = await client.get(f"/audio/{record.id}/file", headers=user.headers)
    assert r.status_code == 409
    assert "failed" in r.json()["detail"]


async def test_list_shows_only_own_audio_newest_first(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    alice, bob = await make_user(), await make_user()
    now = datetime.now(UTC)
    old = await make_audio(alice.id, created_at=now - timedelta(hours=2))
    new = await make_audio(alice.id, created_at=now)
    mid = await make_audio(alice.id, created_at=now - timedelta(hours=1))
    await make_audio(bob.id)

    r = await client.get("/audio", headers=alice.headers)
    assert [a["id"] for a in r.json()] == [str(new.id), str(mid.id), str(old.id)]

    page = await client.get("/audio?limit=1&offset=1", headers=alice.headers)
    assert [a["id"] for a in page.json()] == [str(mid.id)]


async def test_other_users_audio_is_not_found(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    owner, other = await make_user(), await make_user()
    record = await make_audio(owner.id, AudioStatus.COMPLETED, censored=b"x")

    for path in (f"/audio/{record.id}", f"/audio/{record.id}/file"):
        r = await client.get(path, headers=other.headers)
        assert r.status_code == 404, path


async def test_responses_never_expose_storage_paths(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    await make_audio(user.id, AudioStatus.COMPLETED, censored=b"x")
    r = await client.get("/audio", headers=user.headers)
    assert "uploads/" not in r.text and "censored/" not in r.text


async def test_list_pages_with_a_cursor(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    now = datetime.now(UTC)
    # Two share a timestamp: the id must break the tie without skipping one.
    created = [now - timedelta(minutes=m) for m in (0, 1, 1, 2, 3)]
    records = [await make_audio(user.id, created_at=t) for t in created]
    expected = [
        str(r.id)
        for r in sorted(records, key=lambda r: (r.created_at, r.id), reverse=True)
    ]

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2} | ({"before": cursor} if cursor else {})
        r = await client.get("/audio", headers=user.headers, params=params)
        assert r.status_code == 200
        seen += [a["id"] for a in r.json()]
        cursor = r.headers.get("X-Next-Cursor")
        if cursor is None:
            break

    assert seen == expected  # every record once, newest first


async def test_last_page_has_no_cursor(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    await make_audio(user.id)
    r = await client.get("/audio", headers=user.headers, params={"limit": 5})
    assert len(r.json()) == 1
    assert "X-Next-Cursor" not in r.headers


async def test_invalid_cursor_is_422(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    for params in ({"before": "not-a-cursor"}, {"before": "aGVsbG8", "offset": 0}):
        r = await client.get("/audio", headers=user.headers, params=params)
        assert r.status_code == 422, params
    good = (await client.get("/audio", headers=user.headers, params={"limit": 1}))
    await make_audio(user.id)
    await make_audio(user.id)
    good = await client.get("/audio", headers=user.headers, params={"limit": 1})
    r = await client.get(
        "/audio",
        headers=user.headers,
        params={"before": good.headers["X-Next-Cursor"], "offset": 1},
    )
    assert r.status_code == 422  # before and offset together


async def test_clean_job_downloads_the_original_bytes(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    """A job with nothing censored points its censored file at the upload."""
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.COMPLETED, original=b"clean audio")
    async with helper_sessions() as s:
        row = await s.get(AudioFile, record.id)
        assert row is not None
        row.censored_file_path = row.file_path
        s.add(row)
        await s.commit()

    r = await client.get(f"/audio/{record.id}/file", headers=user.headers)
    assert r.status_code == 200
    assert r.content == b"clean audio"
    assert "_censored.mp3" in r.headers["content-disposition"]
