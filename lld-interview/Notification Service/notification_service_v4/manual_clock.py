import threading
from datetime import datetime, timedelta

from notification_service_v4.time_source import TimeSource


class ManualClock(TimeSource):
    """A clock that moves only when told to, so retries and quiet hours can be tested without waiting."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("Give the start time a time zone, e.g. tzinfo=timezone.utc")
        self._now: datetime = start
        self._lock = threading.Lock()  # plays the part of Java's synchronized

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, by: timedelta) -> None:
        if by < timedelta(0):
            raise ValueError("Time does not go backwards")
        with self._lock:
            self._now += by
