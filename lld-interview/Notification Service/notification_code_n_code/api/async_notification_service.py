import logging
from queue import Queue
from threading import Lock, Thread
from typing import Optional

from api.notification_service import NotificationService
from model.channel_type import ChannelType
from model.delivery_status import DeliveryStatus
from model.notification import Notification

logger = logging.getLogger(__name__)


class AsyncNotificationService:
    """Producer-consumer: callers enqueue and return immediately; worker threads send."""

    _STOP = object()   # sentinel that tells a worker to exit

    def __init__(self, notification_service: NotificationService, num_workers: int = 4):
        self.__notification_service = notification_service
        self.__queue: Queue = Queue()
        self.__results: dict[str, Optional[dict[ChannelType, DeliveryStatus]]] = {}
        self.__lock = Lock()
        self.__workers = [
            Thread(target=self.__work, name=f"notification-worker-{i}", daemon=True)
            for i in range(num_workers)
        ]
        for worker in self.__workers:
            worker.start()

    def send_notification_async(self, notification: Notification) -> str:
        """Queue the notification and return its id straight away."""
        with self.__lock:
            self.__results[notification.notification_id] = None   # None = pending
        self.__queue.put(notification)
        return notification.notification_id

    def get_status(self, notification_id: str) -> Optional[dict[ChannelType, DeliveryStatus]]:
        """None while still pending. Raises KeyError for an unknown id."""
        with self.__lock:
            return self.__results[notification_id]

    def wait_until_done(self) -> None:
        self.__queue.join()

    def shutdown(self) -> None:
        for _ in self.__workers:
            self.__queue.put(self._STOP)
        for worker in self.__workers:
            worker.join()

    def __work(self) -> None:
        while True:
            notification = self.__queue.get()
            try:
                if notification is self._STOP:
                    return
                try:
                    result = self.__notification_service.send_notification(notification)
                except Exception:
                    logger.exception("Notification %s failed", notification.notification_id)
                    result = {}   # failed before any channel was tried
                with self.__lock:
                    self.__results[notification.notification_id] = result
            finally:
                self.__queue.task_done()
