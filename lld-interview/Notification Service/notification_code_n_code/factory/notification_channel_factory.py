from channel.email_notification_channel import EmailNotificationChannel
from channel.notification_channel import NotificationChannel
from channel.push_notification_channel import PushNotificationChannel
from channel.sms_notification_channel import SmsNotificationChannel
from model.channel_type import ChannelType


class NotificationChannelFactory:
    # Adding a channel = one new class + one line here. Nothing else changes.
    _CHANNELS: dict[ChannelType, type[NotificationChannel]] = {
        ChannelType.EMAIL: EmailNotificationChannel,
        ChannelType.SMS: SmsNotificationChannel,
        ChannelType.PUSH_NOTIFICATION: PushNotificationChannel,
    }

    @classmethod
    def create_channel(cls, channel_type: ChannelType) -> NotificationChannel:
        channel_cls = cls._CHANNELS.get(channel_type)
        if channel_cls is None:
            raise ValueError(f"Unsupported channel type: {channel_type}")
        return channel_cls()

    @classmethod
    def create_registry(cls) -> dict[ChannelType, NotificationChannel]:
        """One shared instance per channel type, for the dispatcher."""
        return {channel_type: cls.create_channel(channel_type) for channel_type in cls._CHANNELS}
