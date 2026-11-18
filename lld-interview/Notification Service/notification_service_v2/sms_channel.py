from shared.channel import Channel
from notification_service_v2.notification_channel import NotificationChannel
from shared.user import User


class SmsChannel(NotificationChannel):
    """The body only, cut to the carrier's limit with "..." when it is longer."""

    def __init__(self, max_length: int = 160) -> None:
        if max_length < 4:
            raise ValueError('An SMS limit must leave room for text and "..."')
        self._max_length: int = max_length

    def type(self) -> Channel:
        return Channel.SMS

    def address_of(self, user: User) -> str | None:
        return user.phone

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_phone(address)

    def needs_subject(self) -> bool:
        return False

    def format(self, subject: str | None, body: str) -> str:
        if len(body) <= self._max_length:
            return body
        return body[: self._max_length - 3] + "..."
