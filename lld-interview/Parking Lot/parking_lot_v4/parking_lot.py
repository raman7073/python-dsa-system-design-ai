from datetime import datetime, timezone
from typing import Dict, List, Optional
import threading

from parking_lot_v4.ticket import Ticket
from parking_lot_v4.parking_spot import ParkingSpot
from parking_lot_v4.parking_floor import ParkingFloor
from shared.bill import Bill
from shared.charge import Charge
from shared.fee_calculator import FeeCalculator
from shared.illegal_state_exception import IllegalStateError
from shared.parking_full_exception import ParkingFullError
from shared.payment_service import PaymentService
from shared.payment_strategy import PaymentStrategy
from shared.spot_allocation_strategy import SpotAllocationStrategy
from shared.spot_size import SpotSize
from shared.vehicle import Vehicle


class ParkingLot:
    """
    Level 4: one lot, any number of floors and gates.
    Still ONE lot-level lock. Floors change the data model, not the concurrency model.
    """

    def __init__(
        self,
        floors: List[ParkingFloor],
        strategy: SpotAllocationStrategy,
        fees: FeeCalculator,
        payments: PaymentService,
        clock: datetime,
    ) -> None:
        # Sort by floor_id upon insertion so iteration is always lowest floor first (like TreeMap)
        self._floors: Dict[int, ParkingFloor] = {
            f.floor_id: f for f in sorted(floors, key=lambda fl: fl.floor_id)
        }
        self._spots_by_id: Dict[str, ParkingSpot] = {
            s.id: s for f in floors for s in f.spots
        }
        self._strategy: SpotAllocationStrategy = strategy
        self._fees: FeeCalculator = fees
        self._payments: PaymentService = payments
        self._clock:datetime = clock

        # Guarded by `_lock`, together with every floor and spot.
        self._lock: threading.RLock = threading.RLock()
        self._tickets_by_id: Dict[str, Ticket] = {}
        self._open_by_plate: Dict[str, Ticket] = {}
        self._ticket_seq: int = 0

    def park(self, v: Vehicle) -> Ticket:
        with self._lock:
            if v.plate in self._open_by_plate:
                raise IllegalStateError(f"{v.plate} is already inside")

            spot = self._find_spot_floor_by_floor(v)
            if spot is None:
                raise ParkingFullError(f"No spot for {v.type}")

            spot.occupy()
            self._ticket_seq += 1
            entry_time = self._clock
              

            t = Ticket(f"T{self._ticket_seq}", v, spot.floor_id, spot.id, entry_time)
            self._tickets_by_id[t.id] = t
            self._open_by_plate[v.plate] = t
            return t

    def _find_spot_floor_by_floor(self, v: Vehicle) -> Optional[ParkingSpot]:
        """Floor policy: lowest open floor first; the strategy picks the spot within that floor."""
        for floor in self._floors.values():
            if not floor.is_open:
                continue
            spot = self._strategy.find_spot(v, floor.spots)
            if spot is not None:
                return spot
        return None

    def unpark(self, ticket_id: str, method: PaymentStrategy) -> Bill:
        t = self._find_ticket(ticket_id)
        with t.lock:  # one payment per ticket (replaces synchronized (t))
            if not t.can_pay():
                raise IllegalStateError(f"Ticket is {t.status}")

            exit_time = self._clock
               
            
            bill = self._fees.build_bill(t, exit_time)
            self._payments.collect(bill, method)  # slow gateway call: NOT holding the lot lock
            t.mark_paid()

            with self._lock:
                self._spots_by_id[t.spot_id].free()
                del self._open_by_plate[t.vehicle.plate]

            t.complete()
            return bill

    def set_floor_open(self, floor_id: int, is_open: bool) -> None:
        """Close a floor for cleaning or an event. Parked cars can still leave; no new cars are sent there."""
        with self._lock:
            self._floor(floor_id).is_open = is_open

    def availability(self) -> Dict[int, Dict[SpotSize, int]]:
        """For the display board at the entrance: free spots per floor."""
        with self._lock:
            return {
                floor_id: f.free_counts()
                for floor_id, f in self._floors.items()
                if f.is_open
            }

    def add_charge(self, ticket_id: str, c: Charge) -> None:
        self._find_ticket(ticket_id).add_charge(c)

    def _floor(self, floor_id: int) -> ParkingFloor:
        f = self._floors.get(floor_id)
        if f is None:
            raise ValueError(f"No floor {floor_id}")
        return f

    def _find_ticket(self, ticket_id: str) -> Ticket:
        with self._lock:
            t = self._tickets_by_id.get(ticket_id)
            if t is None:
                raise ValueError(f"Unknown ticket {ticket_id}")
            return t