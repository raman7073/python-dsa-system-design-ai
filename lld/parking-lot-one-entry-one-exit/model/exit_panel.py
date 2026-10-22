from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from parking_ticket import ParkingTicket
from payment import Payment, PaymentContext, PaymentStatus, PaymentStrategy
from pricing import PricingStrategy, billable_hours, stay_duration

if TYPE_CHECKING:
    from parking_lot import ParkingLot


class ExitPanel:
    def __init__(
        self,
        exit_panel_id: str,
        lot: ParkingLot,
        pricing_strategy: PricingStrategy,
        payment_context: PaymentContext,
    ) -> None:
        self.exit_panel_id = exit_panel_id
        self.lot = lot
        self.pricing_strategy = pricing_strategy
        self.payment_context = payment_context
        self.payments = payment_context

    def check_out(
        self,
        ticket: ParkingTicket,
        method: str | PaymentStrategy,
        exit_time: datetime | None = None,
    ) -> Payment:
        if exit_time is None:
            exit_time = datetime.now(timezone.utc)
        self._check_time(exit_time)

        active_ticket = self.lot.active_tickets.get(ticket.ticket_id)
        if active_ticket is not ticket or ticket.status != "OPEN":
            raise ValueError("Ticket is not open in this parking lot")
        if ticket.spot.vehicle is not ticket.vehicle:
            raise RuntimeError("Ticket vehicle is not in its assigned spot")

        amount = self.calculate_price(ticket, exit_time)
        payment = self.payment_context.pay(ticket.ticket_id, amount, method)
        if self.payment_context.verify(payment.payment_id) != PaymentStatus.SUCCESS:
            raise RuntimeError("Payment was not successful")

        # A failed payment leaves the car parked. Vacate only after verification.
        self.lot.release_spot(ticket.spot)
        ticket.mark_paid(amount)
        ticket.close(exit_time)
        del self.lot.active_tickets[ticket.ticket_id]
        del self.lot.active_plates[ticket.vehicle.get_registration_no()]
        return payment

    def calculate_duration(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        return billable_hours(ticket, exit_time)

    def calculate_price(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        stay_duration(ticket, exit_time)
        amount = self.pricing_strategy.calculate_fee(ticket, exit_time)
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("Pricing strategy must return non-negative integer cents")
        return amount

    def _check_time(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Exit time must have a timezone")
