"""A short trip through the single entry and single exit parking lot."""

from datetime import timedelta

from hourly_cost import HourlyCost
from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import CarSpot, DisabledSpot, ElectricCarSpot, MotorcycleSpot
from payment import CashPaymentStrategy, PaymentContext
from pricing import TimeBasedPricingStrategy
from vehicle import VehicleType
from vehicle_factory import VehicleFactory


def show_money(cents: int) -> str:
    return "${:.2f}".format(cents / 100)


def main() -> None:
    floor = ParkingFloor("F1", [
        CarSpot("C1", "F1", "compact"),
        CarSpot("C2", "F1", "large"),
        DisabledSpot("D1", "F1"),
        ElectricCarSpot("E1", "F1"),
        MotorcycleSpot("M1", "F1"),
    ])

    # Rates are in cents per started hour. For example, 500 means $5.00.
    hourly_cost = HourlyCost({
        "compact": 500,
        "large": 700,
        "disabled": 300,
        "electric_car": 600,
        "motorcycle": 200,
    })
    lot = ParkingLot([floor], TimeBasedPricingStrategy(hourly_cost), PaymentContext())

    vehicle = VehicleFactory().create_vehicle(VehicleType.CAR, "ABC-123")
    ticket = lot.entry_panel.check_in(vehicle)
    print("Ticket:", ticket.ticket_id)
    print("Parked at:", ticket.spot.floor_id, ticket.spot.spot_id)
    print("Free spots after entry:", sum(spot.is_free() for spot in floor.spots))

    # Use a chosen exit time so the example always shows the same duration.
    exit_time = ticket.entry_time + timedelta(hours=2, minutes=10)
    payment = lot.exit_panel.check_out(
        ticket, CashPaymentStrategy(tendered_cents=1500), exit_time
    )

    print("Fee:", show_money(payment.amount))
    print("Payment status:", payment.status)
    print("Spot free after exit:", ticket.spot.is_free())


if __name__ == "__main__":
    main()
