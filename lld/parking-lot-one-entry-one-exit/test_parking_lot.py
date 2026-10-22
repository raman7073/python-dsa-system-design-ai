import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hourly_cost import HourlyCost
from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import (
    CarSpot,
    DisabledSpot,
    ElectricCarSpot,
    MotorcycleSpot,
    ParkingSpot,
    ParkingSpotType,
)
from payment import (
    CardGateway,
    CardPaymentStrategy,
    CashPaymentStrategy,
    PaymentContext,
    PaymentMethod,
    PaymentService,
    PaymentStatus,
    PaymentStrategy,
)
from pricing import EventBasedPricingStrategy, PricingStrategy, TimeBasedPricingStrategy
from vehicle import Car, ElectricCar, Motorbike, Truck, Van, Vehicle, VehicleType
from vehicle_factory import VehicleFactory


class FailedVerificationContext(PaymentContext):
    def verify(self, payment_id: str) -> str:
        return PaymentStatus.FAILED


class ParkingLotTests(unittest.TestCase):
    def new_york_time_zone(self) -> ZoneInfo:
        try:
            return ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA time zone data is unavailable")

    def setUp(self) -> None:
        self.start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        self.compact = CarSpot("C1", "F1")
        self.large_one = CarSpot("L1", "F1", ParkingSpotType.LARGE)
        self.large_two = CarSpot("L2", "F1", ParkingSpotType.LARGE)
        self.disabled = DisabledSpot("D1", "F1")
        self.electric = ElectricCarSpot("E1", "F1")
        self.motorcycle = MotorcycleSpot("M1", "F1")
        self.floor = ParkingFloor(
            "F1",
            [
                self.compact,
                self.large_one,
                self.large_two,
                self.disabled,
                self.electric,
                self.motorcycle,
            ],
        )
        self.rates = {
            ParkingSpotType.COMPACT: 100,
            ParkingSpotType.LARGE: 200,
            ParkingSpotType.DISABLED: 50,
            ParkingSpotType.ELECTRIC_CAR: 150,
            ParkingSpotType.MOTORCYCLE: 75,
        }

    def make_lot(self, context: PaymentContext | None = None) -> ParkingLot:
        return ParkingLot(
            [self.floor],
            TimeBasedPricingStrategy(HourlyCost(self.rates)),
            context or PaymentContext(),
        )

    def test_payment_context_is_shared_by_lot_and_exit_panel(self) -> None:
        context = PaymentContext()
        lot = ParkingLot(
            [self.floor],
            TimeBasedPricingStrategy(HourlyCost(self.rates)),
            payment_context=context,
        )

        self.assertIs(lot.payment_context, context)
        self.assertIs(lot.exit_panel.payment_context, context)

    def test_payment_service_remains_a_compatibility_alias(self) -> None:
        self.assertIs(PaymentService, PaymentContext)

        context = PaymentService()
        lot = ParkingLot(
            [self.floor],
            TimeBasedPricingStrategy(HourlyCost(self.rates)),
            payment_service=context,
        )
        self.assertIs(lot.payment_service, context)
        self.assertIs(lot.payment_context, context)

    def test_each_lot_owns_one_entry_and_one_exit_panel(self) -> None:
        first_lot = self.make_lot()
        second_floor = ParkingFloor("F2", [CarSpot("C2", "F2")])
        second_lot = ParkingLot(
            [second_floor], TimeBasedPricingStrategy(HourlyCost(self.rates))
        )

        self.assertIsNot(first_lot, second_lot)
        for lot in (first_lot, second_lot):
            with self.subTest(lot=lot):
                self.assertIs(lot.entry_panel.lot, lot)
                self.assertIs(lot.exit_panel.lot, lot)
                self.assertEqual(lot.entry_panel.entry_panel_id, "ENTRY-1")
                self.assertEqual(lot.exit_panel.exit_panel_id, "EXIT-1")
        self.assertIsNot(first_lot.entry_panel, second_lot.entry_panel)
        self.assertIsNot(first_lot.exit_panel, second_lot.exit_panel)

    def test_two_lots_keep_floors_tickets_prices_and_payments_separate(self) -> None:
        first_context = PaymentContext()
        second_context = PaymentContext()
        first_lot = self.make_lot(first_context)
        second_spot = CarSpot("C2", "F2")
        second_floor = ParkingFloor("F2", [second_spot])
        second_lot = ParkingLot(
            [second_floor],
            TimeBasedPricingStrategy(HourlyCost({ParkingSpotType.COMPACT: 250})),
            second_context,
        )

        # The same registration can be parked in different physical lots.
        first_ticket = first_lot.entry_panel.check_in(Car("car-1"), self.start)
        second_ticket = second_lot.entry_panel.check_in(Car("car-1"), self.start)
        self.assertIs(first_ticket.spot, self.compact)
        self.assertIs(second_ticket.spot, second_spot)
        self.assertIsNot(first_lot.floors[0], second_lot.floors[0])
        self.assertIn(first_ticket.ticket_id, first_lot.active_tickets)
        self.assertNotIn(first_ticket.ticket_id, second_lot.active_tickets)
        self.assertIn(second_ticket.ticket_id, second_lot.active_tickets)
        self.assertNotIn(second_ticket.ticket_id, first_lot.active_tickets)

        departure = self.start + timedelta(hours=1)
        with self.assertRaises(ValueError):
            second_lot.exit_panel.check_out(first_ticket, PaymentMethod.CASH, departure)

        first_payment = first_lot.exit_panel.check_out(
            first_ticket, PaymentMethod.CASH, departure
        )
        self.assertEqual(first_payment.amount, 100)
        self.assertIn(first_ticket.ticket_id, first_context.payments_by_ticket)
        self.assertNotIn(first_ticket.ticket_id, second_context.payments_by_ticket)
        self.assertIn(second_ticket.ticket_id, second_lot.active_tickets)
        self.assertFalse(second_spot.is_free())

        second_payment = second_lot.exit_panel.check_out(
            second_ticket, PaymentMethod.CARD, departure
        )
        self.assertEqual(second_payment.amount, 250)
        self.assertIn(second_ticket.ticket_id, second_context.payments_by_ticket)
        self.assertNotIn(second_ticket.ticket_id, first_context.payments_by_ticket)
        self.assertTrue(second_spot.is_free())

    def test_vehicles_are_assigned_compatible_spots(self) -> None:
        lot = self.make_lot()
        vehicles_and_spots = [
            (Car("car-1"), self.compact),
            (Truck("truck-1"), self.large_one),
            (Van("van-1"), self.large_two),
            (ElectricCar("electric-1"), self.electric),
            (Motorbike("bike-1"), self.motorcycle),
        ]

        for vehicle, expected_spot in vehicles_and_spots:
            with self.subTest(vehicle=vehicle.get_registration_no()):
                ticket = lot.entry_panel.check_in(vehicle, self.start)
                self.assertIs(ticket.spot, expected_spot)
                self.assertIs(ticket.spot.vehicle, vehicle)

    def test_factory_creates_all_builtin_vehicle_types(self) -> None:
        factory = VehicleFactory()
        vehicle_classes = [
            (VehicleType.CAR, Car),
            (VehicleType.TRUCK, Truck),
            (VehicleType.ELECTRIC_CAR, ElectricCar),
            (VehicleType.MOTORCYCLE, Motorbike),
            (VehicleType.VAN, Van),
        ]

        for vehicle_type, vehicle_class in vehicle_classes:
            with self.subTest(vehicle_type=vehicle_type):
                vehicle = factory.create_vehicle(vehicle_type, "  plate-1  ")
                self.assertIsInstance(vehicle, vehicle_class)
                self.assertEqual(vehicle.get_vehicle_type(), vehicle_type)
                self.assertEqual(vehicle.get_registration_no(), "PLATE-1")

    def test_factory_created_accessible_car_uses_disabled_spot(self) -> None:
        factory = VehicleFactory()
        lot = self.make_lot()
        vehicle = factory.create_vehicle(
            VehicleType.CAR, "accessible", accessible=True
        )

        ticket = lot.entry_panel.check_in(vehicle, self.start)

        self.assertIsInstance(vehicle, Car)
        self.assertTrue(vehicle.accessible)
        self.assertIs(ticket.spot, self.disabled)

    def test_factory_registration_rejects_duplicate_unless_replaced(self) -> None:
        factory = VehicleFactory()

        with self.assertRaises(ValueError):
            factory.register(VehicleType.CAR, Car)

        factory.register(
            VehicleType.CAR,
            lambda plate: Car(plate, accessible=True),
            replace=True,
        )
        vehicle = factory.create_vehicle(VehicleType.CAR, "replaced")
        self.assertIsInstance(vehicle, Car)
        self.assertTrue(vehicle.accessible)

    def test_factory_rejects_unknown_type_and_invalid_constructor_results(self) -> None:
        factory = VehicleFactory()

        with self.assertRaises(ValueError):
            factory.create_vehicle("unknown", "plate-1")
        with self.assertRaises(ValueError):
            factory.create_vehicle(VehicleType.CAR, "  ")

        factory.register("invalid_result", lambda plate: object())
        with self.assertRaises(TypeError):
            factory.create_vehicle("invalid_result", "plate-1")

        factory.register("wrong_type", lambda plate: Car(plate))
        with self.assertRaises(ValueError):
            factory.create_vehicle("wrong_type", "plate-2")

    def test_custom_factory_vehicle_can_park_and_check_out(self) -> None:
        vehicle_type = "scooter"

        class Scooter(Vehicle):
            def __init__(self, registration_no: str) -> None:
                super().__init__(registration_no, vehicle_type)

        class ScooterSpot(ParkingSpot):
            def __init__(self, spot_id: str, floor_id: str) -> None:
                super().__init__(spot_id, floor_id, vehicle_type)

            def can_fit(self, vehicle: Vehicle) -> bool:
                return vehicle.get_vehicle_type() == vehicle_type

        factory = VehicleFactory()
        factory.register(vehicle_type, Scooter)
        vehicle = factory.create_vehicle(vehicle_type, "scooter-1")
        spot = ScooterSpot("S1", "F1")
        lot = ParkingLot(
            [ParkingFloor("F1", [spot])], EventBasedPricingStrategy(125)
        )

        ticket = lot.entry_panel.check_in(vehicle, self.start)
        self.assertIs(ticket.spot, spot)
        payment = lot.exit_panel.check_out(
            ticket, PaymentMethod.CASH, self.start + timedelta(hours=1)
        )

        self.assertEqual(payment.amount, 125)
        self.assertEqual(ticket.status, "CLOSED")
        self.assertTrue(spot.is_free())

    def test_accessible_car_prefers_disabled_spot(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("accessible", accessible=True), self.start)

        self.assertIs(ticket.spot, self.disabled)
        self.assertTrue(self.compact.is_free())

    def test_non_accessible_car_does_not_take_disabled_spot(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("ordinary"), self.start)

        self.assertIs(ticket.spot, self.compact)
        self.assertTrue(self.disabled.is_free())

    def test_payment_closes_ticket_and_releases_spot(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=1)

        payment = lot.exit_panel.check_out(ticket, PaymentMethod.CASH, departure)

        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(payment.ticket_id, ticket.ticket_id)
        self.assertEqual(payment.amount, 100)
        self.assertEqual(ticket.amount, 100)
        self.assertEqual(ticket.status, "CLOSED")
        self.assertEqual(ticket.exit_time, departure)
        self.assertTrue(self.compact.is_free())
        self.assertNotIn(ticket.ticket_id, lot.active_tickets)
        self.assertNotIn("CAR-1", lot.active_plates)
        with self.assertRaises(ValueError):
            lot.exit_panel.check_out(ticket, PaymentMethod.CASH, departure)

    def test_cash_strategy_can_be_passed_to_checkout(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        payment = lot.exit_panel.check_out(
            ticket, CashPaymentStrategy(tendered_cents=100),
            self.start + timedelta(hours=1),
        )

        self.assertEqual(payment.method, PaymentMethod.CASH)
        self.assertEqual(payment.amount, 100)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(ticket.status, "CLOSED")
        self.assertTrue(ticket.spot.is_free())

    def test_insufficient_cash_keeps_ticket_open_for_retry(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=1)

        with self.assertRaises(RuntimeError):
            lot.exit_panel.check_out(ticket, CashPaymentStrategy(50), departure)

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(ticket.spot.vehicle, ticket.vehicle)
        self.assertNotIn(ticket.ticket_id, lot.payment_context.payments_by_ticket)

        payment = lot.exit_panel.check_out(ticket, CashPaymentStrategy(100), departure)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertTrue(ticket.spot.is_free())

    def test_card_strategy_charges_its_gateway_before_checkout(self) -> None:
        charges: list[tuple[str, int]] = []

        class RecordingGateway(CardGateway):
            def charge(self, ticket_id: str, amount: int) -> bool:
                charges.append((ticket_id, amount))
                return True

        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        payment = lot.exit_panel.check_out(
            ticket, CardPaymentStrategy(RecordingGateway()),
            self.start + timedelta(hours=2),
        )

        self.assertEqual(charges, [(ticket.ticket_id, 200)])
        self.assertEqual(payment.method, PaymentMethod.CARD)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(ticket.status, "CLOSED")
        self.assertTrue(ticket.spot.is_free())

    def test_card_denial_keeps_ticket_open_and_can_be_retried(self) -> None:
        class SwitchableGateway(CardGateway):
            approved = False

            def charge(self, ticket_id: str, amount: int) -> bool:
                return self.approved

        gateway = SwitchableGateway()
        context = PaymentContext()
        lot = self.make_lot(context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=1)
        strategy = CardPaymentStrategy(gateway)

        with self.assertRaises(RuntimeError):
            lot.exit_panel.check_out(ticket, strategy, departure)

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(ticket.spot.vehicle, ticket.vehicle)
        self.assertIn(ticket.ticket_id, lot.active_tickets)
        self.assertIn(ticket.vehicle.get_registration_no(), lot.active_plates)

        gateway.approved = True
        payment = lot.exit_panel.check_out(ticket, strategy, departure)

        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(ticket.status, "CLOSED")
        self.assertTrue(ticket.spot.is_free())

    def test_custom_payment_strategy_works_directly_and_when_registered(self) -> None:
        calls: list[tuple[str, int]] = []

        class VoucherPaymentStrategy(PaymentStrategy):
            method = "VOUCHER"

            def process_payment(self, ticket_id: str, amount: int) -> str:
                calls.append((ticket_id, amount))
                return PaymentStatus.SUCCESS

        context = PaymentContext()
        strategy = VoucherPaymentStrategy()
        context.register_strategy(strategy)
        lot = self.make_lot(context)
        first = lot.entry_panel.check_in(Car("car-1"), self.start)
        second = lot.entry_panel.check_in(Car("car-2"), self.start)
        departure = self.start + timedelta(hours=1)

        direct = lot.exit_panel.check_out(first, strategy, departure)
        registered = lot.exit_panel.check_out(second, "VOUCHER", departure)

        self.assertEqual(calls, [(first.ticket_id, 100), (second.ticket_id, 200)])
        self.assertEqual(direct.method, "VOUCHER")
        self.assertEqual(registered.method, "VOUCHER")
        self.assertEqual(first.status, "CLOSED")
        self.assertEqual(second.status, "CLOSED")

    def test_successful_strategy_payment_is_not_processed_twice(self) -> None:
        calls: list[tuple[str, int]] = []

        class CountingPaymentStrategy(PaymentStrategy):
            method = "COUNTING"

            def process_payment(self, ticket_id: str, amount: int) -> str:
                calls.append((ticket_id, amount))
                return PaymentStatus.SUCCESS

        context = PaymentContext()
        strategy = CountingPaymentStrategy()

        first = context.pay("ticket-1", 100, strategy)
        second = context.pay("ticket-1", 100, strategy)

        self.assertIs(first, second)
        self.assertEqual(calls, [("ticket-1", 100)])
        with self.assertRaises(ValueError):
            context.pay("ticket-1", 200, strategy)

    def test_verification_retry_does_not_repeat_successful_card_charge(self) -> None:
        class RecoveringVerificationContext(PaymentContext):
            def __init__(self) -> None:
                super().__init__()
                self.verify_calls = 0

            def verify(self, payment_id: str) -> str:
                self.verify_calls += 1
                if self.verify_calls == 1:
                    return PaymentStatus.FAILED
                return super().verify(payment_id)

        class CountingGateway(CardGateway):
            def __init__(self) -> None:
                self.charges = 0

            def charge(self, ticket_id: str, amount: int) -> bool:
                self.charges += 1
                return True

        context = RecoveringVerificationContext()
        gateway = CountingGateway()
        lot = self.make_lot(context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=1)
        strategy = CardPaymentStrategy(gateway)

        with self.assertRaises(RuntimeError):
            lot.exit_panel.check_out(ticket, strategy, departure)

        self.assertEqual(ticket.status, "OPEN")
        payment = lot.exit_panel.check_out(ticket, strategy, departure)
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        self.assertEqual(gateway.charges, 1)
        self.assertEqual(context.verify_calls, 2)
        self.assertTrue(ticket.spot.is_free())

    def test_pending_strategy_is_rejected_without_recording_payment(self) -> None:
        class PendingPaymentStrategy(PaymentStrategy):
            method = "PENDING_TEST"

            def process_payment(self, ticket_id: str, amount: int) -> str:
                return PaymentStatus.PENDING

        context = PaymentContext()
        lot = self.make_lot(context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaisesRegex(ValueError, "Pending payments are not supported"):
            lot.exit_panel.check_out(
                ticket, PendingPaymentStrategy(), self.start + timedelta(hours=1)
            )

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(ticket.spot.vehicle, ticket.vehicle)
        self.assertEqual(context.payments_by_ticket, {})
        self.assertEqual(context.payments_by_id, {})

    def test_partial_hour_is_rounded_up(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=2, minutes=10)

        self.assertEqual(lot.exit_panel.calculate_duration(ticket, departure), 3)
        payment = lot.exit_panel.check_out(ticket, PaymentMethod.CARD, departure)
        self.assertEqual(payment.amount, 300)

    def test_fall_back_stay_charges_actual_elapsed_hours(self) -> None:
        new_york = self.new_york_time_zone()
        arrival = datetime(2026, 11, 1, 0, 30, tzinfo=new_york)
        departure = datetime(2026, 11, 1, 2, 30, tzinfo=new_york)
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), arrival)

        self.assertEqual(lot.exit_panel.calculate_duration(ticket, departure), 3)
        payment = lot.exit_panel.check_out(ticket, PaymentMethod.CARD, departure)

        self.assertEqual(payment.amount, 300)

    def test_fall_back_repeated_hour_charges_one_elapsed_hour(self) -> None:
        new_york = self.new_york_time_zone()
        arrival = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=0)
        departure = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), arrival)

        self.assertEqual(lot.exit_panel.calculate_duration(ticket, departure), 1)
        payment = lot.exit_panel.check_out(ticket, PaymentMethod.CARD, departure)

        self.assertEqual(payment.amount, 100)

    def test_legacy_hourly_cost_constructor_still_prices_checkout(self) -> None:
        lot = ParkingLot([self.floor], HourlyCost(self.rates))
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        payment = lot.exit_panel.check_out(
            ticket, PaymentMethod.CASH, self.start + timedelta(hours=1, minutes=1)
        )

        self.assertEqual(payment.amount, 200)

    def test_legacy_hourly_cost_keyword_still_prices_checkout(self) -> None:
        lot = ParkingLot([self.floor], hourly_cost=HourlyCost(self.rates))
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        payment = lot.exit_panel.check_out(
            ticket, PaymentMethod.CASH, self.start + timedelta(hours=1)
        )

        self.assertEqual(payment.amount, 100)

    def test_event_pricing_charges_once_for_partial_and_long_stays(self) -> None:
        for duration in (timedelta(0), timedelta(minutes=10), timedelta(days=3)):
            with self.subTest(duration=duration):
                floor = ParkingFloor("F1", [CarSpot("C1", "F1")])
                lot = ParkingLot([floor], EventBasedPricingStrategy(750))
                ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

                payment = lot.exit_panel.check_out(
                    ticket, PaymentMethod.CARD, self.start + duration
                )

                self.assertEqual(payment.amount, 750)
                self.assertEqual(ticket.amount, 750)
                self.assertEqual(ticket.status, "CLOSED")

    def test_custom_pricing_strategy_is_used_by_checkout(self) -> None:
        calls: list[tuple[object, datetime]] = []

        class CustomPricingStrategy(PricingStrategy):
            def calculate_fee(self, ticket, exit_time):
                calls.append((ticket, exit_time))
                return 42

        lot = ParkingLot([self.floor], CustomPricingStrategy())
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)
        departure = self.start + timedelta(hours=5)

        payment = lot.exit_panel.check_out(ticket, PaymentMethod.CASH, departure)

        self.assertEqual(calls, [(ticket, departure)])
        self.assertEqual(payment.amount, 42)
        self.assertEqual(ticket.amount, 42)

    def test_event_pricing_rejects_exit_before_entry_without_payment(self) -> None:
        context = PaymentContext()
        lot = ParkingLot([self.floor], EventBasedPricingStrategy(750), context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaises(ValueError):
            lot.exit_panel.check_out(
                ticket, PaymentMethod.CASH, self.start - timedelta(seconds=1)
            )

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertEqual(context.payments_by_ticket, {})

    def test_pricing_failure_keeps_ticket_and_spot_open(self) -> None:
        class FailingPricingStrategy(PricingStrategy):
            def calculate_fee(self, ticket, exit_time):
                raise ValueError("No price for this ticket")

        context = PaymentContext()
        lot = ParkingLot([self.floor], FailingPricingStrategy(), context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaisesRegex(ValueError, "No price for this ticket"):
            lot.exit_panel.check_out(
                ticket, PaymentMethod.CASH, self.start + timedelta(hours=1)
            )

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertIn(ticket.ticket_id, lot.active_tickets)
        self.assertEqual(context.payments_by_ticket, {})

    def test_invalid_payment_method_keeps_ticket_and_spot_open(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaises(ValueError):
            lot.exit_panel.check_out(ticket, "NOT_A_METHOD", self.start + timedelta(hours=1))

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertIn(ticket.ticket_id, lot.active_tickets)

    def test_failed_payment_verification_keeps_ticket_and_spot_open(self) -> None:
        lot = self.make_lot(FailedVerificationContext())
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaises(RuntimeError):
            lot.exit_panel.check_out(ticket, PaymentMethod.CARD, self.start + timedelta(hours=1))

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertIn(ticket.ticket_id, lot.active_tickets)

    def test_duplicate_check_in_is_rejected(self) -> None:
        lot = self.make_lot()
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaises(ValueError):
            lot.entry_panel.check_in(Car("CAR-1"), self.start)

        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertTrue(self.large_one.is_free())

    def test_no_suitable_spot_is_rejected(self) -> None:
        lot = self.make_lot()
        lot.entry_panel.check_in(ElectricCar("electric-1"), self.start)

        with self.assertRaises(ValueError):
            lot.entry_panel.check_in(ElectricCar("electric-2"), self.start)

        self.assertEqual(len(lot.active_tickets), 1)

    def test_exit_before_entry_is_rejected_without_payment(self) -> None:
        context = PaymentContext()
        lot = self.make_lot(context)
        ticket = lot.entry_panel.check_in(Car("car-1"), self.start)

        with self.assertRaises(ValueError):
            lot.exit_panel.check_out(ticket, PaymentMethod.CASH, self.start - timedelta(seconds=1))

        self.assertEqual(ticket.status, "OPEN")
        self.assertIs(self.compact.vehicle, ticket.vehicle)
        self.assertEqual(context.payments_by_ticket, {})


if __name__ == "__main__":
    unittest.main()
