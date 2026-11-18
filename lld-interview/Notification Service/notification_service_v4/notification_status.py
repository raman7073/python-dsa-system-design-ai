from enum import Enum


class NotificationStatus(Enum):
    """
    QUEUED waits for its time; SENDING is with a gateway right now; RETRYING failed and waits to try
    again. The other four are final.
    """

    QUEUED = "queued"
    SENDING = "sending"
    RETRYING = "retrying"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    def is_final(self) -> bool:
        return self in (NotificationStatus.SENT, NotificationStatus.FAILED,
                        NotificationStatus.SKIPPED, NotificationStatus.CANCELLED)
