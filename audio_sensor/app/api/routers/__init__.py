"""The API's routes, one module per resource. app.main includes `api_router`."""

from fastapi import APIRouter

from app.api.routers import audio, auth, health, sound_effects

api_router = APIRouter()
# Included in the order the API docs list them: sign up and log in, upload and
# results, sound effects, then the health check.
api_router.include_router(auth.router)
api_router.include_router(audio.router)
api_router.include_router(sound_effects.router)
api_router.include_router(health.router)
