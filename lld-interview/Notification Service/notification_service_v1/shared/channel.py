from enum import Enum

class Channel(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH_NOTIFICATION = "push_notification"
    IN_APP_MESSAGE = "in_app_message"
    WEBHOOK = "webhook"
