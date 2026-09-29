from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import CurrentUser, DatabaseSession
from app.schemas.auth import Register, Token, UserRead
from app.services import auth

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserRead, status_code=201)
def register(data: Register, db: DatabaseSession):
    return auth.register(data, db)


@router.post("/token", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DatabaseSession):
    return auth.login(form.username, form.password, db)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user
