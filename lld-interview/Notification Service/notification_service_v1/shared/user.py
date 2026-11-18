import re


class User:
    """
    A person who can be notified. The id and name are required; email, phone and device token are each
    optional, but at least one must be there, or the user cannot be reached at all.
    The email is stored lower-case and the phone without spaces or dashes, so "Asha@Mail.com" and
    "asha@mail.com" are one email, and "+91 98450-12345" and "+919845012345" are one phone,
    when the service checks for a second account.
    """

    _EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
    _PHONE = re.compile(r"\+?[0-9]{10,15}")

    def __init__(
        self,
        id: str,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        device_token: str | None = None,
    ) -> None:
        self.id: str = User._required(id, "an id")
        self.name: str = User._required(name, "a name")
        self.email: str | None = User.normal_email(email)
        self.phone: str | None = User.normal_phone(phone)
        self.device_token: str | None = (
            None if device_token is None or not device_token.strip() else device_token.strip()
        )
        if self.email is None and self.phone is None and self.device_token is None:
            raise ValueError(f"User {self.id} needs at least one of email, phone or device token")

    @staticmethod
    def normal_email(raw: str | None) -> str | None:
        """The stored form of an email, or None for none. Refuses text that is not an email address."""
        if raw is None or not raw.strip():
            return None
        email = raw.strip().lower()
        if not User._EMAIL.fullmatch(email):
            raise ValueError(f"Not an email address: {raw}")
        return email

    @staticmethod
    def normal_phone(raw: str | None) -> str | None:
        """The stored form of a phone number, or None for none: digits with an optional leading +."""
        if raw is None or not raw.strip():
            return None
        phone = re.sub(r"[\s()-]", "", raw)
        if not User._PHONE.fullmatch(phone):
            raise ValueError(f"Not a phone number: {raw}")
        return phone

    def with_email(self, new_email: str | None) -> "User":
        return User(self.id, self.name, new_email, self.phone, self.device_token)

    def with_phone(self, new_phone: str | None) -> "User":
        return User(self.id, self.name, self.email, new_phone, self.device_token)

    def with_device_token(self, token: str | None) -> "User":
        return User(self.id, self.name, self.email, self.phone, token)

    @staticmethod
    def _required(value: str | None, what: str) -> str:
        if value is None or not value.strip():
            raise ValueError(f"A user needs {what}")
        return value.strip()
