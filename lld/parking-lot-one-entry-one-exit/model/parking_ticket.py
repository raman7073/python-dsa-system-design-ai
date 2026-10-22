from datetime import datetime, timezone
from uuid import uuid4

from parking_spot import ParkingSpot
from vehicle import Vehicle


class ParkingTicket:
    def __init__(self, vehicle: Vehicle, spot: ParkingSpot, entry_time: datetime) -> None:
        self.ticket_id: str = str(uuid4())
        self.vehicle: Vehicle = vehicle
        self.spot: ParkingSpot = spot
        self.entry_time: datetime = entry_time
        self.exit_time: datetime | None = None
        self.amount: int | None = None
        self.status: str = "OPEN"

    def mark_paid(self, amount: int) -> None:
        if self.status != "OPEN":
            raise ValueError("Only an open ticket can be paid")
        if amount < 0:
            raise ValueError("Payment amount cannot be negative")
        self.amount = amount
        self.status = "PAID"

    def close(self, exit_time: datetime) -> None:
        if self.status != "PAID":
            raise ValueError("Pay for the ticket before closing it")
        if exit_time.astimezone(timezone.utc) < self.entry_time.astimezone(timezone.utc):
            raise ValueError("Exit time cannot be before entry time")
        self.exit_time = exit_time
        self.status = "CLOSED"
