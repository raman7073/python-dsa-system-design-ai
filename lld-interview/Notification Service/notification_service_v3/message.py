class Message:
    """The words of a notification before a channel shapes them: a subject (may be None) and a body."""

    def __init__(self, subject: str | None, body: str | None) -> None:
        if body is None or not body.strip():
            raise ValueError("A notification needs a body")
        self.subject: str | None = None if subject is None or not subject.strip() else subject.strip()
        self.body: str = body.strip()
