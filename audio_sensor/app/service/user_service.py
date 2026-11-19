import asyncio

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database.models import User
from app.security import hash_password


class EmailAlreadyRegisteredError(ValueError):
    """A user with this email already exists."""


class UserService:
    """User accounts. Knows nothing about HTTP."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.exec(select(User).where(User.email == email.lower()))
        return result.first()

    async def create_user(self, email: str, password: str) -> User:
        """Create a user with a hashed password.

        Raises EmailAlreadyRegisteredError if the email is taken.
        """
        email = email.lower()
        if await self.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError(email)

        # Argon2 is deliberately slow (tens of ms of CPU); keep it off the
        # event loop.
        hashed = await asyncio.to_thread(hash_password, password)

        user = User(email=email, hashed_password=hashed)
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # Two signups with the same email raced past the check above;
            # the unique index caught the second one.
            await self.session.rollback()
            raise EmailAlreadyRegisteredError(email) from exc
        return user
