from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from notification_service_v3.message import Message
from notification_service_v3.template import Template
from notification_service_v3.template_registry import TemplateRegistry
from notification_service_v4.delivery_exception import DeliveryException
from notification_service_v4.email_channel import EmailChannel
from notification_service_v4.exponential_backoff import ExponentialBackoff
from notification_service_v4.gateway import Gateway
from notification_service_v4.notification import Notification
from notification_service_v4.notification_channel import NotificationChannel
from notification_service_v4.notification_request import NotificationRequest
from notification_service_v4.notification_status import NotificationStatus
from notification_service_v4.opt_out_rule import OptOutRule
from notification_service_v4.priority import Priority
from notification_service_v4.push_channel import PushChannel
from notification_service_v4.quiet_hours_rule import QuietHoursRule
from notification_service_v4.rate_limit_rule import RateLimitRule
from notification_service_v4.retry_policy import RetryPolicy
from notification_service_v4.send_context import SendContext
from notification_service_v4.send_rule import SendRule
from notification_service_v4.sms_channel import SmsChannel
from notification_service_v4.time_source import TimeSource
from notification_service_v4.verdict import Verdict
from shared.channel import Channel
from shared.notification_exception import NotificationException
from shared.preferences import Preferences
from shared.user import User

# HIGH sorts before NORMAL before LOW, like comparing Java enums by their order.
_PRIORITY_RANK: dict[Priority, int] = {p: i for i, p in enumerate(Priority)}


def _dispatch_order(n: Notification) -> tuple[int, datetime, int]:
    """Due first by priority, then oldest due time, then the order they were made."""
    return (_PRIORITY_RANK[n.priority], n.due_at, n.sequence)


