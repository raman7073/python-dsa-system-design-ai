from abc import ABC, abstractmethod
from datetime import datetime, timezone


class TimeSource(ABC):
    """Where the service reads the time. Production uses the system clock; tests move a manual one."""

    @abstractmethod
    def now(self) -> datetime:
        """The current moment, in UTC."""

    @staticmethod
    def system() -> "TimeSource":
        return _SystemTimeSource()


class _SystemTimeSource(TimeSource):
    """The real clock, as a UTC datetime (Python's nearest match to Java's Instant)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
