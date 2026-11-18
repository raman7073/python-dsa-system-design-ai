from notification_service_v4.send_context import SendContext
from notification_service_v4.send_rule import SendRule
from notification_service_v4.verdict import Verdict


class OptOutRule(SendRule):
    """A user who switched a channel off gets nothing on it, whatever the priority."""

    def _evaluate(self, ctx: SendContext) -> Verdict | None:
        channel = ctx.notification.channel
        return None if ctx.preferences.allows(channel) else Verdict.skip(f"opted out of {channel.name}")
