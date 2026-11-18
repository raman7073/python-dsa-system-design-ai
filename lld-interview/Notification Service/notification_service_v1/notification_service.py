from shared.channel import Channel
from shared.notification import Notification
from shared.notification_exception import NotificationException
from shared.notification_status import NotificationStatus
from shared.outbox import Outbox
from shared.preferences import Preferences
from shared.user import User

# The channels Level 1 can deliver on. The rest of Channel is not wired up yet.
_SUPPORTED_CHANNELS = (Channel.EMAIL, Channel.SMS, Channel.PUSH_NOTIFICATION)


class NotificationService:
    """
    The one entry point: register users, keep their contacts and opt-outs, send them messages.
    Every request is validated here once, so the model classes only ever see valid input.
    """

    def __init__(self, outbox: Outbox | None = None) -> None:
        self._outbox: Outbox = outbox if outbox is not None else Outbox()
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
        _check_channel(channel)
        match channel:
            case Channel.EMAIL:
                updated = old.with_email(value)
            case Channel.SMS:
                updated = old.with_phone(value)
            case _:  # PUSH_NOTIFICATION
                updated = old.with_device_token(value)
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
        _check_channel(channel)
        if body is None or not body.strip():
            raise ValueError("A notification needs a body")
        if channel != Channel.SMS and (subject is None or not subject.strip()):
            raise ValueError(f"A notification on {channel.name} needs a subject")
        clean_subject = None if subject is None else subject.strip()
        clean_body = body.strip()
        id = f"N{self._next_id}"
        self._next_id += 1

        if not self._preferences_of(user_id).allows(channel):
            return self._keep(Notification(id, user_id, channel, clean_subject, clean_body,
                                           NotificationStatus.SKIPPED, f"opted out of {channel.name}"))
        # Level 1 knows every channel by name, right here. Level 1.1 moves each case into its own class.
        match channel:
            case Channel.EMAIL:
                address = user.email
            case Channel.SMS:
                address = user.phone
            case _:  # PUSH_NOTIFICATION
                address = user.device_token
        if address is None:
            return self._keep(Notification(id, user_id, channel, clean_subject, clean_body,
                                           NotificationStatus.SKIPPED, f"no {channel.name} address"))
        match channel:
            case Channel.EMAIL:
                content = f"Subject: {clean_subject}\n\n{clean_body}"
            case Channel.SMS:
                content = clean_body if len(clean_body) <= 160 else clean_body[:157] + "..."
            case _:  # PUSH_NOTIFICATION
                content = f"{clean_subject}: {clean_body}"
        self._outbox.deliver(channel, address, content)
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

    def _preferences_of(self, user_id: str) -> Preferences:
        return self._preferences[self.user(user_id).id]

    def _keep(self, n: Notification) -> Notification:
        self._notifications[n.id] = n
        return n


def _check_channel(channel: Channel | None) -> None:
    if channel is None:
        raise ValueError("No channel given")
    if channel not in _SUPPORTED_CHANNELS:
        raise ValueError(f"Channel {channel.name} is not supported yet")
