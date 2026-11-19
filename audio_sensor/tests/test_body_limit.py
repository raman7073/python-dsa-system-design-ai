"""Oversized bodies are refused before they are read (MAX_UPLOAD_MB is 1 in tests).

These drive the ASGI app directly, so they can count how much of the body
the app actually pulls in.
"""

from dataclasses import dataclass, field

import httpx

from app.api.body_limit import FORM_OVERHEAD_BYTES
from app.config import get_api_settings
from app.main import app

MB = 1024 * 1024
LIMIT = get_api_settings().max_upload_bytes + FORM_OVERHEAD_BYTES


@dataclass
class Exchange:
    status: int = 0
    body: bytes = b""
    bytes_read: int = 0
    messages: list[dict] = field(default_factory=list)


async def post_censor(chunks: list[bytes], content_length: int | None) -> Exchange:
    """POST /censor with no token, streaming `chunks`, and record what happens."""
    ex = Exchange()
    pending = list(chunks)

    async def receive():
        if pending:
            chunk = pending.pop(0)
            ex.bytes_read += len(chunk)
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            ex.status = message["status"]
        elif message["type"] == "http.response.body":
            ex.body += message.get("body", b"")

    headers = [(b"content-type", b"multipart/form-data; boundary=b")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/censor", "raw_path": b"/censor",
        "query_string": b"", "root_path": "", "server": ("test", 80),
        "client": ("127.0.0.1", 1234), "headers": headers,
    }
    await app(scope, receive, send)
    return ex


def multipart(size: int) -> list[bytes]:
    head = b'--b\r\nContent-Disposition: form-data; name="file"; filename="x.mp3"\r\n\r\n'
    return [head] + [b"x" * MB] * (size // MB) + [b"x" * (size % MB), b"\r\n--b--\r\n"]


async def test_declared_oversized_body_is_refused_unread() -> None:
    chunks = multipart(20 * MB)
    ex = await post_censor(chunks, content_length=sum(map(len, chunks)))

    assert ex.status == 413
    assert ex.bytes_read == 0  # not a single byte read
    assert b"Upload exceeds 1 MB." in ex.body


async def test_chunked_oversized_body_is_cut_off() -> None:
    ex = await post_censor(multipart(20 * MB), content_length=None)

    assert ex.status == 413
    assert ex.bytes_read <= LIMIT + MB  # stopped at the first chunk past the limit


async def test_body_longer_than_its_content_length_is_cut_off() -> None:
    ex = await post_censor(multipart(20 * MB), content_length=1000)  # lies

    assert ex.status == 413
    assert ex.bytes_read <= LIMIT + MB


async def test_body_within_limit_reaches_the_app() -> None:
    chunks = multipart(MB // 2)
    ex = await post_censor(chunks, content_length=sum(map(len, chunks)))

    assert ex.status == 401  # got as far as the login check
    assert ex.bytes_read == sum(map(len, chunks))


async def test_small_requests_are_unaffected(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/signup", json={"email": "ok@example.com", "password": "correct-horse-42"}
    )
    assert r.status_code == 201
