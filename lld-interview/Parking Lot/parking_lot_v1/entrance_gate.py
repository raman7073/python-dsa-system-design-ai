from parking_lot_v1.parking_lot import ParkingLot
from shared.vehicle import Vehicle
from parking_lot_v1.ticket import Ticket

class EntranceGate:
    def __init__(self, gate_id: str, lot: ParkingLot) -> None:
        self._gate_id: str = gate_id
        self._lot: ParkingLot = lot

    def on_arrival(self, v: Vehicle) -> Ticket:
        t: Ticket = self._lot.park(v)
        print(f"  [{self._gate_id}] {v.plate}: go to spot {t.spot_id}")
        return t
