# Using a simple mock clock or standard system datetime clock
from datetime import datetime, timezone


class SystemClock:
    @classmethod
    def instant(self) -> datetime:
                return datetime.now(timezone.utc)