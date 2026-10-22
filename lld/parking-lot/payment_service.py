from decimal import Decimal

from payment import PaymentStrategy
from payment_repository import PaymentRecord, PaymentRepository


class PaymentService:
    """Collect and record one payment for a ticket, including retries."""

    def __init__(self, repository: PaymentRepository) -> None:
        self._repository = repository

    def collect(
        self, ticket_id: str, amount: Decimal, strategy: PaymentStrategy
    ) -> PaymentRecord:
        existing = self._repository.get_by_ticket_id(ticket_id)
        if existing:
            record = existing[0]
            if record.payment.amount != amount:
                raise RuntimeError("Recorded payment does not match the exit fee")
            return record

        payment = strategy.process_payment(amount, idempotency_key=ticket_id)
        if payment.amount != amount or payment.payment_id != ticket_id:
            raise RuntimeError("Payment strategy returned an invalid payment")
        record = PaymentRecord(ticket_id=ticket_id, payment=payment)
        self._repository.add(record)
        return record

    def for_ticket(self, ticket_id: str) -> tuple[PaymentRecord, ...]:
        return self._repository.get_by_ticket_id(ticket_id)
