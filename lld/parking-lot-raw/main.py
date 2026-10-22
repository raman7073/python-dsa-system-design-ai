from datetime import timedelta

from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import ParkingSpot
from payment import CashPayment
from pricing import HourlyPricing
from vehicle import Car


def show_money(cents: int) -> str:
    return "${:.2f}".format(cents / 100)


def main() -> None:
    floor = ParkingFloor(1, [
        ParkingSpot("1A", "compact"),
        ParkingSpot("1B", "regular"),
        ParkingSpot("1C", "large"),
    ])
    lot = ParkingLot([floor], HourlyPricing(500))  # $5 for each started hour

    car = Car("abc-123")
    ticket = lot.park_vehicle(car)
    print(car.license_plate, "parked in spot", ticket.spot_id)

    # Pretend the car leaves 2 hours and 10 minutes after it arrived.
    exit_time = ticket.entry_time + timedelta(hours=2, minutes=10)
    completed = lot.exit_vehicle(ticket.ticket_id, CashPayment(2000), exit_time)
    payment = lot.payment_for_ticket(ticket.ticket_id)

    print("Parking fee:", show_money(completed.fee_cents))
    print("Paid with:", payment.method)
    print("Change:", show_money(payment.change_cents))
    print("Spot available again:", not floor.get_spot(ticket.spot_id).is_occupied())


if __name__ == "__main__":
    main()
