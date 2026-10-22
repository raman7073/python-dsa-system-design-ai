from datetime import timedelta
from decimal import Decimal

from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import ParkingSpot, SpotType
from payment import CashPaymentStrategy
from pricing import HourlyPricingStrategy
from vehicle import Car


class Main:
    @staticmethod
    def run() -> None:
        floor = ParkingFloor(
            floor_number=1,
            spots=[
                ParkingSpot(spot_id="1A", spot_type=SpotType.COMPACT),
                ParkingSpot(spot_id="1B", spot_type=SpotType.REGULAR),
                ParkingSpot(spot_id="1C", spot_type=SpotType.LARGE),
            ],
        )
        parking_lot = ParkingLot(
            floors=[floor],
            pricing_strategy=HourlyPricingStrategy(Decimal("5.00")),
        )

        car = Car(license_plate="abc-123")
        ticket = parking_lot.park_vehicle(car)

        print(f"Vehicle {ticket.vehicle.license_plate} parked successfully.")
        print(f"Ticket: {ticket.ticket_id}")
        print(f"Floor: {ticket.floor_number}")
        print(f"Spot: {ticket.spot_id}")
        print(f"Entry time: {ticket.entry_time.isoformat()}")

        exit_time = ticket.entry_time + timedelta(hours=2, minutes=10)
        completed_ticket = parking_lot.exit_vehicle(
            ticket_id=ticket.ticket_id,
            payment_strategy=CashPaymentStrategy(Decimal("20.00")),
            exit_time=exit_time,
        )

        print(f"Exit time: {completed_ticket.exit_time.isoformat()}")
        print(f"Parking fee: ${completed_ticket.fee:.2f}")
        payment_record = parking_lot.payments_for_ticket(completed_ticket.ticket_id)[-1]
        print(f"Payment method: {payment_record.payment.method.value}")
        print(f"Change due: ${payment_record.payment.change_due:.2f}")
        print(f"Spot {completed_ticket.spot_id} is now available.")


if __name__ == "__main__":
    Main.run()
