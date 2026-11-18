from channel.notification_channel import NotificationChannel
from exceptions.notification_exception import NotificationException
from model.notification import Notification
from model.user_contact import UserContact


class SmsNotificationChannel(NotificationChannel):
    def send(self, notification: Notification, contact: UserContact) -> None:
        if not contact.phone:
            raise NotificationException(f"No phone number for user {contact.user_id}")
        # Call the SMS provider here
        print(f"[SMS] to {contact.phone}: {notification.message}")
