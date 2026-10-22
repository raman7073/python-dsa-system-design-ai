import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread

from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import ParkingSpot, SpotFitPolicy, SpotType
from payment import (
    CardPaymentStrategy,
    CashPaymentStrategy,
    DigitalWalletPaymentStrategy,
    PaymentGateway,
    PaymentMethod,
    PaymentStrategy,
    Payment,
)
from payment_repository import InMemoryPaymentRepository, PaymentRecord
from pricing import HourlyPricingStrategy
from spot_allocation import SpotAllocation, SpotAllocationStrategy
from vehicle import Car, Motorcycle, Truck, Vehicle, VehicleType
from vehicle_factory import VehicleFactory


class TestGateway(PaymentGateway):
    def __init__(self) -> None:
        self.charges = []

    def charge(self, amount: Decimal, payment_token: str, idempotency_key: str) -> str:
        self.charges.append((amount, payment_token, idempotency_key))
        return f"transaction-{len(self.charges)}"


class LastCompatibleSpotStrategy(SpotAllocationStrategy):
    def find_spot(self, floors, vehicle):
        for floor in reversed(floors):
            for spot in reversed(floor.spots):
                if not spot.is_occupied and spot.can_fit_vehicle(vehicle):
                    return SpotAllocation(floor, spot)
        return None


class FailingOnceRepository(InMemoryPaymentRepository):
    def __init__(self, fail_after_write: bool) -> None:
        super().__init__()
        self.fail_after_write = fail_after_write
        self.failed = False

    def add(self, record: PaymentRecord) -> None:
        if not self.failed:
            self.failed = True
            if self.fail_after_write:
                super().add(record)
            raise RuntimeError("repository unavailable")
        super().add(record)


class IdempotentGateway(PaymentGateway):
    def __init__(self) -> None:
        self.charges = {}

    def charge(self, amount: Decimal, payment_token: str, idempotency_key: str) -> str:
        if idempotency_key not in self.charges:
            self.charges[idempotency_key] = (amount, payment_token)
        return idempotency_key


class UnderpayingStrategy(PaymentStrategy):
    def process_payment(self, amount: Decimal, idempotency_key: str) -> Payment:
        return Payment(
            idempotency_key,
            amount - Decimal("0.01"),
            PaymentMethod.CASH,
            None,
            datetime.now(timezone.utc),
        )


class ParkingLotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.floor = ParkingFloor(
            1,
            [
                ParkingSpot("compact-1", SpotType.COMPACT),
                ParkingSpot("regular-1", SpotType.REGULAR),
                ParkingSpot("large-1", SpotType.LARGE),
            ],
        )
        self.lot = ParkingLot(
            [self.floor], HourlyPricingStrategy(Decimal("3.50"))
        )
        self.entry_time = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)

    def test_vehicle_plates_are_normalized(self) -> None:
        self.assertEqual(Car("  ab-123 ").license_plate, "AB-123")

    def test_spot_fit_uses_vehicle_rules_not_enum_values(self) -> None:
        compact, regular, large = self.floor.spots
        self.assertTrue(compact.can_fit_vehicle(Motorcycle("m-1")))
        self.assertFalse(compact.can_fit_vehicle(Car("c-1")))
        self.assertTrue(regular.can_fit_vehicle(Car("c-2")))
        self.assertFalse(regular.can_fit_vehicle(Truck("t-1")))
        self.assertTrue(large.can_fit_vehicle(Truck("t-2")))

    def test_new_vehicle_kind_uses_registered_constructor_and_fit_rule(self) -> None:
        factory = VehicleFactory()
        factory.register("BUS", lambda plate: Vehicle(plate, "BUS"))
        bus = factory.create_vehicle("BUS", "bus-1")
        fit_policy = SpotFitPolicy().with_rule("BUS", {SpotType.LARGE})
        floor = ParkingFloor(
            2,
            [ParkingSpot("bus-space", SpotType.LARGE, fit_policy=fit_policy)],
        )
        lot = ParkingLot([floor], HourlyPricingStrategy(Decimal("3.50")))
        ticket = lot.park_vehicle(bus, self.entry_time)
        self.assertEqual(ticket.spot_id, "bus-space")

    def test_park_price_pay_and_exit(self) -> None:
        ticket = self.lot.park_vehicle(Car("car-1"), self.entry_time)
        payment = self.lot.exit_vehicle(
            ticket.ticket_id,
            CashPaymentStrategy(Decimal("12.00")),
            self.entry_time + timedelta(hours=2, minutes=1),
        )
        self.assertEqual(payment.fee, Decimal("10.50"))
        records = self.lot.payments_for_ticket(payment.ticket_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].ticket_id, payment.ticket_id)
        self.assertEqual(records[0].payment.method, PaymentMethod.CASH)
        self.assertEqual(records[0].payment.change_due, Decimal("1.50"))
        self.assertFalse(hasattr(payment, "payment"))
        self.assertFalse(self.lot.floors[0].spots[1].is_occupied)
        self.assertFalse(payment.is_active)

    def test_payment_repository_keeps_multiple_records_per_ticket(self) -> None:
        repository = InMemoryPaymentRepository()
        cash_strategy = CashPaymentStrategy(Decimal("5.00"))
        first_payment = cash_strategy.process_payment(
            Decimal("5.00"), "payment-1"
        )
        second_payment = cash_strategy.process_payment(
            Decimal("2.00"), "payment-2"
        )
        repository.add(PaymentRecord("ticket-1", first_payment))
        repository.add(PaymentRecord("ticket-1", second_payment))
        repository.add(PaymentRecord("ticket-2", first_payment))

        ticket_records = repository.get_by_ticket_id("ticket-1")
        self.assertEqual(len(ticket_records), 2)
        self.assertEqual(
            [record.payment.amount for record in ticket_records],
            [Decimal("5.00"), Decimal("2.00")],
        )
        self.assertEqual(len(repository.get_by_ticket_id("ticket-2")), 1)

    def test_failed_payment_keeps_ticket_and_spot_active(self) -> None:
        ticket = self.lot.park_vehicle(Car("car-2"), self.entry_time)
        with self.assertRaisesRegex(ValueError, "less than"):
            self.lot.exit_vehicle(
                ticket.ticket_id,
                CashPaymentStrategy(Decimal("1.00")),
                self.entry_time + timedelta(hours=1),
            )
        self.assertTrue(ticket.is_active)
        self.assertTrue(self.lot.floors[0].spots[1].is_occupied)

    def test_duplicate_active_plate_is_rejected(self) -> None:
        self.lot.park_vehicle(Car("car-3"), self.entry_time)
        with self.assertRaisesRegex(ValueError, "already has an active ticket"):
            self.lot.park_vehicle(Car(" CAR-3 "))

    def test_no_fitting_spot_is_reported(self) -> None:
        self.lot.park_vehicle(Motorcycle("occupied-compact"), self.entry_time)
        self.lot.park_vehicle(Car("occupied-regular"), self.entry_time)
        self.lot.park_vehicle(Truck("occupied-large"), self.entry_time)
        with self.assertRaisesRegex(RuntimeError, "No available spot"):
            self.lot.park_vehicle(Truck("truck-1"))

    def test_initial_occupancy_without_ticket_is_rejected(self) -> None:
        self.floor.spots[0].park(Motorcycle("untracked"))
        with self.assertRaisesRegex(ValueError, "untracked occupied"):
            ParkingLot([self.floor], HourlyPricingStrategy(Decimal("3.50")))

    def test_custom_allocation_strategy_is_injected(self) -> None:
        lot = ParkingLot(
            [self.floor],
            HourlyPricingStrategy(Decimal("3.50")),
            LastCompatibleSpotStrategy(),
        )
        ticket = lot.park_vehicle(Car("car-custom"), self.entry_time)
        self.assertEqual(ticket.spot_id, "large-1")

    def test_card_and_wallet_strategies_use_gateway(self) -> None:
        gateway = TestGateway()
        ticket = self.lot.park_vehicle(Car("car-4"), self.entry_time)
        card_result = self.lot.exit_vehicle(
            ticket.ticket_id,
            CardPaymentStrategy(gateway, "opaque-card-token"),
            self.entry_time + timedelta(minutes=30),
        )
        card_records = self.lot.payments_for_ticket(card_result.ticket_id)
        self.assertEqual(card_records[0].payment.method, PaymentMethod.CARD)
        self.assertEqual(gateway.charges[0][1], "opaque-card-token")

        second_ticket = self.lot.park_vehicle(Car("car-5"), self.entry_time)
        wallet_result = self.lot.exit_vehicle(
            second_ticket.ticket_id,
            DigitalWalletPaymentStrategy(gateway, "opaque-wallet-token"),
            self.entry_time + timedelta(minutes=30),
        )
        wallet_records = self.lot.payments_for_ticket(wallet_result.ticket_id)
        self.assertEqual(
            wallet_records[0].payment.method, PaymentMethod.DIGITAL_WALLET
        )
        self.assertEqual(len(gateway.charges), 2)

    def test_hourly_pricing_rounds_up_started_hours(self) -> None:
        pricing = HourlyPricingStrategy(Decimal("2.00"))
        self.assertEqual(
            pricing.calculate_fee(
                self.entry_time,
                self.entry_time + timedelta(hours=1, microseconds=1),
                Car("car-6"),
            ),
            Decimal("4.00"),
        )

    def test_naive_timestamps_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.lot.park_vehicle(Car("car-7"), datetime(2026, 1, 1, 10))

    def test_ticket_and_floor_snapshots_cannot_change_lot_state(self) -> None:
        ticket = self.lot.park_vehicle(Car("car-8"), self.entry_time)
        with self.assertRaises(FrozenInstanceError):
            ticket.spot_id = "large-1"
        snapshot = self.lot.floors[0].spots[1]
        snapshot.remove_vehicle()
        self.floor.spots[1].park(Car("unrelated"))
        self.assertTrue(self.lot.floors[0].spots[1].is_occupied)
        self.lot.exit_vehicle(
            ticket.ticket_id,
            CashPaymentStrategy(Decimal("3.50")),
            self.entry_time + timedelta(minutes=1),
        )

    def test_retry_after_repository_failure_does_not_charge_again(self) -> None:
        for fail_after_write in (False, True):
            with self.subTest(fail_after_write=fail_after_write):
                repository = FailingOnceRepository(fail_after_write)
                lot = ParkingLot(
                    [self.floor],
                    HourlyPricingStrategy(Decimal("3.50")),
                    payment_repository=repository,
                )
                gateway = IdempotentGateway()
                ticket = lot.park_vehicle(Car(f"retry-{fail_after_write}"), self.entry_time)
                strategy = CardPaymentStrategy(gateway, "token")
                with self.assertRaisesRegex(RuntimeError, "repository unavailable"):
                    lot.exit_vehicle(
                        ticket.ticket_id,
                        strategy,
                        self.entry_time + timedelta(minutes=1),
                    )
                self.assertTrue(lot.floors[0].spots[1].is_occupied)
                completed = lot.exit_vehicle(ticket.ticket_id, strategy)
                self.assertFalse(completed.is_active)
                self.assertEqual(len(gateway.charges), 1)
                self.assertEqual(len(lot.payments_for_ticket(ticket.ticket_id)), 1)

    def test_insufficient_cash_can_be_retried_with_more_cash(self) -> None:
        ticket = self.lot.park_vehicle(Car("car-9"), self.entry_time)
        with self.assertRaisesRegex(ValueError, "less than"):
            self.lot.exit_vehicle(
                ticket.ticket_id,
                CashPaymentStrategy(Decimal("1.00")),
                self.entry_time + timedelta(minutes=1),
            )
        completed = self.lot.exit_vehicle(
            ticket.ticket_id, CashPaymentStrategy(Decimal("5.00"))
        )
        self.assertEqual(completed.fee, Decimal("3.50"))

    def test_invalid_payment_result_does_not_release_spot(self) -> None:
        ticket = self.lot.park_vehicle(Car("car-10"), self.entry_time)
        with self.assertRaisesRegex(RuntimeError, "invalid payment"):
            self.lot.exit_vehicle(
                ticket.ticket_id,
                UnderpayingStrategy(),
                self.entry_time + timedelta(minutes=1),
            )
        self.assertTrue(self.lot.floors[0].spots[1].is_occupied)

    def test_slow_gateway_does_not_block_another_entry(self) -> None:
        started = Event()
        release = Event()

        class SlowGateway(PaymentGateway):
            def charge(self, amount, payment_token, idempotency_key):
                started.set()
                if not release.wait(3):
                    raise TimeoutError("gateway timed out")
                return idempotency_key

        ticket = self.lot.park_vehicle(Car("car-11"), self.entry_time)
        failures = []

        def exit_in_background():
            try:
                self.lot.exit_vehicle(
                    ticket.ticket_id,
                    CardPaymentStrategy(SlowGateway(), "token"),
                    self.entry_time + timedelta(minutes=1),
                )
            except Exception as error:
                failures.append(error)

        worker = Thread(target=exit_in_background)
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            second = self.lot.park_vehicle(Car("car-12"), self.entry_time)
            self.assertEqual(second.spot_id, "large-1")
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(failures)


if __name__ == "__main__":
    unittest.main()
