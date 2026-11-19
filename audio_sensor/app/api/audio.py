from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.types import Receive, Scope, Send

from app.api.dependencies import AudioServiceDep, CurrentUserDep
from app.api.pagination import decode_cursor, encode_cursor
from app.api.rate_limit import limit_censor
from app.api.schemas import AudioRead
from app.config import get_api_settings
from app.service.audio_service import (
    AudioNotFoundError,
    AudioNotReadyError,
    AudioVariant,
    QueueUnavailableError,
    TooManyActiveJobsError,
)
from app.storage import Download, UploadTooLargeError

# Every route here requires a bearer token (`user: CurrentUserDep`), and users
# only ever see their own audio.
UNAUTHORIZED: dict[int | str, dict[str, Any]] = {401: {"description": "Missing, invalid or expired token."}}

router = APIRouter(tags=["censor"], responses=UNAUTHORIZED)


@router.post(
    "/censor",
    summary="Queue an audio file for censoring",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioRead,
    dependencies=[Depends(limit_censor)],
    responses={
        202: {
            "description": "Queued (`status`: pending). Poll the `Location` URL "
            "(GET /audio/{id}) until `status` is `completed`, then download "
            "`censored_url`. If the file isn't decodable audio, `status` becomes "
            "`failed` with an `error`.",
            "headers": {"Location": {"description": "URL of the new audio record."}},
        },
        413: {"description": f"The upload exceeds {get_api_settings().MAX_UPLOAD_MB} MB."},
        429: {
            "description": "Too many uploads: either the hourly rate limit, or "
            f"{get_api_settings().MAX_ACTIVE_JOBS_PER_USER} jobs already in progress (wait for one "
            "to finish). See `Retry-After`.",
        },
        503: {"description": "The job queue is unavailable; nothing was stored."},
    },
)
async def censor_endpoint(
    user: CurrentUserDep,
    service: AudioServiceDep,
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="Audio file (wav, mp3, flac, ogg, m4a, ...).")],
    beep: Annotated[
        bool, Form(description="Beep over flagged words instead of silencing them.")
    ] = False,
    padding_ms: Annotated[
        int, Form(ge=0, le=1000, description="Extra milliseconds muted on each side of a word.")
    ] = 150,
) -> AudioRead:
    # Only stores the upload and queues the job; a Celery worker does the
    # slow transcription and censoring (app.worker.tasks).
    try:
        record = await service.submit_upload(
            user.id, file.filename, file.file, padding_ms=padding_ms, beep=beep
        )
    except UploadTooLargeError as exc:
        raise HTTPException(413, f"Upload exceeds {get_api_settings().MAX_UPLOAD_MB} MB.") from exc
    except TooManyActiveJobsError as exc:
        raise HTTPException(
            429,
            f"You already have {exc.limit} audio files being censored; "
            "wait for one to finish.",
            # A short job takes about a minute; this is only a hint.
            headers={"Retry-After": "60"},
        ) from exc
    except QueueUnavailableError as exc:
        raise HTTPException(503, "The censor queue is unavailable; try again later.") from exc

    response.headers["Location"] = str(request.url_for("read_audio", audio_id=record.id))
    return AudioRead.from_record(record, request)


@router.get(
    "/audio",
    tags=["audio"],
    summary="List your stored audio records",
    response_model=list[AudioRead],
    responses={
        200: {
            "headers": {
                "X-Next-Cursor": {
                    "description": "Pass as `before` to get the next page. "
                    "Absent on the last page."
                }
            }
        },
        422: {"description": "Invalid `before` cursor, or `before` used with `offset`."},
    },
)
async def list_audio(
    user: CurrentUserDep,
    service: AudioServiceDep,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100, description="Records per page.")] = 50,
    before: Annotated[
        str | None,
        Query(description="Cursor from the previous page's `X-Next-Cursor` header."),
    ] = None,
    offset: Annotated[
        int, Query(ge=0, description="Records to skip. Prefer `before` for deep pages.")
    ] = 0,
) -> list[AudioRead]:
    """Every audio record you uploaded, newest first. Empty list if none.

    For the next page, pass the `X-Next-Cursor` response header back as
    `before` (it stays fast however deep you page; `offset` slows down).
    """
    cursor = None
    if before is not None:
        if offset:
            raise HTTPException(422, "Use either `before` or `offset`, not both.")
        try:
            cursor = decode_cursor(before)
        except ValueError as exc:
            raise HTTPException(422, "Invalid `before` cursor.") from exc

    records = await service.list_audios(user.id, limit=limit, offset=offset, before=cursor)
    if len(records) == limit:
        response.headers["X-Next-Cursor"] = encode_cursor(records[-1])
    return [AudioRead.from_record(record, request) for record in records]


@router.get(
    "/audio/{audio_id}",
    tags=["audio"],
    summary="Get a stored audio record",
    response_model=AudioRead,
    responses={404: {"description": "No audio with this ID among your uploads."}},
)
async def read_audio(
    audio_id: UUID, user: CurrentUserDep, service: AudioServiceDep, request: Request
) -> AudioRead:
    try:
        record = await service.get_audio(audio_id, user.id)
    except AudioNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return AudioRead.from_record(record, request)


@router.get(
    "/audio/{audio_id}/file",
    name="read_audio_file",
    tags=["audio"],
    summary="Download a stored audio file",
    response_class=FileResponse,
    responses={
        200: {"description": "The censored file (default) or the original upload."},
        404: {"description": "No audio with this ID among your uploads, or its file is missing."},
        409: {"description": "The censored file isn't ready: the job is still running, or failed."},
    },
)
async def read_audio_file(
    audio_id: UUID,
    user: CurrentUserDep,
    service: AudioServiceDep,
    variant: Annotated[
        AudioVariant, Query(description="`censored` (default) or `original`.")
    ] = AudioVariant.CENSORED,
):
    try:
        stored = await service.get_audio_file(audio_id, user.id, variant)
    except AudioNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except AudioNotReadyError as exc:
        raise HTTPException(409, str(exc)) from exc

    if stored.download.path is not None:
        return FileResponse(
            stored.download.path, media_type=stored.media_type, filename=stored.download_filename
        )
    # Object storage: stream it through, so download links stay behind login.
    headers = {"Content-Disposition": f'attachment; filename="{stored.download_filename}"'}
    if stored.download.size is not None:
        headers["Content-Length"] = str(stored.download.size)
    return ClosingStreamingResponse(
        stored.download, media_type=stored.media_type, headers=headers
    )


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
