import unittest
from datetime import datetime, timedelta, timezone

from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import ParkingSpot
from parking_ticket import ParkingTicket
from payment import CardPayment, CashPayment, PaymentGateway, WalletPayment
from pricing import FlatPricing, HourlyPricing, PricingStrategy
from vehicle import Car, Motorcycle, Truck


class FakeGateway(PaymentGateway):
    def __init__(self) -> None:
        self.charges: dict[str, tuple[int, str]] = {}

    def charge(self, amount_cents: int, token: str, ticket_id: str) -> str:
        # A repeated ticket ID represents the same charge.
        if ticket_id not in self.charges:
            self.charges[ticket_id] = (amount_cents, token)
        return "charge-" + ticket_id


class ParkingLotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.floor = ParkingFloor(1, [
            ParkingSpot("compact", "compact"),
            ParkingSpot("regular", "regular"),
            ParkingSpot("large", "large"),
        ])
        self.lot = ParkingLot([self.floor], HourlyPricing(350))
        self.start = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)

    def test_vehicle_kinds_use_suitable_spots(self) -> None:
        motorcycle = self.lot.park_vehicle(Motorcycle("m-1"), self.start)
        car = self.lot.park_vehicle(Car("c-1"), self.start)
        truck = self.lot.park_vehicle(Truck("t-1"), self.start)
        self.assertEqual(motorcycle.spot_id, "compact")
        self.assertEqual(car.spot_id, "regular")
        self.assertEqual(truck.spot_id, "large")

    def test_cash_payment_exits_and_frees_spot(self) -> None:
        ticket = self.lot.park_vehicle(Car("c-2"), self.start)
        end = self.start + timedelta(hours=2, minutes=1)
        completed = self.lot.exit_vehicle(ticket.ticket_id, CashPayment(1200), end)
        self.assertEqual(completed.fee_cents, 1050)
        self.assertEqual(self.lot.payment_for_ticket(ticket.ticket_id).change_cents, 150)
        self.assertFalse(self.floor.get_spot("regular").is_occupied())

    def test_failed_payment_keeps_vehicle_parked(self) -> None:
        ticket = self.lot.park_vehicle(Car("c-3"), self.start)
        with self.assertRaisesRegex(ValueError, "Not enough cash"):
            self.lot.exit_vehicle(
                ticket.ticket_id,
                CashPayment(100),
                self.start + timedelta(minutes=30),
            )
        self.assertTrue(ticket.is_active())
        self.assertTrue(self.floor.get_spot("regular").is_occupied())

    def test_duplicate_plate_and_full_lot_are_rejected(self) -> None:
        self.lot.park_vehicle(Car(" c-4 "), self.start)
        with self.assertRaisesRegex(ValueError, "already parked"):
            self.lot.park_vehicle(Car("C-4"), self.start)
        self.lot.park_vehicle(Motorcycle("m-4"), self.start)
        self.lot.park_vehicle(Truck("t-4"), self.start)
        with self.assertRaisesRegex(ValueError, "No suitable spot"):
            self.lot.park_vehicle(Car("c-5"), self.start)

    def test_card_and_wallet_payments(self) -> None:
        gateway = FakeGateway()
        card_ticket = self.lot.park_vehicle(Car("c-6"), self.start)
        self.lot.exit_vehicle(
            card_ticket.ticket_id,
            CardPayment(gateway, "card-token"),
            self.start + timedelta(minutes=30),
        )
        self.assertEqual(self.lot.payment_for_ticket(card_ticket.ticket_id).method, "card")

        wallet_ticket = self.lot.park_vehicle(Car("c-7"), self.start)
        self.lot.exit_vehicle(
            wallet_ticket.ticket_id,
            WalletPayment(gateway, "wallet-token"),
            self.start + timedelta(minutes=30),
        )
        self.assertEqual(self.lot.payment_for_ticket(wallet_ticket.ticket_id).method, "wallet")
        self.assertEqual(len(gateway.charges), 2)

    def test_multiple_floors(self) -> None:
        first = ParkingFloor(1, [ParkingSpot("one", "large")])
        second = ParkingFloor(2, [ParkingSpot("two", "large")])
        lot = ParkingLot([first, second], HourlyPricing(500))
        lot.park_vehicle(Truck("t-5"), self.start)
        ticket = lot.park_vehicle(Truck("t-6"), self.start)
        self.assertEqual(ticket.floor_number, 2)

    def test_flat_pricing_can_be_used_by_the_same_lot(self) -> None:
        lot = ParkingLot([self.floor], FlatPricing(800))
        ticket = lot.park_vehicle(Car("flat-1"), self.start)
        completed = lot.exit_vehicle(
            ticket.ticket_id,
            CashPayment(1000),
            self.start + timedelta(hours=8),
        )
        self.assertEqual(completed.fee_cents, 800)
        self.assertEqual(lot.payment_for_ticket(ticket.ticket_id).change_cents, 200)

    def test_new_pricing_strategy_can_use_vehicle_kind(self) -> None:
        class VehiclePricing(PricingStrategy):
            def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
                self._duration_seconds(ticket, exit_time)
                if ticket.vehicle.kind == "motorcycle":
                    return 100
                return 500

        lot = ParkingLot([self.floor], VehiclePricing())
        ticket = lot.park_vehicle(Motorcycle("priced-motorcycle"), self.start)
        completed = lot.exit_vehicle(
            ticket.ticket_id,
            CashPayment(100),
            self.start + timedelta(hours=1),
        )
        self.assertEqual(completed.fee_cents, 100)


if __name__ == "__main__":
    unittest.main()
