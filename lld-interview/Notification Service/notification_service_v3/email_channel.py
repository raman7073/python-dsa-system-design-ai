from notification_service_v3.message import Message
from notification_service_v3.notification_channel import NotificationChannel
from shared.channel import Channel
from shared.user import User


class EmailChannel(NotificationChannel):
    """A subject line, a blank line, then the body. No length limit."""

    def type(self) -> Channel:
        return Channel.EMAIL

    def address_of(self, user: User) -> str | None:
        return user.email

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_email(address)

    def _format(self, message: Message) -> str:
        return f"Subject: {message.subject}\n\n{message.body}"
