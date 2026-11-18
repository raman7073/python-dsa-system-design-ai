from __future__ import annotations

from datetime import datetime
from enum import Enum


class Verdict:
    """A rule's answer: send now, never send (and why), or wait until a time."""

    class Kind(Enum):
        ALLOW = "allow"
        SKIP = "skip"
        DEFER = "defer"

    def __init__(self, kind: Verdict.Kind, reason: str | None, until: datetime | None) -> None:
        self.kind: Verdict.Kind = kind
        self.reason: str | None = reason
        self.until: datetime | None = until

    @staticmethod
    def allow() -> Verdict:
        return Verdict(Verdict.Kind.ALLOW, None, None)

    @staticmethod
    def skip(reason: str) -> Verdict:
        return Verdict(Verdict.Kind.SKIP, reason, None)

    @staticmethod
    def defer(until: datetime, reason: str) -> Verdict:
        return Verdict(Verdict.Kind.DEFER, reason, until)
