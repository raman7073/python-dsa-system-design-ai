import asyncio
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database.models import User
from app.security import burn_dummy_verify, hash_password, verify_and_update_password


class EmailAlreadyRegisteredError(ValueError):
    """A user with this email already exists."""


class UserService:
    """User accounts. Knows nothing about HTTP."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        # scalar(): first column of the first row, or None. Emails are unique
        # (unique index on users.email), so there is at most one row.
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def authenticate(self, email: str, password: str) -> User | None:
        """The active user with these credentials, or None.

        Unknown email, wrong password and inactive account all return None,
        so callers can't tell them apart (no account enumeration).
        """
        user = await self.get_by_email(email)
        if user is None:
            # Same cost as a real check, so timing doesn't reveal the email
            # isn't registered.
            await asyncio.to_thread(burn_dummy_verify, password)
            return None

        valid, new_hash = await asyncio.to_thread(
            verify_and_update_password, password, user.hashed_password
        )
        if not valid or not user.is_active:
            return None

        if new_hash is not None:
            # Hashing parameters were upgraded since this password was set;
            # store the stronger hash now that we have the plain password.
            user.hashed_password = new_hash
            self.session.add(user)
            await self.session.commit()
        return user

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
