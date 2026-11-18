import uuid
from dataclasses import dataclass, field
from typing import Optional

from model.channel_type import ChannelType


@dataclass(frozen=True)
class Notification:
    """Immutable, so it can't change while it's queued or being sent."""
    user_id: str
    message: str
    # None -> send on every channel the user prefers.
    # Set  -> send only on this channel, and only if the user opted in.
    channel_type: Optional[ChannelType] = None
    notification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
