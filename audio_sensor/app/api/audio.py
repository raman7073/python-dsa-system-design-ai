from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import AudioServiceDep
from app.api.schemas import AudioRead
from app.audio_censor import AudioDecodeError
from app.config import settings
from app.service.audio_service import AudioNotFoundError, AudioVariant
from app.storage import OUTPUT_MEDIA_TYPES, UploadTooLargeError

router = APIRouter(tags=["censor"])


@router.post(
    "/censor",
    summary="Censor profanity in an audio file",
    response_class=FileResponse,
    responses={
        200: {
            "description": "The censored audio file, in the upload's format "
            "(WAV if that format can't be written).",
            "content": {media_type: {} for media_type in OUTPUT_MEDIA_TYPES.values()},
            "headers": {
                "X-Audio-Id": {"description": "ID of the stored `audio` record."},
                "X-Words-Count": {"description": "Number of transcribed words."},
                "X-Flagged-Count": {"description": "Number of words censored."},
            },
        },
        400: {"description": "The upload could not be decoded as audio."},
        413: {"description": f"The upload exceeds {settings.MAX_UPLOAD_MB} MB."},
    },
)
async def censor_endpoint(
    service: AudioServiceDep,
    file: Annotated[UploadFile, File(description="Audio file (wav, mp3, flac, ogg, m4a, ...).")],
    beep: Annotated[
        bool, Form(description="Beep over flagged words instead of silencing them.")
    ] = False,
    padding_ms: Annotated[
        int, Form(ge=0, le=1000, description="Extra milliseconds muted on each side of a word.")
    ] = 150,
):
    # The service runs the CPU-heavy censoring in a worker thread, so this
    # async endpoint doesn't block the event loop.
    try:
        result = await service.censor_upload(
            file.filename, file.file, padding_ms=padding_ms, beep=beep
        )
    except UploadTooLargeError as exc:
        raise HTTPException(413, f"Upload exceeds {settings.MAX_UPLOAD_MB} MB.") from exc
    except AudioDecodeError as exc:
        raise HTTPException(400, "Could not decode the upload as audio.") from exc

    return FileResponse(
        result.censored_path,
        media_type=result.media_type,
        filename=result.download_filename,
        headers={
            "X-Audio-Id": str(result.record.id),
            "X-Words-Count": str(len(result.words)),
            "X-Flagged-Count": str(result.flagged_count),
        },
    )


@router.get(
    "/audio/{audio_id}",
    tags=["audio"],
    summary="Get a stored audio record",
    response_model=AudioRead,
    responses={404: {"description": "No audio with this ID."}},
)
async def read_audio(audio_id: UUID, service: AudioServiceDep, request: Request) -> AudioRead:
    try:
        record = await service.get_audio(audio_id)
    except AudioNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    file_url = request.url_for("read_audio_file", audio_id=record.id)
    return AudioRead(
        id=record.id,
        created_at=record.created_at,
        censored_url=str(file_url.include_query_params(variant=AudioVariant.CENSORED)),
        original_url=str(file_url.include_query_params(variant=AudioVariant.ORIGINAL)),
    )


@router.get(
    "/audio/{audio_id}/file",
    name="read_audio_file",
    tags=["audio"],
    summary="Download a stored audio file",
    response_class=FileResponse,
    responses={
        200: {"description": "The censored file (default) or the original upload."},
        404: {"description": "No audio with this ID, or its file is missing."},
    },
)
async def read_audio_file(
    audio_id: UUID,
    service: AudioServiceDep,
    variant: Annotated[
        AudioVariant, Query(description="`censored` (default) or `original`.")
    ] = AudioVariant.CENSORED,
):
    try:
        stored = await service.get_audio_file(audio_id, variant)
    except AudioNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    return FileResponse(
        stored.path, media_type=stored.media_type, filename=stored.download_filename
    )
