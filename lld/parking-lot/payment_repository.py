from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Tuple

from payment import Payment


@dataclass(frozen=True)
class PaymentRecord:
    ticket_id: str
    payment: Payment


class PaymentRepository(ABC):
    @abstractmethod
    def add(self, record: PaymentRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_by_ticket_id(self, ticket_id: str) -> Tuple[PaymentRecord, ...]:
        raise NotImplementedError


class InMemoryPaymentRepository(PaymentRepository):
    def __init__(self) -> None:
        self._records_by_ticket: Dict[str, list[PaymentRecord]] = {}
        self._lock = RLock()

    def add(self, record: PaymentRecord) -> None:
        with self._lock:
            records = self._records_by_ticket.setdefault(record.ticket_id, [])
            if any(existing.payment.payment_id == record.payment.payment_id for existing in records):
                return
            records.append(record)

    def get_by_ticket_id(self, ticket_id: str) -> Tuple[PaymentRecord, ...]:
        with self._lock:
            return tuple(self._records_by_ticket.get(ticket_id, ()))
