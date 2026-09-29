"""Application composition; HTTP behavior lives in routers and services."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import BodySizeLimitMiddleware, request_metadata
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()
    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Todo API", version="2.1.0", lifespan=lifespan)
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "X-Process-Time"],
    )
    application.middleware("http")(request_metadata)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
