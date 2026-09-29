from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, DatabaseSession
from app.schemas.todo import TodoPage, TodoPatch, TodoRead, TodoWrite
from app.services import todos

router = APIRouter(prefix="/todos", tags=["Todos"])


@router.post("", response_model=TodoRead, status_code=201)
def create_todo(data: TodoWrite, db: DatabaseSession, user: CurrentUser):
    return todos.create_todo(data, db, user)


@router.get("", response_model=TodoPage)
def list_todos(
    db: DatabaseSession,
    user: CurrentUser,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Literal["id", "title", "created_at", "updated_at", "completed"] = "id",
    order: Literal["asc", "desc"] = "asc",
    completed: bool | None = None,
):
    return todos.list_todos(db, user, offset, limit, sort_by, order, completed)


@router.get("/{todo_id}", response_model=TodoRead)
def read_todo(todo_id: int, db: DatabaseSession, user: CurrentUser):
    return todos.serialize(todos.find_todo(todo_id, db, user))


@router.put("/{todo_id}", response_model=TodoRead)
def update_todo(todo_id: int, data: TodoWrite, db: DatabaseSession, user: CurrentUser):
    return todos.save_changes(todos.find_todo(todo_id, db, user), data.model_dump(), db)


@router.patch("/{todo_id}", response_model=TodoRead)
def patch_todo(todo_id: int, data: TodoPatch, db: DatabaseSession, user: CurrentUser):
    return todos.save_changes(
        todos.find_todo(todo_id, db, user), data.model_dump(exclude_unset=True), db
    )


@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: int, db: DatabaseSession, user: CurrentUser):
    todos.delete_todo(todo_id, db, user)
    return Response(status_code=204)
