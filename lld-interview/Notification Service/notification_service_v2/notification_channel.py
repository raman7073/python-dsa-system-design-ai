from abc import ABC, abstractmethod

from shared.channel import Channel
from shared.user import User


class NotificationChannel(ABC):
    """
    Everything the service needs to know about one channel: which contact on the user it uses,
    whether a message needs a subject, and how the text looks on the wire.
    """

    @abstractmethod
    def type(self) -> Channel: ...

    @abstractmethod
    def address_of(self, user: User) -> str | None:
        """The user's address on this channel, or None when they have none."""

    @abstractmethod
    def with_address(self, user: User, address: str | None) -> User:
        """The same user with this channel's contact changed (None or blank removes it)."""

    @abstractmethod
    def needs_subject(self) -> bool: ...

    @abstractmethod
    def format(self, subject: str | None, body: str) -> str:
        """The exact text handed to the gateway."""
