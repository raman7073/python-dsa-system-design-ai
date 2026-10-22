"""Coordinates parking, tickets, pricing, and payment."""

from datetime import datetime, timezone

from parking_floor import ParkingFloor
from parking_spot import ParkingSpot
from parking_ticket import ParkingTicket
from payment import Payment, PaymentMethod
from pricing import PricingStrategy
from spot_finder import FirstAvailableSpot
from vehicle import Vehicle


class ParkingLot:
    def __init__(
        self,
        floors: list[ParkingFloor],
        pricing: PricingStrategy,
        spot_finder: FirstAvailableSpot | None = None,
    ) -> None:
        if not floors:
            raise ValueError("A parking lot needs at least one floor")
        self.floors = list(floors)
        self.pricing = pricing
        self.spot_finder = spot_finder or FirstAvailableSpot()
        self.active_tickets: dict[str, ParkingTicket] = {}
        self.active_plates: dict[str, str] = {}
        self.payments: dict[str, Payment] = {}

    def park_vehicle(
        self, vehicle: Vehicle, entry_time: datetime | None = None
    ) -> ParkingTicket:
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        self._check_time(entry_time)

        if vehicle.license_plate in self.active_plates:
            raise ValueError("This vehicle is already parked")

        found = self.spot_finder.find(self.floors, vehicle)
        if found is None:
            raise ValueError("No suitable spot is available")

        floor, spot = found
        spot.park(vehicle)
        ticket = ParkingTicket(vehicle, floor.number, spot.spot_id, entry_time)
        self.active_tickets[ticket.ticket_id] = ticket
        self.active_plates[vehicle.license_plate] = ticket.ticket_id
        return ticket

    def exit_vehicle(
        self,
        ticket_id: str,
        payment_method: PaymentMethod,
        exit_time: datetime | None = None,
    ) -> ParkingTicket:
        if exit_time is None:
            exit_time = datetime.now(timezone.utc)
        self._check_time(exit_time)

        ticket = self.active_tickets.get(ticket_id)
        if ticket is None:
            raise ValueError("No active ticket has this ID")

        spot = self._find_spot(ticket.floor_number, ticket.spot_id)
        if spot.vehicle != ticket.vehicle:
            raise RuntimeError("The ticket and occupied spot do not match")

        fee_cents = self.pricing.calculate_fee(ticket, exit_time)
        if not isinstance(fee_cents, int) or fee_cents < 0:
            raise ValueError("Pricing must return non-negative integer cents")
        # If pay() raises an error, the vehicle remains parked.
        payment = payment_method.pay(fee_cents, ticket_id)
        if payment.amount_cents != fee_cents:
            raise ValueError("The payment amount does not match the fee")

        spot.remove_vehicle()
        ticket.exit_time = exit_time
        ticket.fee_cents = fee_cents
        self.payments[ticket_id] = payment
        del self.active_tickets[ticket_id]
        del self.active_plates[ticket.vehicle.license_plate]
        return ticket

    def payment_for_ticket(self, ticket_id: str) -> Payment | None:
        return self.payments.get(ticket_id)

    def _find_spot(self, floor_number: int, spot_id: str) -> ParkingSpot:
        for floor in self.floors:
            if floor.number == floor_number:
                spot = floor.get_spot(spot_id)
                if spot is not None:
                    return spot
        raise RuntimeError("The ticket's spot no longer exists")

    def _check_time(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Use a time with a timezone")
