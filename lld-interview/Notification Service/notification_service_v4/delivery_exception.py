class DeliveryException(Exception):
    """The gateway did not take the message: a timeout, a 5xx, a carrier outage. Worth retrying."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
