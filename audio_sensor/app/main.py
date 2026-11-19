from contextlib import asynccontextmanager

from fastapi import FastAPI
from scalar_fastapi import add_scalar_reference

from app.api.router import router
from app.audio_censor import AudioCensor
from app.config import settings
from app.database.session import init_db
from app.storage import ensure_storage_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables first: it's fast and fails immediately if the
    # database is unreachable, instead of after the slow model load below.
    init_db()
    ensure_storage_dirs()

    # One shared instance for all requests (see app.api.dependencies.get_censor).
    # Load the Whisper and alignment models now so the first request doesn't
    # pay for it.
    app.state.censor = AudioCensor(
        censor_words=settings.CENSOR_WORDS, model_name=settings.WHISPER_MODEL
    )
    app.state.censor.load_models()
    yield


app = FastAPI(
    title="Audio Censor API",
    description="Upload English audio; flagged profanity is muted or beeped out.",
    version="0.1.0",
    lifespan=lifespan,
)
add_scalar_reference(app)  # interactive API docs at /scalar
app.include_router(router)
