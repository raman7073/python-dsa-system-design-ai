import concurrent.futures
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from parking_lot_v5.exit_gate import ExitGate
from parking_lot_v5.ticket import Ticket
from parking_lot_v5.entrance_gate import EntranceGate
from parking_lot_v5.parking_lot import ParkingLot
from parking_lot_v5.parking_spot import ParkingSpot
from parking_lot_v5.floor_manager import FloorManager
from parking_lot_v5.ticket_repository import TicketRepository
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
        best_fit = BestFitStrategy()
        floor1 = FloorManager(1, [
            ParkingSpot("F1-S1", 1, SpotSize.SMALL, 1),
            ParkingSpot("F1-M1", 1, SpotSize.MEDIUM, 2),
            ParkingSpot("F1-M2", 1, SpotSize.MEDIUM, 3),
        ], best_fit)
        
        floor2 = FloorManager(2, [
            ParkingSpot("F2-M1", 2, SpotSize.MEDIUM, 1),
            ParkingSpot("F2-L1", 2, SpotSize.LARGE, 2),
        ], best_fit)

        pricing: PricingStrategy = HourlyPricing({
            VehicleType.BIKE: Decimal("20"),
            VehicleType.CAR: Decimal("40"),
            VehicleType.TRUCK: Decimal("80"),
        })

        

        lot = ParkingLot(
            lot_id="MALL",
            floors=[floor1, floor2],
            tickets=TicketRepository(),
            fees=FeeCalculator(pricing),
            payments=PaymentService(),
            clock=SystemClock.instant,
        )

        # Four entry gates, each on its own thread, all arriving at once
        gates: List[EntranceGate] = [
            EntranceGate("IN-1", lot), EntranceGate("IN-2", lot),
            EntranceGate("IN-3", lot), EntranceGate("IN-4", lot)
        ]
        
        arrivals: List[concurrent.futures.Future] = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for i in range(4):
                gate = gates[i]
                car = Vehicle(f"CAR-{i}", VehicleType.CAR)
                # Submit the gate arrival task to the thread pool
                future = pool.submit(gate.on_arrival, car)
                arrivals.append(future)

        # Collect the results (blocks until all threads finish)
        tickets: List[Ticket] = []
        for f in arrivals:
            tickets.append(f.result())  # 4 cars, 4 medium-or-larger spots

        try:
            EntranceGate("IN-1", lot).on_arrival(Vehicle("CAR-9", VehicleType.CAR))
        except ParkingFullError:
            print("  [IN-1] FULL")

        exit_gate = ExitGate("OUT-1", lot)
        bill = exit_gate.on_departure(tickets[0].id, UpiPayment("me@okbank"))
        
        print(f"Paid Rs {bill.total()}, ticket {tickets[0].id} is {tickets[0].status}")


if __name__ == "__main__":
    Main.main()