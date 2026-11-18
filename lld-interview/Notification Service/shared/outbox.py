from shared.channel import Channel
from shared.delivery import Delivery


class Outbox:
    """
    Stands in for the real email, SMS and push gateways: it keeps every message it is given, in order,
    so the demo can print them and the tests can read them back.
    """

    def __init__(self) -> None:
        self._deliveries: list[Delivery] = []

    def deliver(self, channel: Channel, address: str, content: str) -> None:
        self._deliveries.append(Delivery(channel, address, content))

    def deliveries(self) -> list[Delivery]:
        return list(self._deliveries)

    def to(self, address: str) -> list[Delivery]:
        return [d for d in self._deliveries if d.address == address]
