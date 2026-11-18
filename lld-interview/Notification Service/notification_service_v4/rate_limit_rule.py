from datetime import timedelta

from notification_service_v4.priority import Priority
from notification_service_v4.send_context import SendContext
from notification_service_v4.send_rule import SendRule
from notification_service_v4.verdict import Verdict


class RateLimitRule(SendRule):
    """At most `max_count` messages per user in any `window`; past that, all but HIGH are skipped."""

    def __init__(self, max_count: int, window: timedelta | None) -> None:
        super().__init__()
        if max_count < 1 or window is None or window <= timedelta(0):
            raise ValueError("A rate limit needs a positive count and window")
        self._max_count: int = max_count
        self._window: timedelta = window

    def _evaluate(self, ctx: SendContext) -> Verdict | None:
        if ctx.notification.priority == Priority.HIGH:
            return None
        recent = ctx.sent_to_user_since(ctx.now - self._window)
        if recent < self._max_count:
            return None
        minutes = int(self._window.total_seconds() // 60)
        return Verdict.skip(f"rate limited: {self._max_count} per {minutes} min")
