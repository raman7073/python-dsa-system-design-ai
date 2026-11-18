from shared.channel import Channel
from notification_service_v2.email_channel import EmailChannel
from shared.notification import Notification
from notification_service_v2.notification_channel import NotificationChannel
from shared.notification_exception import NotificationException
from shared.notification_status import NotificationStatus
from shared.outbox import Outbox
from shared.preferences import Preferences
from notification_service_v2.push_channel import PushChannel
from notification_service_v2.sms_channel import SmsChannel
from shared.user import User


class NotificationService:
    """
    The one entry point: register users, keep their contacts and opt-outs, send them messages.
    Every request is validated here once, so the model classes only ever see valid input.
    """

    def __init__(
        self,
        outbox: Outbox | None = None,
        channel_list: list[NotificationChannel] | None = None,
    ) -> None:
        """
        The service is handed its channels; it never names one itself.
        With no channels given, it uses email, SMS (160 characters) and push.
        """
        if channel_list is None:
            channel_list = [EmailChannel(), SmsChannel(), PushChannel()]
        self._outbox: Outbox = outbox if outbox is not None else Outbox()
        self._channels: dict[Channel, NotificationChannel] = {}
        for c in channel_list:
            if c.type() in self._channels:
                raise ValueError(f"Two channels for {c.type().name}")
            self._channels[c.type()] = c
        self._users: dict[str, User] = {}
        self._user_id_by_email: dict[str, str] = {}
        self._user_id_by_phone: dict[str, str] = {}
        self._preferences: dict[str, Preferences] = {}
        self._notifications: dict[str, Notification] = {}
        self._next_id: int = 1

    # ---- users ----------------------------------------------------------------------

    def register_user(self, user: User | None) -> None:
        """One account per person: the id, the email and the phone must all be new."""
        if user is None:
            raise ValueError("No user given")
        if user.id in self._users:
            raise NotificationException(f"Duplicate user {user.id}")
        self._ensure_contacts_free(user)
        self._users[user.id] = user
        self._index(user)
        self._preferences[user.id] = Preferences()

    def update_contact(self, user_id: str, channel: Channel | None, value: str | None) -> User:
        """Changes one contact; a blank value removes it, as long as one way to reach the user is left."""
        old = self.user(user_id)
        updated = self._channel(channel).with_address(old, value)
        self._ensure_contacts_free(updated)
        self._unindex(old)
        self._users[old.id] = updated
        self._index(updated)
        return updated

    def opt_out(self, user_id: str, channel: Channel) -> None:
        self._preferences_of(user_id).opt_out(channel)

    def opt_in(self, user_id: str, channel: Channel) -> None:
        self._preferences_of(user_id).opt_in(channel)

    def allows(self, user_id: str, channel: Channel) -> bool:
        return self._preferences_of(user_id).allows(channel)

    # ---- sending --------------------------------------------------------------------

    def send(self, user_id: str, channel: Channel | None, subject: str | None, body: str | None) -> Notification:
        """
        Sends one message on one channel, now. Refuses a bad request outright; records a SKIPPED
        notification when the request is fine but this user cannot get it (opted out, no address).
        """
        user = self.user(user_id)
        user_id = user.id
        ch = self._channel(channel)
        if body is None or not body.strip():
            raise ValueError("A notification needs a body")
        if ch.needs_subject() and (subject is None or not subject.strip()):
            raise ValueError(f"A notification on {channel.name} needs a subject")
        clean_subject = None if subject is None else subject.strip()
        clean_body = body.strip()
        id = f"N{self._next_id}"
        self._next_id += 1

        if not self._preferences_of(user_id).allows(channel):
            return self._keep(Notification(id, user_id, channel, clean_subject, clean_body,
                                           NotificationStatus.SKIPPED, f"opted out of {channel.name}"))
        address = ch.address_of(user)
        if address is None:
            return self._keep(Notification(id, user_id, channel, clean_subject, clean_body,
                                           NotificationStatus.SKIPPED, f"no {channel.name} address"))
        self._outbox.deliver(channel, address, ch.format(clean_subject, clean_body))
        return self._keep(Notification(id, user_id, channel, clean_subject, clean_body,
                                       NotificationStatus.SENT, address))

    # ---- lookups --------------------------------------------------------------------

    def user(self, id: str | None) -> User:
        u = None if id is None else self._users.get(id.strip())
        if u is None:
            raise NotificationException(f"No user {id}")
        return u

    def user_by_email(self, email: str | None) -> User:
        id = self._user_id_by_email.get(User.normal_email(email))
        if id is None:
            raise NotificationException(f"No user with email {email}")
        return self._users[id]

    def user_by_phone(self, phone: str | None) -> User:
        id = self._user_id_by_phone.get(User.normal_phone(phone))
        if id is None:
            raise NotificationException(f"No user with phone {phone}")
        return self._users[id]

    def users(self) -> list[User]:
        """Every registered user, in the order they registered."""
        return list(self._users.values())

    def notification(self, id: str) -> Notification:
        n = self._notifications.get(id)
        if n is None:
            raise NotificationException(f"No notification {id}")
        return n

    def history(self, user_id: str) -> list[Notification]:
        """Everything sent or skipped for this user, oldest first."""
        id = self.user(user_id).id
        return [n for n in self._notifications.values() if n.user_id == id]

    # ---- private rules --------------------------------------------------------------

    def _ensure_contacts_free(self, u: User) -> None:
        """An email or phone may belong to one user only (the user being updated may keep their own)."""
        email_holder = None if u.email is None else self._user_id_by_email.get(u.email)
        if email_holder is not None and email_holder != u.id:
            raise NotificationException(f"Email {u.email} is already registered to {email_holder}")
        phone_holder = None if u.phone is None else self._user_id_by_phone.get(u.phone)
        if phone_holder is not None and phone_holder != u.id:
            raise NotificationException(f"Phone {u.phone} is already registered to {phone_holder}")

    def _index(self, u: User) -> None:
        if u.email is not None:
            self._user_id_by_email[u.email] = u.id
        if u.phone is not None:
            self._user_id_by_phone[u.phone] = u.id

    def _unindex(self, u: User) -> None:
        if u.email is not None:
            self._user_id_by_email.pop(u.email, None)
        if u.phone is not None:
            self._user_id_by_phone.pop(u.phone, None)

    def _channel(self, type: Channel | None) -> NotificationChannel:
        if type is None:
            raise ValueError("No channel given")
        c = self._channels.get(type)
        if c is None:
            raise NotificationException(f"No {type.name} channel is set up")
        return c

    def _preferences_of(self, user_id: str) -> Preferences:
        return self._preferences[self.user(user_id).id]

    def _keep(self, n: Notification) -> Notification:
        self._notifications[n.id] = n
        return n
