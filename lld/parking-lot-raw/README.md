# Parking lot in plain Python

This version uses small files, ordinary classes, lists, dictionaries, and methods. It has basic type hints, but no dataclasses, abstract base classes, or enums. Type hints tell the reader what a method expects and returns; Python does not enforce them at runtime.

Run the example from this folder:

```bash
python main.py
```

Run the tests:

```bash
python -m unittest -v test_parking_lot.py
```

## Read the code in this order

1. [vehicle.py](./vehicle.py): each vehicle has a plate and a kind.
2. [parking_spot.py](./parking_spot.py) and [parking_floor.py](./parking_floor.py): a floor owns spots; a spot knows which vehicles fit.
3. [spot_finder.py](./spot_finder.py): searches floors for an open, suitable spot.
4. [parking_ticket.py](./parking_ticket.py): records where and when a vehicle entered.
5. [pricing.py](./pricing.py): `HourlyPricing` charges by started hour; `FlatPricing` charges one fixed amount.
6. [payment.py](./payment.py): cash, card, and wallet payments all have a `pay()` method.
7. [parking_lot.py](./parking_lot.py): coordinates entry, exit, tickets, and payments.

The main flow is `park_vehicle()` → receive a ticket → `exit_vehicle()` → calculate fee → pay → free the spot.

## Choose a pricing strategy

Pass a pricing object when creating the lot:

```python
lot = ParkingLot([floor], HourlyPricing(500))  # $5 per started hour
lot = ParkingLot([floor], FlatPricing(800))    # $8 for the whole stay
```

Both classes inherit from `PricingStrategy` and implement `calculate_fee(ticket, exit_time)`. The lot only calls that method. A new pricing rule can use the ticket's entry time or vehicle without changing `ParkingLot`.

## Reading the type hints

- `license_plate: str` means the argument should be text.
- `-> ParkingTicket` means the method returns a ticket.
- `-> None` means the method does not return a useful value.
- `ParkingSpot | None` means the result may be a spot or `None` when no spot is found.

Money is an integer number of cents. For example, `500` means $5.00. Card and wallet payments need a gateway object with a `charge(amount_cents, token, ticket_id)` method. The ticket ID is passed so a real gateway can recognize a repeated charge request.

This is a learning version for one Python process. It does not store tickets on disk or handle several entry and exit threads at once. The more defensive implementation is in [the original folder](../parking-lot/).
