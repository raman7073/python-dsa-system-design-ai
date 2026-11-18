from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from notification_service_v4.notification import Notification
from shared.preferences import Preferences
from shared.user import User


class SendContext:
    """
    What a rule may look at when a notification is about to go: the notification, its user, their
    preferences, the time, and how many messages the user was sent since a given instant.
    """

    def __init__(
        self,
        notification: Notification,
        user: User,
        preferences: Preferences,
        now: datetime,
        sent_to_user_since: Callable[[datetime], int],
    ) -> None:
        self.notification: Notification = notification
        self.user: User = user
        self.preferences: Preferences = preferences
        self.now: datetime = now
        self.sent_to_user_since: Callable[[datetime], int] = sent_to_user_since
