"""FastAPI dependencies shared by the API routers."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.audio_censor import AudioCensor
from app.database.models import User
from app.database.session import get_session
from app.security import InvalidTokenError, decode_access_token
from app.service.audio_service import AudioService
from app.service.user_service import UserService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_censor(request: Request) -> AudioCensor:
    """The shared AudioCensor, created at startup in main.py's lifespan.

    In tests that skip the lifespan, override this dependency instead:
    app.dependency_overrides[get_censor] = lambda: fake_censor
    """
    censor = getattr(request.app.state, "censor", None)
    if censor is None:
        raise RuntimeError(
            "AudioCensor is not initialised: app.state.censor is set in the "
            "app's lifespan (app/main.py)."
        )
    return censor


CensorDep = Annotated[AudioCensor, Depends(get_censor)]


def get_audio_service(session: SessionDep, censor: CensorDep) -> AudioService:
    return AudioService(session, censor)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]


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
