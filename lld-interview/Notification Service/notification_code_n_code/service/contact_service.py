from threading import Lock
from typing import Optional

from model.user_contact import UserContact


class ContactService:
    def __init__(self):
        # user_id -> UserContact
        self.__contacts: dict[str, UserContact] = {}
        self.__lock = Lock()

    def register(self, contact: UserContact) -> None:
        with self.__lock:
            self.__contacts[contact.user_id] = contact

    def get_contact(self, user_id: str) -> Optional[UserContact]:
        with self.__lock:
            return self.__contacts.get(user_id)
