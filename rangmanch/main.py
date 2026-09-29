from contextlib import asynccontextmanager
from fastapi import FastAPI

from database import init_db,  engine
from routes.reviews import router as reviews_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("Starting up: initializing database and tables...")
    init_db()

    yield  # The application serves requests here

    # --- SHUTDOWN ---
    print("Shutting down: disposing connection pool...")
    engine.dispose()

app = FastAPI(
    title="Rangmanch API",
    description=(
        "API for Rangmanch application"
    ),
    lifespan=lifespan
)

app.include_router(reviews_router)


@app.get("/")
async def read_root():
    return {"message": "Welcome to the Rangmanch API"}
