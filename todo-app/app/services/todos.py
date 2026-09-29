from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Todo, User
from app.schemas.todo import TodoPage, TodoRead, TodoWrite
from app.core.security import encrypt, decrypt

def find_todo(todo_id: int, db: Session, user: User) -> Todo:
    todo = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.owner_id == user.id))
    if todo is None:
        raise HTTPException(404, "Todo not found")
    return todo

def serialize(todo: Todo) -> TodoRead:
    return TodoRead(id=todo.id, title=todo.title, description=decrypt(todo.description_encrypted),
                    completed=todo.completed, created_at=todo.created_at, updated_at=todo.updated_at)

def new_todo(data: TodoWrite, user: User) -> Todo:
    return Todo(owner_id=user.id, title=data.title, description_encrypted=encrypt(data.description), completed=data.completed)

def create_todo(data: TodoWrite, db: Session, user: User) -> TodoRead:
    todo = new_todo(data, user)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return serialize(todo)

def save_changes(todo: Todo, changes: dict, db: Session) -> TodoRead:
    for field, value in changes.items():
        if field == "description":
            todo.description_encrypted = encrypt(value)
        else:
            setattr(todo, field, value)
    db.commit()
    db.refresh(todo)
    return serialize(todo)

def list_todos(db: Session, user: User, offset=0, limit=20, sort_by="id", order="asc", completed=None):
    filters = [Todo.owner_id == user.id]
    if completed is not None:
        filters.append(Todo.completed == completed)
    total = db.scalar(select(func.count()).select_from(Todo).where(*filters))
    column = getattr(Todo, sort_by)
    sorting = column.desc() if order == "desc" else column.asc()
    todos = db.scalars(select(Todo).where(*filters).order_by(sorting, Todo.id).offset(offset).limit(limit)).all()
    return TodoPage(items=[serialize(t) for t in todos], total=total, offset=offset, limit=limit)

def delete_todo(todo_id: int, db: Session, user: User) -> None:
    db.delete(find_todo(todo_id, db, user))
    db.commit()


def import_todos(records: list[TodoWrite], db: Session, user: User) -> int:
    db.add_all([new_todo(record, user) for record in records])
    db.commit()
    return len(records)
