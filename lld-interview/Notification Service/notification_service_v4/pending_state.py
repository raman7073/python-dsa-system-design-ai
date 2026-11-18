from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from notification_service_v4.notification_state import IllegalStateError, NotificationState
from notification_service_v4.notification_status import NotificationStatus
from notification_service_v4.sending_state import SendingState

if TYPE_CHECKING:
    from notification_service_v4.notification import Notification


class PendingState(NotificationState):
    """Waiting for its due time: QUEUED before the first try, RETRYING after a failed one."""

    INSTANCE: ClassVar[PendingState]  # the one shared object, set below

    def status(self, n: Notification) -> NotificationStatus:
        return NotificationStatus.QUEUED if n.attempts == 0 else NotificationStatus.RETRYING

    def claim(self, n: Notification, now: datetime) -> None:
        if n.due_at > now:
            raise IllegalStateError(f"{n.id} is not due until {n.due_at}")
        n._move_to(SendingState.INSTANCE)

    def cancel(self, n: Notification) -> None:
        n._finish(NotificationStatus.CANCELLED, "cancelled")


PendingState.INSTANCE = PendingState()
