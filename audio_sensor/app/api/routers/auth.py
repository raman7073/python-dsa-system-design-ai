from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import CurrentUserDep, UserServiceDep
from app.api.rate_limit import TOO_MANY_REQUESTS, limit_login, limit_signup
from app.api.schemas import TokenData, UserCreate, UserRead
from app.security import create_access_token
from app.service.user_service import EmailAlreadyRegisteredError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    summary="Create a user account",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    dependencies=[Depends(limit_signup)],
    responses={
        409: {"description": "An account with this email already exists."},
        422: {"description": "Invalid email or password (see `detail`)."},
        **TOO_MANY_REQUESTS,
    },
)
async def signup(body: UserCreate, users: UserServiceDep) -> UserRead:
    try:
        user = await users.create_user(body.email, body.password)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        ) from exc
    return UserRead.model_validate(user)


@router.post(
    "/login",
    summary="Log in and get an access token",
    response_model=TokenData,
    dependencies=[Depends(limit_login)],
    responses={401: {"description": "Incorrect email or password."}, **TOO_MANY_REQUESTS},
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], users: UserServiceDep
) -> TokenData:
    """OAuth2 password flow: send `username` (your email) and `password` as
    form fields (`application/x-www-form-urlencoded`).

    Use the returned token as `Authorization: Bearer <access_token>`.
    """
    user = await users.authenticate(form.username, form.password)
    if user is None:
        # One message for unknown email, wrong password and inactive account,
        # so the response doesn't reveal which emails are registered.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user.id)
    return TokenData(access_token=token, expires_in=expires_in)


@router.get(
    "/me",
    summary="Get the logged-in user",
    response_model=UserRead,
    responses={401: {"description": "Missing, invalid or expired token."}},
)
async def me(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user)
