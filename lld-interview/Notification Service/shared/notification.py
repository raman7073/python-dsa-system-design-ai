from shared.channel import Channel
from shared.notification_status import NotificationStatus


class Notification:
    """
    What happened to one message on one channel. When it was sent, `detail` is the address it
    went to; when it was skipped, `detail` says why.
    """

    def __init__(
        self,
        id: str,
        user_id: str,
        channel: Channel,
        subject: str | None,
        body: str,
        status: NotificationStatus,
        detail: str,
    ) -> None:
        self.id: str = id
        self.user_id: str = user_id
        self.channel: Channel = channel
        self.subject: str | None = subject
        self.body: str = body
        self.status: NotificationStatus = status
        self.detail: str = detail

    def __str__(self) -> str:
        return f"{self.id} {self.channel.name} to {self.user_id} {self.status.name} ({self.detail})"
