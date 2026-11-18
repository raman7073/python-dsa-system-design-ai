from notification_service_v3.message import Message
from notification_service_v4.gateway import Gateway
from notification_service_v4.notification_channel import NotificationChannel
from shared.channel import Channel
from shared.user import User


class SmsChannel(NotificationChannel):
    """The body only (a subject is dropped), cut to the carrier's limit."""

    def __init__(self, gateway: Gateway | None, max_length: int = 160) -> None:
        super().__init__(gateway)
        if max_length < 4:
            raise ValueError('An SMS limit must leave room for text and "..."')
        self._limit: int = max_length

    def type(self) -> Channel:
        return Channel.SMS

    def address_of(self, user: User) -> str | None:
        return user.phone

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_phone(address)

    def _needs_subject(self) -> bool:
        return False

    def _max_length(self) -> int:
        return self._limit

    def _format(self, message: Message) -> str:
        return message.body
