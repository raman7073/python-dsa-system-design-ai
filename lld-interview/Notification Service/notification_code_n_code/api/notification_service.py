from exceptions.notification_exception import NotificationException
from model.channel_type import ChannelType
from model.delivery_status import DeliveryStatus
from model.notification import Notification
from service.notification_dispatcher import NotificationDispatcher


class NotificationService:
    """Synchronous API: returns once every channel has been tried."""

    def __init__(self, dispatcher: NotificationDispatcher):
        self.__dispatcher = dispatcher

    def send_notification(self, notification: Notification) -> dict[ChannelType, DeliveryStatus]:
        try:
            return self.__dispatcher.dispatch(notification)
        except NotificationException:
            raise
        except Exception as e:
            raise NotificationException(
                f"Failed to send notification {notification.notification_id}"
            ) from e
