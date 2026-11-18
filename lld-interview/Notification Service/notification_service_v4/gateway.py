from abc import ABC, abstractmethod


class Gateway(ABC):
    """The provider behind a channel: an email API, an SMS aggregator, a push service. It can fail."""

    @abstractmethod
    def send(self, address: str, content: str) -> None:
        """Hands the message over, or raises DeliveryException."""
