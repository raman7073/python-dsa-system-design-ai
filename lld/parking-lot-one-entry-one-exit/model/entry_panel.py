from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from parking_ticket import ParkingTicket
from parking_spot import ParkingSpot
from vehicle import Vehicle

if TYPE_CHECKING:
    from parking_lot import ParkingLot


class EntryPanel:
    def __init__(self, entry_panel_id: str, lot: ParkingLot) -> None:
        self.entry_panel_id = entry_panel_id
        self.lot = lot

    def check_in(
        self, vehicle: Vehicle, entry_time: datetime | None = None
    ) -> ParkingTicket:
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        self._check_time(entry_time)

        plate = vehicle.get_registration_no()
        if plate in self.lot.active_plates:
            raise ValueError("Vehicle is already parked")

        allocation = self.lot.allocate_spot(vehicle)
        if allocation is None:
            raise ValueError("No suitable spot is available")

        floor, spot = allocation
        ticket = self.generate_ticket(vehicle, spot, entry_time)
        self.lot.active_tickets[ticket.ticket_id] = ticket
        self.lot.active_plates[plate] = ticket.ticket_id
        return ticket

    def generate_ticket(
        self, vehicle: Vehicle, spot: ParkingSpot, entry_time: datetime
    ) -> ParkingTicket:
        return ParkingTicket(vehicle, spot, entry_time)

    def _check_time(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Entry time must have a timezone")
