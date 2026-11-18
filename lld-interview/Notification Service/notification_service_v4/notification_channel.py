import sys
from abc import ABC, abstractmethod
from typing import final

from notification_service_v3.message import Message
from notification_service_v4.gateway import Gateway
from shared.channel import Channel
from shared.user import User


class NotificationChannel(ABC):
    """
    Template Method: `deliver` fixes the steps every channel follows, in this order, and each
    subclass fills in only what differs.
      1. check the message has what this channel needs (a subject?)
      2. format it the channel's way
      3. cut it to the channel's length limit, with "..."
      4. hand it to this channel's gateway
    """

    def __init__(self, gateway: Gateway | None) -> None:
        if gateway is None:
            raise ValueError("A channel needs a gateway")
        self._gateway: Gateway = gateway

    @abstractmethod
    def type(self) -> Channel: ...

    @abstractmethod
    def address_of(self, user: User) -> str | None:
        """The user's address on this channel, or None when they have none."""

    @abstractmethod
    def with_address(self, user: User, address: str | None) -> User:
        """The same user with this channel's contact changed (None or blank removes it)."""

    def _needs_subject(self) -> bool:
        """Hook: does a message on this channel need a subject? Most do."""
        return True

    def _max_length(self) -> int:
        """Hook: the longest text the gateway takes. No limit unless a channel says so."""
        return sys.maxsize

    @abstractmethod
    def _format(self, message: Message) -> str:
        """The one step every channel must write: how the text looks."""

    @final
    def check(self, message: Message) -> None:
        """Step 1 alone, so the service can refuse a bad request before anything is recorded."""
        if self._needs_subject() and message.subject is None:
            raise ValueError(f"A notification on {self.type().name} needs a subject")

    @final
    def deliver(self, address: str, message: Message) -> str:
        """
        The template method. Marked final, so no channel should skip the check or the length limit.
        Raises DeliveryException when the gateway fails.
        """
        self.check(message)
        content = self._fit(self._format(message))
        self._gateway.send(address, content)
        return content

    @final
    def _fit(self, content: str) -> str:
        limit = self._max_length()
        return content if len(content) <= limit else content[: limit - 3] + "..."