class NotificationService:
    """
    The one entry point: register users and templates, keep contacts and opt-outs, queue messages
    and send them when they are due. A send that fails is retried by the retry policy; a send the
    rules object to is skipped or deferred. Call `process_due()` as time passes (level 4 runs
    it on worker threads).
    """

    def __init__(
        self,
        clock: TimeSource | None,
        channel_list: list[NotificationChannel],
        rules: SendRule | None,
        retry_policy: RetryPolicy | None,
    ) -> None:
        if clock is None or rules is None or retry_policy is None:
            raise ValueError("A clock, rules and a retry policy are required")
        self._clock: TimeSource = clock
        self._rules: SendRule = rules
        self._retry_policy: RetryPolicy = retry_policy
        self._channels: dict[Channel, NotificationChannel] = {}
        for c in channel_list:
            if c.type() in self._channels:
                raise ValueError(f"Two channels for {c.type().name}")
            self._channels[c.type()] = c
        self._users: dict[str, User] = {}
        self._user_id_by_email: dict[str, str] = {}
        self._user_id_by_phone: dict[str, str] = {}
        self._preferences: dict[str, Preferences] = {}
        self._templates: TemplateRegistry = TemplateRegistry()
        self._notifications: dict[str, Notification] = {}
        self._by_idempotency_key: dict[str, list[Notification]] = {}
        self._next_id: int = 1

    @classmethod
    def standard(cls, clock: TimeSource, gateway: Gateway) -> NotificationService:
        """Email, SMS and push through one gateway, the standard rules and 3 tries a minute, 2 minutes apart."""
        channels: list[NotificationChannel] = [EmailChannel(gateway), SmsChannel(gateway), PushChannel(gateway)]
        return cls(clock, channels, cls.standard_rules(), ExponentialBackoff(3, timedelta(minutes=1)))

    @staticmethod
    def standard_rules() -> SendRule:
        """Opt-out, then quiet hours 22:00 to 08:00 India time, then at most 5 messages an hour."""
        head = OptOutRule()
        head.then(QuietHoursRule(time(22, 0), time(8, 0), ZoneInfo("Asia/Kolkata"))) \
            .then(RateLimitRule(5, timedelta(hours=1)))
        return head

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
        self._users[updated.id] = updated
        self._index(updated)
        return updated

    def opt_out(self, user_id: str, channel: Channel) -> None:
        self._preferences_of(user_id).opt_out(channel)

    def opt_in(self, user_id: str, channel: Channel) -> None:
        self._preferences_of(user_id).opt_in(channel)

    def allows(self, user_id: str, channel: Channel) -> bool:
        return self._preferences_of(user_id).allows(channel)

    # ---- templates ------------------------------------------------------------------

    def register_template(self, template: Template | None) -> None:
        self._templates.register(template)

    def template(self, id: str | None) -> Template:
        return self._templates.template(id)

    # ---- sending --------------------------------------------------------------------

    def send(self, request: NotificationRequest | None) -> list[Notification]:
        """
        Queues one notification per channel and sends the ones already due. A bad request is refused
        before anything is recorded. A repeated idempotency key returns the first request's
        notifications and sends nothing.
        """
        if request is None:
            raise ValueError("No request given")
        key = request.idempotency_key
        if key is not None and key in self._by_idempotency_key:
            return list(self._by_idempotency_key[key])

        user = self.user(request.user_id)
        message = self._message_for(request, user)
        targets = self._targets(request, user)
        for ch in targets:
            ch.check(message)  # refuse before any side effect

        now = self._clock.now()
        due = now if request.send_at is None or request.send_at < now else request.send_at
        made: list[Notification] = []
        for ch in targets:
            seq = self._next_id
            self._next_id += 1
            n = Notification(f"N{seq}", user.id, ch.type(), message, request.priority, due, seq)
            self._notifications[n.id] = n
            made.append(n)
        if key is not None:
            self._by_idempotency_key[key] = list(made)
        self.process_due()
        return made

    def send_text(self, user_id: str, channel: Channel | None, subject: str | None, body: str | None) -> Notification:
        """Plain text on one channel, now, at normal priority."""
        request = NotificationRequest.to(user_id).text(subject, body).channels(channel).build()
        return self.send(request)[0]

    def process_due(self) -> int:
        """Sends everything due now, high priority first. Returns how many were attempted."""
        now = self._clock.now()
        due = sorted((n for n in self._notifications.values() if n.is_due(now)), key=_dispatch_order)
        for n in due:
            self._dispatch(n, now)
        return len(due)

    def cancel(self, notification_id: str) -> None:
        """Stops a notification that has not gone yet. Refused once it is being sent or is finished."""
        self.notification(notification_id).cancel()

    def _dispatch(self, n: Notification, now: datetime) -> None:
        """One attempt: claim, ask the rules, try the gateway, record the outcome."""
        n.claim(now)
        user = self._users[n.user_id]
        ch = self._channels[n.channel]
        address = ch.address_of(user)
        if address is None:
            n.skipped(f"no {n.channel.name} address")
            return
        ctx = SendContext(n, user, self._preferences[user.id], now,
                          lambda since: self._sent_since(user.id, since))
        verdict = self._rules.check(ctx)
        match verdict.kind:
            case Verdict.Kind.SKIP:
                n.skipped(verdict.reason)
            case Verdict.Kind.DEFER:
                n.deferred(verdict.until, verdict.reason)
            case Verdict.Kind.ALLOW:
                try:
                    ch.deliver(address, n.message)
                    n.succeeded(address, now)
                except DeliveryException as e:
                    n.failed(str(e), self._retry_policy.next_attempt(n.attempts + 1, now))

    def _sent_since(self, user_id: str, since: datetime) -> int:
        return sum(
            1 for x in self._notifications.values()
            if x.user_id == user_id and x.status == NotificationStatus.SENT and x.sent_at >= since
        )

    def _message_for(self, request: NotificationRequest, user: User) -> Message:
        """A template is filled with the request's values; {name} is the user's name unless the caller gives one."""
        if not request.uses_template():
            return Message(request.subject, request.body)
        values = {"name": user.name, **request.params}
        return self._templates.template(request.template_id).render(values)

    def _targets(self, request: NotificationRequest, user: User) -> list[NotificationChannel]:
        """The channels asked for, or else every channel with an address the user has not switched off."""
        if request.channels:
            return [self._channel(c) for c in request.channels]
        prefs = self._preferences_of(user.id)
        # In Channel's own order, like Java's EnumMap.
        reachable = [
            self._channels[t] for t in Channel
            if t in self._channels and self._channels[t].address_of(user) is not None and prefs.allows(t)
        ]
        if not reachable:
            raise NotificationException(f"No channel reaches {user.id}")
        return reachable

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
        """Every notification for this user, oldest first, whatever its status."""
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
