from datetime import datetime
from uuid import uuid4

from vehicle import Vehicle


class ParkingTicket:
    def __init__(
        self,
        vehicle: Vehicle,
        floor_number: int,
        spot_id: str,
        entry_time: datetime,
    ) -> None:
        self.ticket_id = str(uuid4())
        self.vehicle = vehicle
        self.floor_number = floor_number
        self.spot_id = spot_id
        self.entry_time = entry_time
        self.exit_time: datetime | None = None
        self.fee_cents: int | None = None

    def is_active(self) -> bool:
        return self.exit_time is None
