from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from parking_lot_v5.ticket import Ticket
from parking_lot_v5.floor_manager import FloorManager
from parking_lot_v5.ticket_repository import TicketRepository
from shared.bill import Bill
from shared.charge import Charge
from shared.fee_calculator import FeeCalculator
from shared.illegal_state_exception import IllegalStateError
from shared.parking_full_exception import ParkingFullError
from shared.payment_service import PaymentService
from shared.payment_strategy import PaymentStrategy
from shared.vehicle import Vehicle


class ParkingLot:
    """Facade: gates only call park() and unpark(). Everything is injected, nothing is a Singleton."""

    def __init__(
        self,
        lot_id: str,
        floors: List[FloorManager],
        tickets: TicketRepository,
        fees: FeeCalculator,
        payments: PaymentService,
        clock: datetime,
    ) -> None:
        self._lot_id: str = lot_id
        # Using a dict sorted by floor_id upon insertion to mimic TreeMap behavior
        self._floors: Dict[int, FloorManager] = {
            f.floor_id: f for f in sorted(floors, key=lambda fl: fl.floor_id)
        }
        self._tickets: TicketRepository = tickets
        self._fees: FeeCalculator = fees
        self._payments: PaymentService = payments
        self._clock: datetime = clock

        # Replaces Java's AtomicLong ticketSeq
        self._ticket_seq: int = 0
        self._seq_lock: threading.Lock = threading.Lock()

    def park(self, v: Vehicle) -> Ticket:
        if self._tickets.find_open_by_plate(v.plate) is not None:
            raise IllegalStateError(f"{v.plate} is already inside")

        for floor in self._floors.values():  # lowest floor first
            spot = floor.try_allocate(v)
            if spot is not None:
                return self._issue_ticket(v, floor, spot.id)

        raise ParkingFullError(f"No spot for {v.type}")

    def unpark(self, ticket_id: str, method: PaymentStrategy) -> Bill:
        """bill -> pay -> mark paid -> free spot -> complete. A failed payment changes nothing."""
        t = self._find_ticket(ticket_id)
        
        with t.lock:  # two exit gates, same ticket
            if not t.can_pay():
                raise IllegalStateError(f"Ticket is {t.status}")

            exit_time = self._clock()
                
            bill = self._fees.build_bill(t, exit_time)
            self._payments.collect(bill, method)  # throws on failure
            t.mark_paid()
            
            self._floors[t.floor_id].release(t.spot_id)
            t.complete()
            self._tickets.close(t)
            return bill

    def add_charge(self, ticket_id: str, charge: Charge) -> None:
        self._find_ticket(ticket_id).add_charge(charge)

    def _issue_ticket(self, v: Vehicle, floor: FloorManager, spot_id: str) -> Ticket:
        now =  self._clock()
           

        with self._seq_lock:
            self._ticket_seq += 1
            current_seq = self._ticket_seq

        ticket_id = f"{self._lot_id}-T{current_seq}"
        t = Ticket(ticket_id, v, floor.floor_id, spot_id, now)

        if not self._tickets.save_if_not_parked(t):  # lost a race with another gate
            floor.release(spot_id)
            raise IllegalStateError(f"{v.plate} is already inside")
            
        return t

    def _find_ticket(self, ticket_id: str) -> Ticket:
        t = self._tickets.find_by_id(ticket_id)
        if t is None:
            raise ValueError(f"Unknown ticket {ticket_id}")
        return t

    @property
    def lot_id(self) -> str:
        return self._lot_id