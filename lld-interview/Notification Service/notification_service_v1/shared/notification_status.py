from enum import Enum


class NotificationStatus(Enum):
    """Level 1 sends at once, so a notification is either handed to the outbox or skipped with a reason."""

    SENT = "sent"
    SKIPPED = "skipped"
