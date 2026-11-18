from shared.channel import Channel


class Delivery:
    """One message handed to a gateway: the channel, where it goes and the exact text sent."""

    def __init__(self, channel: Channel, address: str, content: str) -> None:
        self.channel: Channel = channel
        self.address: str = address
        self.content: str = content
