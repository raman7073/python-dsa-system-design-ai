from datetime import datetime, timezone
from decimal import Decimal


from parking_lot_v4.parking_lot import ParkingLot
from parking_lot_v4.parking_spot import ParkingSpot
from parking_lot_v4.entrance_gate import EntranceGate
from parking_lot_v4.exit_gate import ExitGate
from parking_lot_v4.parking_floor import ParkingFloor
from shared.best_fit_strategy import BestFitStrategy
from shared.fee_calculator import FeeCalculator
from shared.hourly_pricing import HourlyPricing
from shared.parking_full_exception import ParkingFullError
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
        floor1 = ParkingFloor(1, [
            ParkingSpot("F1-S1", 1, SpotSize.SMALL, 1),
            ParkingSpot("F1-M1", 1, SpotSize.MEDIUM, 2),
        ])
        floor2 = ParkingFloor(2, [
            ParkingSpot("F2-M1", 2, SpotSize.MEDIUM, 1),
            ParkingSpot("F2-L1", 2, SpotSize.LARGE, 2),
        ])

        pricing: PricingStrategy = HourlyPricing({
            VehicleType.BIKE: Decimal("20"),
            VehicleType.CAR: Decimal("40"),
            VehicleType.TRUCK: Decimal("80"),
        })

       
        lot = ParkingLot(
            floors=[floor1, floor2],
            strategy=BestFitStrategy(),
            fees=FeeCalculator(pricing),
            payments=PaymentService(),
            clock=SystemClock.instant()
        )

        entry = EntranceGate("IN-1", lot)
        exit_gate = ExitGate("OUT-1", lot)

        print(f"Board: {lot.availability()}")
        car1 = entry.on_arrival(Vehicle("CAR-1", VehicleType.CAR))             # floor 1
        entry.on_arrival(Vehicle("CAR-2", VehicleType.CAR))                    # floor 1 full -> floor 2
        entry.on_arrival(Vehicle("TRUCK-1", VehicleType.TRUCK))                # only floor 2 has LARGE
        print(f"Board: {lot.availability()}")

        lot.set_floor_open(1, False)                                           # floor 1 closed for cleaning
        exit_gate.on_departure(car1.id, UpiPayment("a@b"))                     # cars on floor 1 can still leave
        try:
            entry.on_arrival(Vehicle("CAR-3", VehicleType.CAR))                # F1-M1 is free but floor is closed
        except ParkingFullError as e:
            print(f"  [IN-1] FULL ({e})")
            
        lot.set_floor_open(1, True)
        entry.on_arrival(Vehicle("CAR-3", VehicleType.CAR))
        print(f"Board: {lot.availability()}")


if __name__ == "__main__":
    Main.main()