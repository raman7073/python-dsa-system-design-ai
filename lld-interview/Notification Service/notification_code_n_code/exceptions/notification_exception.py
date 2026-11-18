class NotificationException(Exception):
    """A notification failed for a reason retrying won't fix (e.g. missing contact info)."""
