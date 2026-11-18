from decimal import Decimal
from typing import List

from parking_lot_v1.entrance_gate import EntranceGate
from parking_lot_v1.exit_gate import ExitGate
from parking_lot_v1.parking_lot import ParkingLot
from parking_lot_v1.parking_spot import ParkingSpot
from shared.best_fit_strategy import BestFitStrategy
from shared.cash_payment_strategy import CashPayment
from shared.fee_calculator import FeeCalculator
from shared.hourly_pricing import HourlyPricing
from shared.illegal_state_exception import IllegalStateError
from shared.parking_full_exception import ParkingFullError
from shared.payment_failed_exception import PaymentFailedError
from shared.payment_service import PaymentService
from shared.pricing_strategy import PricingStrategy
from shared.spot_size import SpotSize
from shared.system_clock import SystemClock
from shared.upi_payment_strategy import UpiPayment
from shared.vehicle import Vehicle
from shared.vehicle_type import VehicleType

class Main:
    @staticmethod
    def main() -> None:
        # Wiring: the only place that knows the concrete classes
        spots: List[ParkingSpot] = [
            ParkingSpot("S1", SpotSize.SMALL, 1),
            ParkingSpot("M1", SpotSize.MEDIUM, 2),
            ParkingSpot("M2", SpotSize.MEDIUM, 3),
            ParkingSpot("L1", SpotSize.LARGE, 4),
        ]

        pricing: PricingStrategy = HourlyPricing({
            VehicleType.BIKE: Decimal("20"),
            VehicleType.CAR: Decimal("40"),
            VehicleType.TRUCK: Decimal("80"),
        })


        lot = ParkingLot(
            spots=spots,
            strategy=BestFitStrategy(),
            fees=FeeCalculator(pricing),
            payments=PaymentService(),
            clock=SystemClock.instant,
        )

        entry = EntranceGate("IN-1", lot)
        exit_gate = ExitGate("OUT-1", lot)

        # Every call below runs on this one thread, one after another
        print(f"Board: {lot.availability()}")
        
        entry.on_arrival(Vehicle("BIKE-1", VehicleType.BIKE))                  # small spot
        car1 = entry.on_arrival(Vehicle("CAR-1", VehicleType.CAR))             # medium
        entry.on_arrival(Vehicle("BIKE-2", VehicleType.BIKE))                  # small full -> medium
        truck = entry.on_arrival(Vehicle("TRUCK-1", VehicleType.TRUCK))        # large
        
        print(f"Board: {lot.availability()}")

        try:
            entry.on_arrival(Vehicle("CAR-1", VehicleType.CAR))
        except IllegalStateError as e:
            print(f"  Rejected: {e}")

        try:
            entry.on_arrival(Vehicle("CAR-2", VehicleType.CAR))
        except ParkingFullError:
            print("  [IN-1] FULL")

        try:
            exit_gate.on_departure(truck.id, CashPayment(Decimal("10")))
        except PaymentFailedError as e:
            print(f"  Payment failed, truck still {truck.status}: {e}")

        bill = exit_gate.on_departure(truck.id, UpiPayment("driver@okbank"))
        print(f"  Truck paid Rs {bill.total()}, ticket {truck.status}")

        try:
            exit_gate.on_departure(truck.id, UpiPayment("driver@okbank"))
        except IllegalStateError as e:
            print(f"  Rejected: {e}")

        exit_gate.on_departure(car1.id, UpiPayment("a@b"))
        print(f"Board: {lot.availability()}")


if __name__ == "__main__":
    Main.main()
