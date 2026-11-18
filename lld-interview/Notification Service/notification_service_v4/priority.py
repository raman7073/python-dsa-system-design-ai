from enum import Enum


class Priority(Enum):
    """
    HIGH is for messages the user is waiting for (a login code, a fraud alert): they skip quiet hours
    and rate limits and go first. LOW is for marketing.
    Listed most urgent first; the service sends in this order.
    """

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
