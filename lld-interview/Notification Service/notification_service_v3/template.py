import re
from collections.abc import Mapping

from notification_service_v3.message import Message


class Template:
    """
    A reusable message with {placeholders}, such as "Hi {name}, order {orderId} has shipped".
    The text is checked when the template is made, so a typo like "{orderId" fails at start-up,
    not halfway through sending to a million users.
    """

    _ID = re.compile(r"[a-z0-9][a-z0-9-]*")
    _PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")

    def __init__(self, id: str | None, subject: str | None, body: str | None) -> None:
        if id is None or not Template._ID.fullmatch(id.strip()):
            raise ValueError(f"A template id is lower-case letters, digits and dashes, not {id}")
        if body is None or not body.strip():
            raise ValueError(f"Template {id} needs a body")
        self.id: str = id.strip()
        self.subject: str | None = None if subject is None or not subject.strip() else subject.strip()
        self.body: str = body.strip()
        names: dict[str, None] = {}  # a dict keeps first-seen order and drops repeats
        if self.subject is not None:
            names.update(dict.fromkeys(self._scan(self.subject)))
        names.update(dict.fromkeys(self._scan(self.body)))
        self.placeholders: tuple[str, ...] = tuple(names)

    def render(self, values: Mapping[str, str]) -> Message:
        """Fills every placeholder. Refuses when one has no value; extra values are ignored."""
        for name in self.placeholders:
            if name not in values:
                raise ValueError(f"Template {self.id} needs a value for {{{name}}}")
        subject = None if self.subject is None else Template._fill(self.subject, values)
        return Message(subject, Template._fill(self.body, values))

    @staticmethod
    def _fill(text: str, values: Mapping[str, str]) -> str:
        return Template._PLACEHOLDER.sub(lambda m: values[m.group(1)], text)

    def _scan(self, text: str) -> list[str]:
        """The placeholder names in the text; any brace that is not part of a clean {name} is an error."""
        names = Template._PLACEHOLDER.findall(text)
        leftover = Template._PLACEHOLDER.sub("", text)
        if "{" in leftover or "}" in leftover:
            raise ValueError(f"Template {self.id} has a broken placeholder in: {text}")
        return names
