from enum import Enum


class DeliveryStatus(Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"   # user has not opted in to this channel
