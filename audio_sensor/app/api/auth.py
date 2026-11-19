from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import UserServiceDep
from app.api.schemas import UserCreate, UserRead
from app.service.user_service import EmailAlreadyRegisteredError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    summary="Create a user account",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    responses={
        409: {"description": "An account with this email already exists."},
        422: {"description": "Invalid email or password (see `detail`)."},
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
