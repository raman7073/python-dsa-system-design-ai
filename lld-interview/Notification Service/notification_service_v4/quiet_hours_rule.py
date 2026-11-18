from datetime import date, datetime, time, timedelta, tzinfo

from notification_service_v4.priority import Priority
from notification_service_v4.send_context import SendContext
from notification_service_v4.send_rule import SendRule
from notification_service_v4.verdict import Verdict


class QuietHoursRule(SendRule):
    """
    Nothing but HIGH priority between `start` and `end` local time; the rest waits for
    `end`. The window may cross midnight (22:00 to 08:00).
    """

    def __init__(self, start: time | None, end: time | None, zone: tzinfo | None) -> None:
        super().__init__()
        if start is None or end is None or zone is None or start == end:
            raise ValueError("Quiet hours need a start, a different end and a zone")
        self._start: time = start
        self._end: time = end
        self._zone: tzinfo = zone

    def _evaluate(self, ctx: SendContext) -> Verdict | None:
        if ctx.notification.priority == Priority.HIGH:
            return None
        until = self.quiet_until(ctx.now)
        return None if until is None else Verdict.defer(until, f"quiet hours until {self._end:%H:%M}")

    def quiet_until(self, now: datetime) -> datetime | None:
        """The end of the quiet window `now` falls in, or None when it is not quiet."""
        local = now.astimezone(self._zone)
        t = local.time()
        day = local.date()
        crosses_midnight = self._start > self._end
        if not crosses_midnight:
            return self._end_on(day, now) if self._start <= t < self._end else None
        if t >= self._start:
            return self._end_on(day + timedelta(days=1), now)
        if t < self._end:
            return self._end_on(day, now)
        return None

    def _end_on(self, day: date, now: datetime) -> datetime:
        """`end` o'clock on that local day, given back in the same time zone as `now`."""
        return datetime.combine(day, self._end, tzinfo=self._zone).astimezone(now.tzinfo)
