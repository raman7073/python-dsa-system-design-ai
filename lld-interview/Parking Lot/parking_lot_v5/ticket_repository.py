import threading
from typing import Dict, Optional

from parking_lot_v5.ticket import Ticket


class TicketRepository:
    """Shared by all gates. Uses a lock to make 'one open ticket per plate' atomic."""

    def __init__(self) -> None:
        self._by_id: Dict[str, Ticket] = {}
        self._open_by_plate: Dict[str, Ticket] = {}
        # One lock to protect the consistency of both dictionaries
        self._lock: threading.Lock = threading.Lock()

    def save_if_not_parked(self, t: Ticket) -> bool:
        """Equivalent to ConcurrentHashMap.putIfAbsent to ensure atomic checking and saving."""
        with self._lock:
            plate = t.vehicle.plate
            if plate in self._open_by_plate:
                return False
            
            self._open_by_plate[plate] = t
            self._by_id[t.id] = t
            return True

    def find_by_id(self, ticket_id: str) -> Optional[Ticket]:
        with self._lock:
            return self._by_id.get(ticket_id)

    def find_open_by_plate(self, plate: str) -> Optional[Ticket]:
        with self._lock:
            return self._open_by_plate.get(plate)

    def close(self, t: Ticket) -> None:
        with self._lock:
            plate = t.vehicle.plate
            # Replicates openByPlate.remove(t.vehicle().plate(), t)
            # Only remove if the current ticket for that plate is exactly this ticket 't'
            if self._open_by_plate.get(plate) is t:
                del self._open_by_plate[plate]