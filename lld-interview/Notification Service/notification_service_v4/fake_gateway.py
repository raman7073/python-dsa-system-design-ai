import threading

from notification_service_v4.delivery import Delivery
from notification_service_v4.delivery_exception import DeliveryException
from notification_service_v4.gateway import Gateway


class FakeGateway(Gateway):
    """
    Stands in for a real provider. It keeps every message it accepts, in order, and can be told to
    fail the next few sends, or every send until it is brought back up.
    """

    def __init__(self, name: str = "gateway") -> None:
        self._name: str = name
        self._deliveries: list[Delivery] = []
        self._failures_to_come: int = 0
        self._down: bool = False
        self._lock = threading.Lock()  # plays the part of Java's synchronized

    def send(self, address: str, content: str) -> None:
        with self._lock:
            if self._down:
                raise DeliveryException(f"{self._name} is down")
            if self._failures_to_come > 0:
                self._failures_to_come -= 1
                raise DeliveryException(f"{self._name} timed out")
            self._deliveries.append(Delivery(address, content))

    def fail_next(self, times: int) -> None:
        with self._lock:
            self._failures_to_come = times

    def set_down(self, is_down: bool) -> None:
        with self._lock:
            self._down = is_down

    def deliveries(self) -> list[Delivery]:
        with self._lock:
            return list(self._deliveries)

    def to(self, address: str) -> list[Delivery]:
        with self._lock:
            return [d for d in self._deliveries if d.address == address]
