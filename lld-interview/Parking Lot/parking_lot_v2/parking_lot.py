from datetime import datetime, timezone
from typing import Dict, List, Optional

from parking_lot_v2.parking_floor import ParkingFloor
from parking_lot_v2.parking_spot import ParkingSpot
from parking_lot_v2.ticket import Ticket
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
    Facade over floors, tickets, pricing and payment.

    THREADING CONTRACT: single-threaded. Every call comes from one thread (one event loop
    handling all gates), so there are no locks and plain dicts/TreeMaps are correct.
    This class is NOT thread-safe; if that assumption changes, add one lot-level lock here.
    """

    def __init__(
        self,
        floors: List[ParkingFloor],
        strategy: SpotAllocationStrategy,
        fees: FeeCalculator,
        payments: PaymentService,
        clock: datetime,  # Or a Clock protocol/type if defined
    ) -> None:
        # Using a dictionary sorted by floor ID to mimic a TreeMap (lowest floor first)
        self._floors: Dict[int, ParkingFloor] = {}
        self._spots_by_id: Dict[str, ParkingSpot] = {}
        self._tickets_by_id: Dict[str, Ticket] = {}
        self._open_by_plate: Dict[str, Ticket] = {}
        
        for f in floors:
            self._floors[f.floor_id] = f
            for s in f.spots:
                self._spots_by_id[s.id] = s

        self._strategy: SpotAllocationStrategy = strategy
        self._fees: FeeCalculator = fees
        self._payments: PaymentService = payments
        self._clock: datetime = clock
        self._ticket_seq: int = 0

    def park(self, v: Vehicle) -> Ticket:
        if v.plate in self._open_by_plate:
            raise IllegalStateError(f"{v.plate} is already inside")

        spot = self._find_spot(v)
        if spot is None:
            raise ParkingFullError(f"No spot for {v.type}")

        spot.occupy()

        self._ticket_seq += 1
        ticket_id = f"T{self._ticket_seq}"
        
        entry_time = self._clock() 

        t = Ticket(ticket_id, v, spot.floor_id, spot.id, entry_time)
        self._tickets_by_id[t.id] = t
        self._open_by_plate[v.plate] = t
        return t

    def unpark(self, ticket_id: str, method: PaymentStrategy) -> Bill:
        """Order matters: bill -> pay -> mark paid -> free spot -> complete. A failed payment changes nothing."""
        t = self._find_ticket(ticket_id)
        if not t.can_pay():
            raise IllegalStateError(f"Ticket is {t.status}")

        exit_time = self._clock() 
        bill = self._fees.build_bill(t, exit_time)
        
        self._payments.collect(bill, method)  # raises PaymentFailedError if it fails
        
        t.mark_paid()
        self._spots_by_id[t.spot_id].free()
        del self._open_by_plate[t.vehicle.plate]
        t.complete()
        return bill

    def add_charge(self, ticket_id: str, c: Charge) -> None:
        self._find_ticket(ticket_id).add_charge(c)

    def set_floor_open(self, floor_id: int, open_status: bool) -> None:
        """Close a floor for cleaning. Parked cars can still leave; no new cars are sent there."""
        self._get_floor(floor_id).is_open = open_status

    def availability(self) -> Dict[int, Dict[SpotSize, int]]:
        """For the display board: free spots per open floor."""
        result: Dict[int, Dict[SpotSize, int]] = {}
        # Iterate in sorted order of floor IDs (mimicking TreeMap)
        for floor_id in sorted(self._floors.keys()):
            f = self._floors[floor_id]
            if f.is_open:
                result[floor_id] = f.free_counts()
        return result

    def _find_spot(self, v: Vehicle) -> Optional[ParkingSpot]:
        """Floor policy: lowest open floor first; the strategy picks the spot within that floor."""
        for floor_id in sorted(self._floors.keys()):
            floor = self._floors[floor_id]
            if not floor.is_open:
                continue
            spot = self._strategy.find_spot(v, floor.spots)
            if spot is not None:
                return spot
        return None

    def _get_floor(self, floor_id: int) -> ParkingFloor:
        f = self._floors.get(floor_id)
        if f is None:
            raise ValueError(f"No floor {floor_id}")
        return f

    def _find_ticket(self, ticket_id: str) -> Ticket:
        t = self._tickets_by_id.get(ticket_id)
        if t is None:
            raise ValueError(f"Unknown ticket {ticket_id}")
        return t