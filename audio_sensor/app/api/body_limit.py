"""Reject oversized request bodies before they are read.

FastAPI parses a whole multipart body before any dependency runs (login,
rate limits) and Starlette writes file parts to temporary disk with no cap,
so without this an anonymous client could fill the disk with large uploads.

The limit applies to every request; the largest legitimate body is an
upload of MAX_UPLOAD_MB plus its form fields. The exact file-size check
still happens when the upload is stored (app.storage.copy_limited).
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Room for the multipart boundaries, part headers and small form fields.
FORM_OVERHEAD_BYTES = 64 * 1024


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int, max_upload_mb: int):
        self.app = app
        self.max_bytes = max_bytes
        self.detail = f"Upload exceeds {max_upload_mb} MB."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Declared too large: refuse without reading anything.
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._reject(send)
                    return
                break

        # No (or a false) Content-Length: count what actually arrives, and
        # stop reading once over the limit.
        received = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                # FastAPI turns an error while parsing the body into its own
                # 400; answer 413 instead and drop the app's response.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": self.detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    # The client may still be sending; don't reuse this connection.
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
