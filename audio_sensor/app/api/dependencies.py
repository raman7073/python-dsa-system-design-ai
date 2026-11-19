"""FastAPI dependencies shared by the API routers."""

from typing import Annotated

from fastapi import Depends, Request
from sqlmodel import Session

from app.audio_censor import AudioCensor
from app.database.session import get_session
from app.service.audio_service import AudioService

SessionDep = Annotated[Session, Depends(get_session)]


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
