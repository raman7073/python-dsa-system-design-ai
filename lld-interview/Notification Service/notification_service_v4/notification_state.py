from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from notification_service_v4.notification_status import NotificationStatus

if TYPE_CHECKING:
    # Only for type hints: notification.py imports the states, so a real import here would be circular.
    from notification_service_v4.notification import Notification


class IllegalStateError(RuntimeError):
    """An event the notification's current state does not allow (Java's IllegalStateException)."""


class NotificationState(ABC):
    """
    State pattern: one object per stage of a notification's life. Each event is a method; a state
    that does not allow the event keeps the default, which refuses it. So "can I cancel this?" is
    answered in one place per state, not by an if on the status in every method of Notification.
    """

    @abstractmethod
    def status(self, n: Notification) -> NotificationStatus: ...

    def claim(self, n: Notification, now: datetime) -> None:
        """A dispatcher takes a due notification to send it."""
        raise self._refused(n, "be sent")

    def succeeded(self, n: Notification, address: str, now: datetime) -> None:
        raise self._refused(n, "be marked sent")

    def failed(self, n: Notification, error: str, retry_at: datetime | None) -> None:
        """`retry_at` None means the retry policy has given up."""
        raise self._refused(n, "be marked failed")

    def deferred(self, n: Notification, until: datetime, why: str) -> None:
        """A send rule said "not now": back to waiting until the given time."""
        raise self._refused(n, "be deferred")

    def skipped(self, n: Notification, reason: str) -> None:
        """A send rule or a missing address said "never"."""
        raise self._refused(n, "be skipped")

    def cancel(self, n: Notification) -> None:
        raise self._refused(n, "be cancelled")

    def _refused(self, n: Notification, what: str) -> IllegalStateError:
        return IllegalStateError(f"{n.id} is {self.status(n).name} and cannot {what}")
