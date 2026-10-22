from datetime import datetime, timezone
from dataclasses import dataclass
from decimal import Decimal
from threading import RLock
from typing import Dict, Optional, Sequence
from uuid import uuid4

from parking_floor import ParkingFloor
from parking_spot import ParkingSpot
from parking_ticket import ParkingTicket
from payment import PaymentDeclinedError, PaymentStrategy
from payment_repository import (
    InMemoryPaymentRepository,
    PaymentRecord,
    PaymentRepository,
)
from payment_service import PaymentService
from pricing import PricingStrategy
from spot_allocation import (
    FirstAvailableSpotAllocationStrategy,
    SpotAllocationStrategy,
)
from vehicle import Vehicle


@dataclass(frozen=True)
class _PendingExit:
    exit_time: datetime
    fee: Decimal
    payment_strategy: PaymentStrategy | None


class ParkingLot:
    def __init__(
        self,
        floors: Sequence[ParkingFloor],
        pricing_strategy: PricingStrategy,
        allocation_strategy: Optional[SpotAllocationStrategy] = None,
        payment_repository: Optional[PaymentRepository] = None,
    ) -> None:
        if not floors:
            raise ValueError("A parking lot must have at least one floor")
        floor_numbers = [floor.floor_number for floor in floors]
        if len(floor_numbers) != len(set(floor_numbers)):
            raise ValueError("Floor numbers must be unique")
        if any(spot.is_occupied for floor in floors for spot in floor.spots):
            raise ValueError("A new parking lot cannot start with untracked occupied spots")
        # Own the spot state; caller-owned floors must not be able to change it.
        self._floors = self._copy_floors(floors)
        self._pricing_strategy = pricing_strategy
        self._allocation_strategy = (
            allocation_strategy
            if allocation_strategy is not None
            else FirstAvailableSpotAllocationStrategy()
        )
        self._payment_service = PaymentService(
            payment_repository if payment_repository is not None else InMemoryPaymentRepository()
        )
        self._active_tickets: Dict[str, ParkingTicket] = {}
        self._active_plates: Dict[str, str] = {}
        self._pending_exits: Dict[str, _PendingExit] = {}
        self._processing_exits: set[str] = set()
        self._lock = RLock()

    @property
    def floors(self) -> Sequence[ParkingFloor]:
        with self._lock:
            return self._copy_floors(self._floors)

    def park_vehicle(
        self, vehicle: Vehicle, entry_time: Optional[datetime] = None
    ) -> ParkingTicket:
        entry_time = entry_time or datetime.now(timezone.utc)
        self._validate_timestamp(entry_time)

        with self._lock:
            if vehicle.license_plate in self._active_plates:
                raise ValueError(
                    f"Vehicle {vehicle.license_plate} already has an active ticket"
                )

            available_floors = self._copy_floors(self._floors)
            allocation = self._allocation_strategy.find_spot(available_floors, vehicle)
            if allocation is None:
                raise RuntimeError("No available spot can fit this vehicle")
            if not any(allocation.floor is floor for floor in available_floors):
                raise RuntimeError("Allocation strategy returned a floor outside this lot")
            if not any(allocation.spot is spot for spot in allocation.floor.spots):
                raise RuntimeError("Allocation strategy returned a spot outside its floor")
            floor = self._find_floor(allocation.floor.floor_number)
            spot = floor.get_spot(allocation.spot.spot_id)
            if spot is None or spot.is_occupied or not spot.can_fit_vehicle(vehicle):
                raise RuntimeError("Allocation strategy returned an unusable spot")

            ticket = ParkingTicket(
                ticket_id=str(uuid4()),
                vehicle=vehicle,
                floor_number=floor.floor_number,
                spot_id=spot.spot_id,
                entry_time=entry_time,
            )
            spot.park(vehicle)
            self._active_tickets[ticket.ticket_id] = ticket
            self._active_plates[vehicle.license_plate] = ticket.ticket_id
            return ticket

    def exit_vehicle(
        self,
        ticket_id: str,
        payment_strategy: PaymentStrategy,
        exit_time: Optional[datetime] = None,
    ) -> ParkingTicket:
        exit_time = exit_time or datetime.now(timezone.utc)
        self._validate_timestamp(exit_time)

        with self._lock:
            try:
                ticket = self._active_tickets[ticket_id]
            except KeyError as error:
                raise ValueError(f"No active ticket found: {ticket_id}") from error
            if ticket_id in self._processing_exits:
                raise RuntimeError("Exit is already in progress for this ticket")

            spot = self._find_ticket_spot(ticket)
            if spot.vehicle != ticket.vehicle:
                raise RuntimeError(
                    f"Parking spot {ticket.spot_id} no longer contains "
                    f"the vehicle on ticket {ticket.ticket_id}"
                )

            pending = self._pending_exits.get(ticket_id)
            if pending is None:
                fee = self._pricing_strategy.calculate_fee(
                    ticket.entry_time, exit_time, ticket.vehicle
                )
                if not isinstance(fee, Decimal) or not fee.is_finite():
                    raise TypeError("Pricing strategy must return a finite Decimal fee")
                if fee < 0 or fee != fee.quantize(Decimal("0.01")):
                    raise ValueError("Pricing strategy must return non-negative whole cents")
                pending = _PendingExit(exit_time, fee, payment_strategy)
                self._pending_exits[ticket_id] = pending
            elif pending.payment_strategy is None:
                pending = _PendingExit(pending.exit_time, pending.fee, payment_strategy)
                self._pending_exits[ticket_id] = pending
            self._processing_exits.add(ticket_id)

        try:
            assert pending.payment_strategy is not None
            self._payment_service.collect(
                ticket_id, pending.fee, pending.payment_strategy
            )
        except BaseException as error:
            with self._lock:
                if isinstance(error, PaymentDeclinedError):
                    self._pending_exits[ticket_id] = _PendingExit(
                        pending.exit_time, pending.fee, None
                    )
                self._processing_exits.remove(ticket_id)
            raise

        with self._lock:
            spot.remove_vehicle()
            completed = ticket.close(exit_time=pending.exit_time, fee=pending.fee)
            del self._active_tickets[ticket.ticket_id]
            del self._active_plates[ticket.vehicle.license_plate]
            del self._pending_exits[ticket_id]
            self._processing_exits.remove(ticket_id)
            return completed

    def payments_for_ticket(self, ticket_id: str) -> Sequence[PaymentRecord]:
        return self._payment_service.for_ticket(ticket_id)

    @staticmethod
    def _copy_floors(floors: Sequence[ParkingFloor]) -> tuple[ParkingFloor, ...]:
        return tuple(
            ParkingFloor(
                floor.floor_number,
                [
                    ParkingSpot(
                        spot.spot_id, spot.spot_type, spot.vehicle, spot.fit_policy
                    )
                    for spot in floor.spots
                ],
            )
            for floor in floors
        )

    def _find_floor(self, floor_number: int) -> ParkingFloor:
        floor = next(
            (floor for floor in self._floors if floor.floor_number == floor_number),
            None,
        )
        if floor is None:
            raise RuntimeError(f"Ticket references missing floor {floor_number}")
        return floor

    def _find_ticket_spot(self, ticket: ParkingTicket) -> ParkingSpot:
        floor = self._find_floor(ticket.floor_number)
        spot = floor.get_spot(ticket.spot_id)
        if spot is None:
            raise RuntimeError(f"Ticket references missing spot {ticket.spot_id}")
        return spot

    @staticmethod
    def _validate_timestamp(timestamp: datetime) -> None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Timestamps must include a timezone")
