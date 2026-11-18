from shared.channel import Channel
from notification_service_v2.notification_channel import NotificationChannel
from shared.user import User


class PushChannel(NotificationChannel):
    """"Title: body", sent to the user's device token."""

    def type(self) -> Channel:
        return Channel.PUSH_NOTIFICATION

    def address_of(self, user: User) -> str | None:
        return user.device_token

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_device_token(address)

    def needs_subject(self) -> bool:
        return True

    def format(self, subject: str | None, body: str) -> str:
        return f"{subject}: {body}"
