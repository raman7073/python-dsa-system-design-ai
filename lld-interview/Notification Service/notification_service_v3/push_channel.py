from notification_service_v3.message import Message
from notification_service_v3.notification_channel import NotificationChannel
from shared.channel import Channel
from shared.user import User


class PushChannel(NotificationChannel):
    """"Title: body", sent to the user's device token; a lock screen shows about 120 characters."""

    def type(self) -> Channel:
        return Channel.PUSH_NOTIFICATION

    def address_of(self, user: User) -> str | None:
        return user.device_token

    def with_address(self, user: User, address: str | None) -> User:
        return user.with_device_token(address)

    def _max_length(self) -> int:
        return 120

    def _format(self, message: Message) -> str:
        return f"{message.subject}: {message.body}"
