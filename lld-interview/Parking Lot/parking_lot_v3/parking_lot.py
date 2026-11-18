from datetime import datetime
from typing import Callable, Dict, List
import threading

from parking_lot_v3.parking_spot import ParkingSpot
from parking_lot_v3.ticket import Ticket
from shared.bill import Bill
from shared.charge import Charge
from shared.fee_calculator import FeeCalculator
from shared.illegal_state_exception import IllegalStateError
from shared.parking_full_exception import ParkingFullError
from shared.payment_service import PaymentService
from shared.payment_strategy import PaymentStrategy
from shared.spot_allocation_strategy import SpotAllocationStrategy
from shared.spot_size import SpotSize
from shared.spot_status import SpotStatus
from shared.vehicle import Vehicle


class ParkingLot:
    """
    Facade over spots, tickets, pricing and payment.

    THREADING CONTRACT: thread-safe. Gates call from any thread.
    ONE lot-level lock guards every spot and both ticket maps.
    The slow payment call runs OUTSIDE it, under a per-ticket lock (or reentrant lock).
    """

    def __init__(
        self,
        spots: List[ParkingSpot],
        strategy: SpotAllocationStrategy,
        fees: FeeCalculator,
        payments: PaymentService,
        clock: Callable[[], datetime],
    ) -> None:
        self._spots: List[ParkingSpot] = list(spots)
        self._spots_by_id: Dict[str, ParkingSpot] = {spot.id: spot for spot in self._spots}
        self._strategy: SpotAllocationStrategy = strategy
        self._fees: FeeCalculator = fees
        self._payments: PaymentService = payments
        self._clock: Callable[[], datetime] = clock

        # Guarded by `_lock`. Plain dict is fine: every read and write happens inside the lock.
        self._lock: threading.Lock = threading.Lock()
        self._tickets_by_id: Dict[str, Ticket] = {}
        self._open_by_plate: Dict[str, Ticket] = {}
        self._ticket_seq: int = 0

    def park(self, v: Vehicle) -> Ticket:
        with self._lock:
            # check-then-act is safe: the whole block holds the lock
            if v.plate in self._open_by_plate:
                raise IllegalStateError(f"{v.plate} is already inside")

            spot = self._strategy.find_spot(v, self._spots)
            if spot is None:
                raise ParkingFullError(f"No spot for {v.type}")

            spot.occupy()

            self._ticket_seq += 1
            ticket_id = f"T{self._ticket_seq}"
            
            entry_time = self._clock()

            t = Ticket(ticket_id, v, spot.id, entry_time)
            self._tickets_by_id[t.id] = t
            self._open_by_plate[v.plate] = t
            return t

    def unpark(self, ticket_id: str, method: PaymentStrategy) -> Bill:
        """Order matters: bill -> pay -> mark paid -> free spot -> complete. A failed payment changes nothing."""
        t = self._find_ticket(ticket_id)
        
        with t.lock:  # Two exit gates, same ticket: only one pays
            if not t.can_pay():
                raise IllegalStateError(f"Ticket is {t.status}")

            exit_time = self._clock()
            bill = self._fees.build_bill(t, exit_time)
            
            self._payments.collect(bill, method)  # slow gateway call: NOT holding the lot lock
            t.mark_paid()
            
            with self._lock:
                self._spots_by_id[t.spot_id].free()
                del self._open_by_plate[t.vehicle.plate]
                
            t.complete()
            return bill

    def add_charge(self, ticket_id: str, c: Charge) -> None:
        t = self._find_ticket(ticket_id)
        with t.lock:
            t.add_charge(c)

    def availability(self) -> Dict[SpotSize, int]:
        """For the display board: free spots per size, as one consistent snapshot."""
        with self._lock:
            counts: Dict[SpotSize, int] = {size: 0 for size in SpotSize}
            for s in self._spots:
                if s.status == SpotStatus.FREE:
                    counts[s.size] += 1
            return counts

    def _find_ticket(self, ticket_id: str) -> Ticket:
        with self._lock:
            t = self._tickets_by_id.get(ticket_id)
            if t is None:
                raise ValueError(f"Unknown ticket {ticket_id}")
            return t
