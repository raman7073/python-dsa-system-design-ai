class Delivery:
    """One message a gateway accepted: where it went and the exact text."""

    def __init__(self, address: str, content: str) -> None:
        self.address: str = address
        self.content: str = content
