from parking_lot_v1.parking_lot import ParkingLot
from shared.bill import Bill
from shared.payment_strategy import PaymentStrategy


class ExitGate:
    def __init__(self, gate_id: str, lot: ParkingLot) -> None:
        self._gate_id: str = gate_id
        self._lot: ParkingLot = lot

    def on_departure(self, ticket_id: str, method: PaymentStrategy) -> Bill:
        return self._lot.unpark(ticket_id, method)
