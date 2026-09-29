from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import init_db, engine
from routes import users, books


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
    title="Kitaab Exchange API",
    description="API for exchanging used books.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(users.router)
app.include_router(books.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Kitaab Exchange API!"}
