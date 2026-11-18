from abc import ABC, abstractmethod

from model.notification import Notification
from model.user_contact import UserContact


# Python's equivalent of a Java interface:
# an ABC whose methods are all @abstractmethod.
# It can't be instantiated, and a subclass can't be instantiated
# until it implements every abstract method.
class NotificationChannel(ABC):

    @abstractmethod
    def send(self, notification: Notification, contact: UserContact) -> None:
        """Deliver the notification through this channel.

        Raise NotificationException for permanent failures (no retry);
        any other exception is treated as transient and retried.
        """
        pass
