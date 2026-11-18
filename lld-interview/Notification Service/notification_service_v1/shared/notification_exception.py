class NotificationException(Exception):
    """A request the service refuses: an unknown user, a duplicate account, a taken email or phone."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
