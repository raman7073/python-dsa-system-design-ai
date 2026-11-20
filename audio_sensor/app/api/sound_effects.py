"""Sound effects: upload your own, list them (with the built-in ones),
preview and delete. Use one with censor_mode=sound_effect and its id, on
POST /censor or PATCH /audio/{id}."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from app.api.audio import UNAUTHORIZED
from app.api.dependencies import CurrentUserDep, SoundEffectServiceDep
from app.api.rate_limit import limit_censor
from app.api.responses import download_response
from app.api.schemas import SoundEffectRead
from app.config import get_api_settings
from app.service.sound_effect_service import (
    MAX_NAME_LENGTH,
    InvalidSoundEffectError,
    SoundEffectInUseError,
    SoundEffectNameTakenError,
    SoundEffectNotFoundError,
    TooManySoundEffectsError,
)
from app.storage import SOUND_EFFECT_SUFFIXES, UploadTooLargeError

router = APIRouter(
    prefix="/sound-effects", tags=["sound effects"], responses=UNAUTHORIZED
)
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"description": "No sound effect with this ID that you can use."}
}


@router.post(
    "",
    summary="Upload a sound effect",
    status_code=status.HTTP_201_CREATED,
    response_model=SoundEffectRead,
    # Uploads share /censor's hourly budget.
    dependencies=[Depends(limit_censor)],
    responses={
        409: {
            "description": "You already have an effect with this name, or "
            f"{get_api_settings().MAX_SOUND_EFFECTS_PER_USER} effects (delete one first)."
        },
        413: {
            "description": f"The file exceeds {get_api_settings().MAX_SOUND_EFFECT_MB} MB."
        },
        422: {"description": "Bad name, or not one of the accepted audio formats."},
        429: {"description": "Hourly upload limit reached. See `Retry-After`."},
    },
)
async def create_sound_effect(
    user: CurrentUserDep,
    service: SoundEffectServiceDep,
    request: Request,
    response: Response,
    file: Annotated[
        UploadFile,
        File(
            description=f"A short audio clip: {', '.join(SOUND_EFFECT_SUFFIXES)}, at most "
            f"{get_api_settings().MAX_SOUND_EFFECT_MB} MB. It is repeated or cut to fit "
            "each censored word."
        ),
    ],
    name: Annotated[
        str,
        Form(
            min_length=1,
            max_length=MAX_NAME_LENGTH,
            description="Unique among your effects.",
        ),
    ],
) -> SoundEffectRead:
    try:
        effect = await service.create(user.id, name, file.filename, file.file)
    except InvalidSoundEffectError as exc:
        raise HTTPException(422, str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(
            413, f"Sound effect exceeds {get_api_settings().MAX_SOUND_EFFECT_MB} MB."
        ) from exc
    except (SoundEffectNameTakenError, TooManySoundEffectsError) as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Location"] = str(
        request.url_for("read_sound_effect_file", effect_id=effect.id)
    )
    return SoundEffectRead.from_effect(effect, request)


@router.get(
    "",
    summary="List the sound effects you can use",
    response_model=list[SoundEffectRead],
)
async def list_sound_effects(
    user: CurrentUserDep, service: SoundEffectServiceDep, request: Request
) -> list[SoundEffectRead]:
    """Built-in effects first, then your own, by name."""
    effects = await service.list_available(user.id)
    return [SoundEffectRead.from_effect(e, request) for e in effects]


# HEAD separately and unlisted (a shared route duplicates the operation id).
@router.head("/{effect_id}/file", include_in_schema=False)
@router.get(
    "/{effect_id}/file",
    name="read_sound_effect_file",
    summary="Download a sound effect (to preview it)",
    responses=NOT_FOUND,
)
async def read_sound_effect_file(
    effect_id: UUID, user: CurrentUserDep, service: SoundEffectServiceDep, request: Request
) -> Response:
    try:
        stored = await service.get_file(effect_id, user.id)
    except SoundEffectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return await download_response(
        stored.download, stored.media_type, stored.download_filename, request.method
    )


@router.delete(
    "/{effect_id}",
    summary="Delete one of your sound effects",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {
            "description": "No sound effect of yours with this ID (built-in ones can't be deleted)."
        },
        409: {
            "description": "Audio still being censored uses it; try again once it's done."
        },
    },
)
async def delete_sound_effect(
    effect_id: UUID, user: CurrentUserDep, service: SoundEffectServiceDep
) -> Response:
    """Finished audio keeps its censored file; its sound_effect_id becomes null."""
    try:
        await service.delete(effect_id, user.id)
    except SoundEffectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SoundEffectInUseError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
