from datetime import datetime

from notification_service_v3.message import Message
from notification_service_v4.done_state import DoneState
from notification_service_v4.notification_state import NotificationState
from notification_service_v4.notification_status import NotificationStatus
from notification_service_v4.pending_state import PendingState
from notification_service_v4.priority import Priority
from shared.channel import Channel


class Notification:
    """
    One message to one user on one channel, and where it is in its life. Every event is handed to
    the current NotificationState, which allows it or refuses it.

      QUEUED --claim--> SENDING --succeeded--> SENT
         ^                 |  \\--failed, retry--> RETRYING --claim--> SENDING ...
         |                 |   \\-failed, give up-> FAILED
         +---deferred------+    \\-skipped--------> SKIPPED
      QUEUED or RETRYING --cancel--> CANCELLED
    """

    def __init__(
        self,
        id: str,
        user_id: str,
        channel: Channel,
        message: Message,
        priority: Priority,
        due_at: datetime,
        sequence: int,
    ) -> None:
        self.id: str = id
        self.user_id: str = user_id
        self.channel: Channel = channel
        self.message: Message = message
        self.priority: Priority = priority
        self.sequence: int = sequence
        self._state: NotificationState = PendingState.INSTANCE
        self._due_at: datetime = due_at
        self._sent_at: datetime | None = None
        self._attempts: int = 0
        self._detail: str = f"due at {due_at}"

    # ---- events: each one asks the state --------------------------------------------

    def claim(self, now: datetime) -> None:
        self._state.claim(self, now)

    def succeeded(self, address: str, now: datetime) -> None:
        self._state.succeeded(self, address, now)

    def failed(self, error: str, retry_at: datetime | None) -> None:
        self._state.failed(self, error, retry_at)

    def deferred(self, until: datetime, why: str) -> None:
        self._state.deferred(self, until, why)

    def skipped(self, reason: str) -> None:
        self._state.skipped(self, reason)

    def cancel(self) -> None:
        self._state.cancel(self)

    # ---- what the states change (only the state classes call these) -----------------

    def _move_to(self, next: NotificationState) -> None:
        self._state = next

    def _finish(self, status: NotificationStatus, why: str) -> None:
        self._detail = why
        self._state = DoneState(status)

    def _reschedule(self, at: datetime, why: str) -> None:
        self._due_at = at
        self._detail = why

    def _count_attempt(self) -> None:
        self._attempts += 1

    def _mark_sent_at(self, at: datetime) -> None:
        self._sent_at = at

    # ---- reads (read-only from outside) ----------------------------------------------

    @property
    def status(self) -> NotificationStatus:
        return self._state.status(self)

    @property
    def due_at(self) -> datetime:
        return self._due_at

    @property
    def sent_at(self) -> datetime | None:
        """When the gateway took it, or None."""
        return self._sent_at

    @property
    def attempts(self) -> int:
        """How many times a gateway was tried."""
        return self._attempts

    @property
    def detail(self) -> str:
        """The address when sent; otherwise why it is waiting, failed or skipped."""
        return self._detail

    def is_due(self, now: datetime) -> bool:
        return self.status in (NotificationStatus.QUEUED, NotificationStatus.RETRYING) and self._due_at <= now

    def __str__(self) -> str:
        return f"{self.id} {self.channel.name} to {self.user_id} {self.status.name} ({self._detail})"
