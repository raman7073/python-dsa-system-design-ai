from datetime import datetime
from typing import List
import threading

from shared.active_state import ActiveState
from shared.charge import Charge
from shared.ticket_state import TicketState
from shared.ticket_status import TicketStatus
from shared.vehicle import Vehicle


class Ticket:
    """A record of one stay. Guards its lifecycle; does NOT price or charge anything."""

    def __init__(
        self,
        ticket_id: str,
        vehicle: Vehicle,
        floor_id: int,
        spot_id: str,
        entry_time: datetime,
    ) -> None:
        self._id: str = ticket_id
        self._vehicle: Vehicle = vehicle
        self._floor_id: int = floor_id
        self._spot_id: str = spot_id
        self._entry_time: datetime = entry_time
        self._extra_charges: List[Charge] = []
        self._state: TicketState = ActiveState()
        self.lock: threading.RLock = threading.RLock()  # Replaces Java's synchronized methods

    # Public actions delegate to the current state
    def can_pay(self) -> bool:
        with self.lock:
            return self._state.can_pay()

    def mark_paid(self) -> None:
        with self.lock:
            self._state.pay(self)

    def complete(self) -> None:
        with self.lock:
            self._state.exit(self)

    def add_charge(self, c: Charge) -> None:
        with self.lock:
            self._state.add_charge(self, c)

    # Used only by state classes
    def set_state(self, s: TicketState) -> None:
        with self.lock:
            self._state = s

    def add_charge_internal(self, c: Charge) -> None:
        with self.lock:
            self._extra_charges.append(c)

    @property
    def id(self) -> str:
        return self._id

    @property
    def vehicle(self) -> Vehicle:
        return self._vehicle

    @property
    def floor_id(self) -> int:
        return self._floor_id

    @property
    def spot_id(self) -> str:
        return self._spot_id

    @property
    def entry_time(self) -> datetime:
        return self._entry_time

    @property
    def status(self) -> TicketStatus:
        with self.lock:
            return self._state.status()

    def extra_charges(self) -> List[Charge]:
        with self.lock:
            # Equivalent to Java's List.copyOf(extraCharges) (returns a shallow copy)
            return list(self._extra_charges)