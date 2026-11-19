"""Serving stored files (audio and sound effects) from either storage backend."""

from typing import Any

from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.storage import Download


def download_response(download: Download, media_type: str, filename: str) -> Response:
    """A local file as-is, or an object-storage stream passed through (so
    download links stay behind login)."""
    if download.path is not None:
        return FileResponse(download.path, media_type=media_type, filename=filename)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if download.size is not None:
        headers["Content-Length"] = str(download.size)
    return ClosingStreamingResponse(download, media_type=media_type, headers=headers)


class ClosingStreamingResponse(StreamingResponse):
    """Streams a Download and always closes it afterwards.

    Closing inside the chunk generator isn't enough: when the client
    disconnects, Starlette abandons the generator mid-stream without closing
    it, and its background tasks are skipped too. Wrapping the whole response
    covers every ending: finished, failed, or disconnected.
    """

    def __init__(self, download: Download, **kwargs: Any):
        super().__init__(iterate_in_threadpool(download.chunks or iter(())), **kwargs)
        self._close = download.close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if self._close is not None:
                await run_in_threadpool(self._close)
