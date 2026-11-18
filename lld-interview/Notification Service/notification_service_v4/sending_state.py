from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from notification_service_v4.notification_state import NotificationState
from notification_service_v4.notification_status import NotificationStatus

if TYPE_CHECKING:
    from notification_service_v4.notification import Notification


class SendingState(NotificationState):
    """
    Claimed by a dispatcher and being sent. Only the dispatcher's outcome can move it on; a cancel
    now is too late, because the gateway may already have the message.
    """

    INSTANCE: ClassVar[SendingState]  # the one shared object, set below

    def status(self, n: Notification) -> NotificationStatus:
        return NotificationStatus.SENDING

    def succeeded(self, n: Notification, address: str, now: datetime) -> None:
        n._count_attempt()
        n._mark_sent_at(now)
        n._finish(NotificationStatus.SENT, address)

    def failed(self, n: Notification, error: str, retry_at: datetime | None) -> None:
        n._count_attempt()
        if retry_at is None:
            n._finish(NotificationStatus.FAILED, f"{error} (gave up after {n.attempts} attempts)")
        else:
            n._reschedule(retry_at, f"{error}, retry at {retry_at}")
            n._move_to(_pending())

    def deferred(self, n: Notification, until: datetime, why: str) -> None:
        n._reschedule(until, why)
        n._move_to(_pending())

    def skipped(self, n: Notification, reason: str) -> None:
        n._finish(NotificationStatus.SKIPPED, reason)


def _pending() -> NotificationState:
    # Imported here, not at the top: pending_state.py imports this file, so a top-level import
    # would be circular.
    from notification_service_v4.pending_state import PendingState
    return PendingState.INSTANCE


SendingState.INSTANCE = SendingState()
