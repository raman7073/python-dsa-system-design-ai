from abc import ABC, abstractmethod
from datetime import datetime


class RetryPolicy(ABC):
    """When to try a failed send again. Strategy: the service asks, the policy decides."""

    @abstractmethod
    def next_attempt(self, attempts_so_far: int, now: datetime) -> datetime | None:
        """`attempts_so_far` counts the one that just failed. None means give up."""
