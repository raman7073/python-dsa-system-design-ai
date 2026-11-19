"""FastAPI dependencies shared by the API routers."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database.models import User
from app.database.session import get_session
from app.security import InvalidTokenError, decode_access_token
from app.service.audio_service import AudioService
from app.service.sound_effect_service import SoundEffectService
from app.service.user_service import UserService
from app.worker.celery_app import enqueue_censor

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_audio_service(session: SessionDep) -> AudioService:
    """Censor jobs are queued on Redis for the Celery worker.

    In tests, override this to pass a fake queue instead:
    app.dependency_overrides[get_audio_service] = lambda: AudioService(s, fake)
    """
    return AudioService(session, enqueue_censor)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]


def get_sound_effect_service(session: SessionDep) -> SoundEffectService:
    return SoundEffectService(session)


SoundEffectServiceDep = Annotated[SoundEffectService, Depends(get_sound_effect_service)]


def get_user_service(session: SessionDep) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# Reads "Authorization: Bearer <token>". tokenUrl also wires the "Authorize"
# button in /scalar and /docs to the login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], users: UserServiceDep
) -> User:
    """The active user the bearer token belongs to, or 401.

    Add `user: CurrentUserDep` to any endpoint to require login.
    """
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise unauthorized from exc

    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
