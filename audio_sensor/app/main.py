import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from scalar_fastapi import add_scalar_reference

from app.api.audio import router as audio_router
from app.api.auth import router as auth_router
from app.api.body_limit import FORM_OVERHEAD_BYTES, BodySizeLimitMiddleware
from app.api.health import router as health_router
from app.api.rate_limit import rate_limiter
from app.api.sound_effects import router as sound_effects_router
from app.config import get_api_settings
from app.database.session import check_db_schema, close_db
from app.storage import get_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fails immediately if the database is unreachable or migrations haven't
    # been applied. The Whisper models are loaded by the Celery worker, not
    # here: the API only stores uploads and queues jobs.
    await check_db_schema()
    # Fails fast if the bucket is unreachable (S3), or creates the folders.
    await asyncio.to_thread(get_storage().ensure_ready)
    yield
    await rate_limiter.close()
    await close_db()


app = FastAPI(
    title="Audio Censor API",
    description="Upload English audio; flagged profanity is muted or beeped out.",
    version="0.1.0",
    lifespan=lifespan,
)
# Outermost, so oversized bodies are refused before anything reads them.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=get_api_settings().max_upload_bytes + FORM_OVERHEAD_BYTES,
    max_upload_mb=get_api_settings().MAX_UPLOAD_MB,
)
# Added last, so it is outermost: even a 413 or 429 carries the CORS headers
# a browser needs to show the client the real error.
if get_api_settings().CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_api_settings().CORS_ORIGINS,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        # Headers clients read: the new record, the next page, when to retry,
        # and download names and sizes.
        expose_headers=[
            "Location",
            "X-Next-Cursor",
            "Retry-After",
            "Content-Disposition",
            "Content-Length",
        ],
        max_age=600,
    )
add_scalar_reference(app)  # interactive API docs at /scalar
app.include_router(audio_router)
app.include_router(auth_router)
app.include_router(sound_effects_router)
app.include_router(health_router)
