from shared.channel import Channel
from notification_service_v2.notification_channel import NotificationChannel
from shared.user import User


class EmailChannel(NotificationChannel):
    """A subject line, a blank line, then the body."""

    def type(self) -> Channel:
        return Channel.EMAIL

    def address_of(self, user: User) -> str | None:
        return user.email

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_email(address)

    def needs_subject(self) -> bool:
        return True

    def format(self, subject: str | None, body: str) -> str:
        return f"Subject: {subject}\n\n{body}"
