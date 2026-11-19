from collections.abc import Iterator
from contextlib import contextmanager
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
from fastapi.responses import FileResponse

from app.api.dependencies import AudioServiceDep, CurrentUserDep
from app.api.pagination import decode_cursor, encode_cursor
from app.api.rate_limit import limit_censor
from app.api.responses import download_response
from app.api.schemas import AudioRead, AudioSettingsUpdate
from app.censor_words import MAX_CUSTOM_WORDS, InvalidCustomWordsError
from app.config import get_api_settings
from app.database.models import AudioStatus, CensorMode
from app.service.audio_service import (
    MAX_PADDING_MS,
    AudioNotFoundError,
    AudioNotReadyError,
    AudioVariant,
    InvalidSettingsError,
    JobBusyError,
    QueueUnavailableError,
    RerunNotPossibleError,
    SoundEffectNotFoundError,
    TooManyActiveJobsError,
)
from app.storage import UploadTooLargeError

# Every route here requires a bearer token (`user: CurrentUserDep`), and users
# only ever see their own audio.
UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing, invalid or expired token."}
}

router = APIRouter(tags=["censor"], responses=UNAUTHORIZED)

INVALID_SETTINGS = (
    "Invalid settings: bad custom words, a sound effect that isn't yours or "
    "doesn't exist, or censor_mode and sound_effect_id that don't fit together."
)
TOO_MANY = (
    "Too many requests: either the hourly rate limit, or "
    f"{get_api_settings().MAX_ACTIVE_JOBS_PER_USER} jobs already in progress (wait for one "
    "to finish). See `Retry-After`."
)


@contextmanager
def _http_errors() -> Iterator[None]:
    """Turn AudioService errors into HTTP responses (shared by the routes)."""
    try:
        yield
    except UploadTooLargeError as exc:
        raise HTTPException(
            413, f"Upload exceeds {get_api_settings().MAX_UPLOAD_MB} MB."
        ) from exc
    except (
        InvalidCustomWordsError,
        InvalidSettingsError,
        SoundEffectNotFoundError,
    ) as exc:
        raise HTTPException(422, str(exc)) from exc
    except AudioNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (JobBusyError, RerunNotPossibleError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except TooManyActiveJobsError as exc:
        raise HTTPException(
            429,
            f"You already have {exc.limit} audio files being censored; "
            "wait for one to finish.",
            # A short job takes about a minute; this is only a hint.
            headers={"Retry-After": "60"},
        ) from exc
    except QueueUnavailableError as exc:
        raise HTTPException(
            503, "The censor queue is unavailable; try again later."
        ) from exc


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
        413: {
            "description": f"The upload exceeds {get_api_settings().MAX_UPLOAD_MB} MB."
        },
        422: {"description": INVALID_SETTINGS + " Nothing was stored."},
        429: {"description": TOO_MANY},
        503: {"description": "The job queue is unavailable; nothing was stored."},
    },
)
async def censor_endpoint(
    user: CurrentUserDep,
    service: AudioServiceDep,
    request: Request,
    response: Response,
    file: Annotated[
        UploadFile, File(description="Audio file (wav, mp3, flac, ogg, m4a, ...).")
    ],
    censor_mode: Annotated[
        CensorMode | None,
        Form(
            description="What replaces flagged words: mute (default), beep, or "
            "sound_effect (with sound_effect_id)."
        ),
    ] = None,
    custom_words: Annotated[
        list[str] | None,
        Form(
            description="An extra word to censor on top of the built-in list; send the "
            f"field once per word (at most {MAX_CUSTOM_WORDS}). Single words only "
            "(letters, digits, ' and -). Whole words: 'banana' doesn't catch 'bananas'."
        ),
    ] = None,
    sound_effect_id: Annotated[
        UUID | None,
        Form(
            description="Your own sound effect or a built-in one, for censor_mode "
            "sound_effect."
        ),
    ] = None,
    beep: Annotated[
        bool, Form(description="Same as censor_mode=beep (kept for older clients).")
    ] = False,
    padding_ms: Annotated[
        int,
        Form(
            ge=0,
            le=MAX_PADDING_MS,
            description="Extra milliseconds censored on each side of a word.",
        ),
    ] = 150,
) -> AudioRead:
    # Only stores the upload and queues the job; a Celery worker does the
    # slow transcription and censoring (app.worker.tasks).
    mode = censor_mode or (CensorMode.BEEP if beep else CensorMode.MUTE)
    if beep and mode != CensorMode.BEEP:
        raise HTTPException(422, f"beep=true contradicts censor_mode={mode}.")
    with _http_errors():
        record = await service.submit_upload(
            user.id,
            file.filename,
            file.file,
            padding_ms=padding_ms,
            censor_mode=mode,
            custom_words=custom_words or (),
            sound_effect_id=sound_effect_id,
        )

    response.headers["Location"] = str(
        request.url_for("read_audio", audio_id=record.id)
    )
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
        422: {
            "description": "Invalid `before` cursor, or `before` used with `offset`."
        },
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

    records = await service.list_audios(
        user.id, limit=limit, offset=offset, before=cursor
    )
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


@router.patch(
    "/audio/{audio_id}",
    tags=["audio"],
    summary="Change a job's censor settings and re-run it",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioRead,
    # A re-run uses the worker like an upload, so it shares /censor's budget.
    dependencies=[Depends(limit_censor)],
    responses={
        200: {"description": "Nothing changed: the settings were already these."},
        202: {
            "description": "Queued (`status`: pending). New custom words re-run "
            "detection and rendering; any other change re-runs rendering only. The "
            "audio isn't transcribed again. Poll GET /audio/{id} as after an upload."
        },
        404: {"description": "No audio with this ID among your uploads."},
        409: {
            "description": "The job is still pending or processing, or it has no "
            "stored transcript to re-run from (it failed before transcription, or "
            "ran before transcripts were kept: upload it again)."
        },
        422: {"description": INVALID_SETTINGS},
        429: {"description": TOO_MANY},
        503: {"description": "The job queue is unavailable; nothing was changed."},
    },
)
async def update_audio_settings(
    audio_id: UUID,
    body: AudioSettingsUpdate,
    user: CurrentUserDep,
    service: AudioServiceDep,
    request: Request,
    response: Response,
) -> AudioRead:
    """Send only the settings to change; the rest keep their current value."""
    with _http_errors():
        # exclude_none: null means "keep" (an empty custom_words list still
        # goes through, and removes the words).
        record = await service.update_settings(
            audio_id, user.id, **body.model_dump(exclude_none=True)
        )
    if record.status != AudioStatus.PENDING:
        response.status_code = status.HTTP_200_OK  # nothing changed, nothing queued
    return AudioRead.from_record(record, request)


@router.get(
    "/audio/{audio_id}/file",
    name="read_audio_file",
    tags=["audio"],
    summary="Download a stored audio file",
    response_class=FileResponse,
    responses={
        200: {"description": "The censored file (default) or the original upload."},
        404: {
            "description": "No audio with this ID among your uploads, or its file is missing."
        },
        409: {
            "description": "The censored file isn't ready: the job is still running, or failed."
        },
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

    return download_response(stored.download, stored.media_type, stored.download_filename)
