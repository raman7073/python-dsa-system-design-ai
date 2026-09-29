from fastapi import FastAPI
from routes.planner import router as planner_router
from routes.stream import router as stream_router

app = FastAPI(
    title="Yatra Planner API",
    description="Aggregate travel data from multiple sources to provide single plan with SSE support",
    version="1.0.0"
)

app.include_router(planner_router)
app.include_router(stream_router)


@app.get("/")
def root():
    return {"message": "Welcome to yatra planner API!"}
