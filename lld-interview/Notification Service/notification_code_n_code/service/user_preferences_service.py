from threading import Lock

from model.channel_type import ChannelType
from model.preferences import UserPreferences


class UserPreferencesService:
    DEFAULT_CHANNEL = ChannelType.EMAIL

    def __init__(self):
        # user_id -> UserPreferences
        self.__preferences: dict[str, UserPreferences] = {}
        self.__lock = Lock()

    def __get_or_create(self, user_id: str) -> UserPreferences:
        # Caller must hold self.__lock.
        # New users start with the default channel (email)
        if user_id not in self.__preferences:
            self.__preferences[user_id] = UserPreferences(user_id, {self.DEFAULT_CHANNEL})
        return self.__preferences[user_id]

    def set_preferences(self, user_id: str, channels: set[ChannelType]) -> None:
        with self.__lock:
            self.__preferences[user_id] = UserPreferences(user_id, set(channels))

    def get_preferences(self, user_id: str) -> set[ChannelType]:
        with self.__lock:
            # Return a copy so callers can't mutate shared state outside the lock
            return set(self.__get_or_create(user_id).channels)

    def add_channel(self, user_id: str, channel: ChannelType) -> None:
        with self.__lock:
            self.__get_or_create(user_id).channels.add(channel)

    def remove_channel(self, user_id: str, channel: ChannelType) -> None:
        with self.__lock:
            self.__get_or_create(user_id).channels.discard(channel)
