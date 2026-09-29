from fastapi import APIRouter

from app.api.routes import auth, excel, health, todos

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
# Register literal import paths before /todos/{todo_id}.
api_router.include_router(excel.router)
api_router.include_router(todos.router)
