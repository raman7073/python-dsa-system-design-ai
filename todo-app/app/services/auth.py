from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import User
from app.schemas.auth import Register, Token
from app.core.security import password_hasher, dummy_hash, create_token

def register(data: Register, db: Session) -> User:
    user = User(username=data.username, password_hash=password_hasher.hash(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username is unavailable")
    db.refresh(user)
    return user

def login(username: str, password: str, db: Session) -> Token:
    if len(password) > 128 or len(username) > 50:
        raise HTTPException(401, "Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    valid = password_hasher.verify(password, user.password_hash if user else dummy_hash)
    if not valid or user is None:
        raise HTTPException(401, "Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_token(user.id))
