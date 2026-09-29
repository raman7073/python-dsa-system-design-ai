from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import init_db, engine
from routes import orders, stats


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
    title="Dabbe Wala API",
    description="API for managing orders and generating statistics.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(orders.router)
app.include_router(stats.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Dabbe Wala API!"}
