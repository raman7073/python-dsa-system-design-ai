# Parking lot with one entry and one exit

This folder implements the parking lot in the diagram using ordinary Python classes and methods. It uses basic type hints, but no dataclasses, enums, or abstract base classes. Each class has a small job, and the program keeps its data in memory.

From this folder, run:

```bash
python main.py
python -m unittest -v
```

Type hints describe the values a method expects and returns. For example, `amount: int` means an amount is an integer, and `-> Payment` means the method returns a `Payment`. `-> None` means it returns no value. `PaymentContext | None` means the value can be a payment context or `None`. Python does not enforce these hints at runtime. The `|` form needs Python 3.10 or newer.

The panels use `TYPE_CHECKING` to name `ParkingLot` in their hints without importing it while the program runs. This avoids an import loop between the lot and its panels.

## Read the files in this order

1. [vehicle.py](./vehicle.py) defines the five vehicle classes: `Car`, `Truck`, `ElectricCar`, `Motorbike`, and `Van`.
2. [vehicle_factory.py](./vehicle_factory.py) creates vehicles by type and lets callers register new constructors.
3. [parking_spot.py](./parking_spot.py) defines the spot classes and the `park()` / `vacate()` actions.
4. [parking_floor.py](./parking_floor.py) groups the spots on a floor and finds a compatible free spot.
5. [parking_ticket.py](./parking_ticket.py) records the vehicle, spot, and entry time.
6. [hourly_cost.py](./hourly_cost.py) stores each spot type's hourly rate.
7. [pricing.py](./pricing.py) defines the pricing strategy interface and its time based and event based implementations.
8. [payment.py](./payment.py) defines cash and card payment strategies, payment records, and the context that selects and runs a payment strategy.
9. [entry_panel.py](./entry_panel.py) checks a vehicle in; [exit_panel.py](./exit_panel.py) checks its ticket out.
10. [parking_lot.py](./parking_lot.py) connects one entry panel, one exit panel, and the floors.
11. [main.py](./main.py) shows the complete trip.

## How the diagram becomes code

```text
VehicleFactory.create_vehicle() → EntryPanel.check_in() → ParkingFloor finds a spot
    → ParkingSpot.park() → ParkingTicket

ParkingTicket → ExitPanel.check_out() → PricingStrategy.calculate_fee()
    → PaymentContext.pay() → PaymentStrategy.process_payment()
    → ParkingSpot.vacate()
```

Create a lot with `ParkingLot(floors, pricing_strategy, payment_context)`. Its constructor creates exactly one entry panel and one exit panel, and both panels refer to that lot. The payment context is optional; if you leave it out, the lot creates one.

```python
first_lot = ParkingLot(
    [first_floor], TimeBasedPricingStrategy(HourlyCost(first_rates))
)
second_lot = ParkingLot([second_floor], EventBasedPricingStrategy(1500))
```

These are separate parking lots. Each has its own floors, active tickets, panels, pricing, and payment context.

## Vehicle factory

Create vehicles through `VehicleFactory`. It registers the five built-in types and chooses their constructors by `VehicleType`. The entry panel still accepts a `Vehicle` object, so the same factory can be used with any lot. Directly constructing `Car`, `Truck`, and the other built-in classes remains supported.

```python
from vehicle import VehicleType
from vehicle_factory import VehicleFactory

factory = VehicleFactory()
car = factory.create_vehicle(VehicleType.CAR, "ABC-123")
accessible_car = factory.create_vehicle(
    VehicleType.CAR, "ACCESS-1", accessible=True
)
ticket = lot.entry_panel.check_in(car)
```

Register a constructor to add another vehicle type. A constructor receives the registration number and returns a `Vehicle` of the registered type. `register()` rejects an existing type unless you explicitly pass `replace=True`.

```python
from parking_floor import ParkingFloor
from parking_lot import ParkingLot
from parking_spot import ParkingSpot
from pricing import EventBasedPricingStrategy
from vehicle import Vehicle


class Bus(Vehicle):
    def __init__(self, registration_no: str) -> None:
        super().__init__(registration_no, "bus")


class BusSpot(ParkingSpot):
    def __init__(self, spot_id: str, floor_id: str) -> None:
        super().__init__(spot_id, floor_id, "bus")

    def can_fit(self, vehicle: Vehicle) -> bool:
        return vehicle.get_vehicle_type() == "bus"


factory.register("bus", Bus)
bus = factory.create_vehicle("bus", "BUS-1")
bus_floor = ParkingFloor("F2", [BusSpot("B1", "F2")])
bus_lot = ParkingLot([bus_floor], EventBasedPricingStrategy(500))
bus_ticket = bus_lot.entry_panel.check_in(bus)
```

The floor checks each custom spot's `can_fit()` rule for new vehicle types, so the new type can park without changing the built-in vehicle classes or the entry panel.

`TimeBasedPricingStrategy` charges by spot type for each started hour; a zero-length stay costs nothing. It calculates elapsed time using UTC instants, so daylight saving changes do not alter the charge. `EventBasedPricingStrategy` charges its configured event fee once per ticket, regardless of stay length or spot type. Passing `HourlyCost` directly, or with the old `hourly_cost=` keyword, still selects time based pricing for older callers.

The diagram labels `ParkingLot` as a singleton, but that would make it hard to represent two physical lots or test each lot independently. Keeping one entry and one exit panel **per lot** satisfies the diagram's panel requirement without sharing all lot state globally.

To add another rule, subclass `PricingStrategy` and implement `calculate_fee(ticket, exit_time) -> int`. Return non-negative integer cents. The exit panel validates the stay timestamps before calling the strategy, then passes its result to the payment context. No changes to either panel or the lot are needed for another strategy.

## Payment strategies

At checkout, pass `CashPaymentStrategy(tendered_cents=1500)` or `CardPaymentStrategy(gateway)`. A cash payment fails if the tendered amount is too small. A card gateway implements `charge(ticket_id, amount) -> bool`; the ticket ID lets it recognize a retry. Without a tendered amount or gateway, the built-in strategies use the example's in-memory successful payment behavior. The older `PaymentMethod.CASH` and `PaymentMethod.CARD` strings still work.

`PaymentContext` is the Strategy pattern's context: it chooses a registered strategy by method name or accepts one directly, delegates processing to that strategy, and records the result. To add another payment method, subclass `PaymentStrategy`, set its `method` name, and implement `process_payment(ticket_id, amount)` to return `PaymentStatus.SUCCESS` or `PaymentStatus.FAILED`. This synchronous checkout does not support pending payments. Pass the strategy directly to `check_out()`, or call `PaymentContext.register_strategy()` and pass its method name. The context stores successful payments once per ticket. Failed attempts can be retried, and the car stays parked until payment verification succeeds. If verification temporarily fails after a successful charge, retrying the same fee verifies the recorded payment without charging again. `PaymentService` remains an alias for existing callers.

Spot types and vehicle types are simple named values. A car can use a compact or large car spot; a truck or van needs a large car spot; an electric car uses an electric car spot; and a motorbike uses a motorcycle spot. The disabled spot is included to match the diagram and needs an eligible vehicle. The compatibility rule lives in [parking_spot.py](./parking_spot.py), so read that file for the precise checks.

Money is an integer number of **cents**. A rate of `500` means $5.00 per started hour. The example stays for 2 hours and 10 minutes, so it pays for 3 hours. The default payment strategies do not connect to a real bank.

This is a learning example. It runs in one Python process, keeps no data after the program ends, and assumes one operation happens at a time.
