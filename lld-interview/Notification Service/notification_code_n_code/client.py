import logging

from api.async_notification_service import AsyncNotificationService
from api.notification_service import NotificationService
from factory.notification_channel_factory import NotificationChannelFactory
from model.channel_type import ChannelType
from model.notification import Notification
from model.user_contact import UserContact
from service.contact_service import ContactService
from service.notification_dispatcher import NotificationDispatcher
from service.user_preferences_service import UserPreferencesService


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Wiring
    preferences = UserPreferencesService()
    contacts = ContactService()
    dispatcher = NotificationDispatcher(preferences, contacts, NotificationChannelFactory.create_registry())
    service = NotificationService(dispatcher)

    # Users
    contacts.register(UserContact("alice", email="alice@example.com", device_token="alice-phone"))
    contacts.register(UserContact("bob", email="bob@example.com"))   # no phone number
    preferences.add_channel("alice", ChannelType.PUSH_NOTIFICATION)  # alice: EMAIL (default) + PUSH
    preferences.add_channel("bob", ChannelType.SMS)                  # bob: EMAIL (default) + SMS

    print("\n--- Sync: alice, all preferred channels")
    print(service.send_notification(Notification("alice", "Your order has shipped")))

    print("\n--- Sync: alice, SMS only (not opted in)")
    print(service.send_notification(Notification("alice", "OTP 1234", ChannelType.SMS)))

    print("\n--- Sync: bob, SMS opted in but no phone number")
    print(service.send_notification(Notification("bob", "Welcome!")))

    print("\n--- Sync: carol, no contact info")
    print(service.send_notification(Notification("carol", "Hello")))

    print("\n--- Async: 3 notifications")
    async_service = AsyncNotificationService(service, num_workers=2)
    ids = [
        async_service.send_notification_async(Notification(user, f"Sale starts now, {user}"))
        for user in ("alice", "bob", "alice")
    ]
    async_service.wait_until_done()
    for nid in ids:
        print(nid[:8], async_service.get_status(nid))
    async_service.shutdown()


if __name__ == "__main__":
    main()
