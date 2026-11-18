from channel.notification_channel import NotificationChannel
from exceptions.notification_exception import NotificationException
from model.notification import Notification
from model.user_contact import UserContact


class EmailNotificationChannel(NotificationChannel):
    def send(self, notification: Notification, contact: UserContact) -> None:
        if not contact.email:
            raise NotificationException(f"No email address for user {contact.user_id}")
        # Call the email provider here
        print(f"[EMAIL] to {contact.email}: {notification.message}")
