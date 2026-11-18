from __future__ import annotations

from typing import TYPE_CHECKING

from notification_service_v4.notification_state import NotificationState
from notification_service_v4.notification_status import NotificationStatus

if TYPE_CHECKING:
    from notification_service_v4.notification import Notification


class DoneState(NotificationState):
    """SENT, FAILED, SKIPPED or CANCELLED. Nothing moves a finished notification: every event is refused."""

    def __init__(self, status: NotificationStatus) -> None:
        self._status: NotificationStatus = status

    def status(self, n: Notification) -> NotificationStatus:
        return self._status
