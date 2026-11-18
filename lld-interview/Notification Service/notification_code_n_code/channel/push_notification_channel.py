from channel.notification_channel import NotificationChannel
from exceptions.notification_exception import NotificationException
from model.notification import Notification
from model.user_contact import UserContact


class PushNotificationChannel(NotificationChannel):
    def send(self, notification: Notification, contact: UserContact) -> None:
        if not contact.device_token:
            raise NotificationException(f"No device token for user {contact.user_id}")
        # Call the push provider here
        print(f"[PUSH] to {contact.device_token}: {notification.message}")
