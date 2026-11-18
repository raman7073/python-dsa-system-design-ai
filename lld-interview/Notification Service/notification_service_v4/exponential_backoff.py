from datetime import datetime, timedelta

from notification_service_v4.retry_policy import RetryPolicy


class ExponentialBackoff(RetryPolicy):
    """Waits first, 2 x first, 4 x first ... between tries, and gives up after max_attempts tries in all."""

    def __init__(self, max_attempts: int, first: timedelta | None) -> None:
        if max_attempts < 1:
            raise ValueError("At least one attempt")
        if first is None or first <= timedelta(0):
            raise ValueError("The first wait must be positive")
        self._max_attempts: int = max_attempts
        self._first: timedelta = first

    def next_attempt(self, attempts_so_far: int, now: datetime) -> datetime | None:
        if attempts_so_far >= self._max_attempts:
            return None
        return now + self._first * (1 << (attempts_so_far - 1))
