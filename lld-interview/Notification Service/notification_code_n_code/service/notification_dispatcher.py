import logging
import time
from typing import Optional

from channel.notification_channel import NotificationChannel
from exceptions.notification_exception import NotificationException
from model.channel_type import ChannelType
from model.delivery_status import DeliveryStatus
from model.notification import Notification
from model.user_contact import UserContact
from service.contact_service import ContactService
from service.user_preferences_service import UserPreferencesService

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(
        self,
        preferences_service: UserPreferencesService,
        contact_service: ContactService,
        channels: dict[ChannelType, NotificationChannel],
        max_attempts: int = 3,
        base_delay_seconds: float = 0.1,
    ):
        self.__preferences_service = preferences_service
        self.__contact_service = contact_service
        self.__channels = channels          # registry: no if/elif per channel type
        self.__max_attempts = max_attempts
        self.__base_delay_seconds = base_delay_seconds

    def dispatch(self, notification: Notification) -> dict[ChannelType, DeliveryStatus]:
        preferred = self.__preferences_service.get_preferences(notification.user_id)

        if notification.channel_type is None:
            targets = preferred
        elif notification.channel_type in preferred:
            targets = {notification.channel_type}
        else:
            # Opting out is a normal outcome, not an error
            return {notification.channel_type: DeliveryStatus.SKIPPED}

        contact = self.__contact_service.get_contact(notification.user_id)
        return {
            channel_type: self.__deliver(channel_type, notification, contact)
            for channel_type in sorted(targets, key=lambda c: c.value)
        }

    def __deliver(
        self,
        channel_type: ChannelType,
        notification: Notification,
        contact: Optional[UserContact],
    ) -> DeliveryStatus:
        nid = notification.notification_id
        channel = self.__channels.get(channel_type)
        if channel is None:
            logger.error("%s: no channel registered for %s", nid, channel_type)
            return DeliveryStatus.FAILED
        if contact is None:
            logger.error("%s: no contact info for user %s", nid, notification.user_id)
            return DeliveryStatus.FAILED

        for attempt in range(1, self.__max_attempts + 1):
            try:
                channel.send(notification, contact)
                return DeliveryStatus.SENT
            except NotificationException as e:
                # Permanent failure: retrying won't help
                logger.error("%s: %s failed: %s", nid, channel_type, e)
                return DeliveryStatus.FAILED
            except Exception as e:
                # Transient failure (provider down, timeout): retry with exponential backoff
                logger.warning("%s: %s attempt %d/%d failed: %s",
                               nid, channel_type, attempt, self.__max_attempts, e)
                if attempt < self.__max_attempts:
                    time.sleep(self.__base_delay_seconds * 2 ** (attempt - 1))
        return DeliveryStatus.FAILED
