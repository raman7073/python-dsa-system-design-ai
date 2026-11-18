from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from shared.channel import Channel


class NotificationRequest:
    """
    What a caller wants sent: to whom, which words (a template with values, or plain text) and on
    which channels. Made only through `Builder`, whose `build()` checks the whole request,
    so the service never sees a half-filled one.

        NotificationRequest.to("U1").template("order-shipped").param("orderId", "A-1001") \\
                           .channels(Channel.EMAIL, Channel.PUSH_NOTIFICATION).build()

    No channels means "every channel that reaches the user".
    """

    def __init__(self, builder: NotificationRequest.Builder) -> None:
        """Called by Builder.build() only; use NotificationRequest.to(...) to make a request."""
        self.user_id: str = builder._user_id
        self.template_id: str | None = builder._template_id
        self.params: Mapping[str, str] = MappingProxyType(dict(builder._params))
        self.subject: str | None = builder._subject
        self.body: str | None = builder._body
        # In Channel's own order, like Java's EnumSet. Empty means every channel that reaches the user.
        self.channels: tuple[Channel, ...] = tuple(c for c in Channel if c in builder._channels)

    @staticmethod
    def to(user_id: str | None) -> NotificationRequest.Builder:
        return NotificationRequest.Builder(user_id)

    def uses_template(self) -> bool:
        return self.template_id is not None

    class Builder:
        def __init__(self, user_id: str | None) -> None:
            self._user_id = user_id
            self._template_id: str | None = None
            self._params: dict[str, str] = {}
            self._subject: str | None = None
            self._body: str | None = None
            self._channels: set[Channel] = set()

        def template(self, id: str | None) -> NotificationRequest.Builder:
            self._template_id = id
            return self

        def param(self, name: str | None, value: str | None) -> NotificationRequest.Builder:
            if name is None or not name.strip():
                raise ValueError("A param needs a name")
            if value is None:
                raise ValueError(f"Param {name} needs a value")
            self._params[name.strip()] = value
            return self

        def text(self, subject: str | None, body: str | None) -> NotificationRequest.Builder:
            self._subject = subject
            self._body = body
            return self

        def channels(self, *chosen: Channel | None) -> NotificationRequest.Builder:
            if any(c is None for c in chosen):
                names = [None if c is None else c.name for c in chosen]
                raise ValueError(f"A None channel in {names}")
            self._channels.update(chosen)
            return self

        def build(self) -> NotificationRequest:
            if self._user_id is None or not self._user_id.strip():
                raise ValueError("A notification needs a user")
            has_text = self._body is not None or self._subject is not None
            if self._template_id is not None and has_text:
                raise ValueError("Use a template or plain text, not both")
            if self._template_id is None and not has_text:
                raise ValueError("A notification needs a template or some text")
            if self._template_id is None and self._params:
                raise ValueError("Params only make sense with a template")
            if has_text and (self._body is None or not self._body.strip()):
                raise ValueError("A notification needs a body")
            return NotificationRequest(self)
