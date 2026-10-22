from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Optional

from vehicle import Vehicle


@dataclass(frozen=True)
class ParkingTicket:
    ticket_id: str
    vehicle: Vehicle
    floor_number: int
    spot_id: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    fee: Optional[Decimal] = None

    @property
    def is_active(self) -> bool:
        return self.exit_time is None

    def close(self, exit_time: datetime, fee: Decimal) -> "ParkingTicket":
        if not self.is_active:
            raise ValueError(f"Ticket {self.ticket_id} is already closed")
        return replace(self, exit_time=exit_time, fee=fee)
