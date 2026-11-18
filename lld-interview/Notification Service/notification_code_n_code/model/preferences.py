from dataclasses import dataclass

from model.channel_type import ChannelType


@dataclass
class UserPreferences:
    """Not thread-safe on its own; UserPreferencesService guards access with a lock."""
    user_id: str
    channels: set[ChannelType]
