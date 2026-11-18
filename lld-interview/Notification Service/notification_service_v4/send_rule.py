from __future__ import annotations

from abc import ABC, abstractmethod
from typing import final

from notification_service_v4.send_context import SendContext
from notification_service_v4.verdict import Verdict


class SendRule(ABC):
    """
    Chain of Responsibility: each rule either decides (skip or defer) or passes the notification to
    the next rule. A notification that reaches the end of the chain is allowed.

        rules = OptOutRule()
        rules.then(QuietHoursRule(...)).then(RateLimitRule(...))
    """

    def __init__(self) -> None:
        self._next: SendRule | None = None

    def then(self, next_rule: SendRule | None) -> SendRule:
        """Links the next rule and returns it, so a chain reads left to right."""
        if next_rule is None:
            raise ValueError("No rule given")
        self._next = next_rule
        return next_rule

    @final
    def check(self, ctx: SendContext) -> Verdict:
        mine = self._evaluate(ctx)
        if mine is not None:
            return mine
        return Verdict.allow() if self._next is None else self._next.check(ctx)

    @abstractmethod
    def _evaluate(self, ctx: SendContext) -> Verdict | None:
        """This rule's own decision, or None for "no objection, ask the next rule"."""
