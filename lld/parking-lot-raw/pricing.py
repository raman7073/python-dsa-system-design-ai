import math
from datetime import datetime

from parking_ticket import ParkingTicket


class PricingStrategy:
    """Every pricing rule answers the same question: what does this stay cost?"""

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        raise NotImplementedError("Subclasses must implement calculate_fee()")

    def _duration_seconds(self, ticket: ParkingTicket, exit_time: datetime) -> float:
        if exit_time < ticket.entry_time:
            raise ValueError("Exit cannot be before entry")
        return (exit_time - ticket.entry_time).total_seconds()


class HourlyPricing(PricingStrategy):
    def __init__(self, cents_per_hour: int) -> None:
        if not isinstance(cents_per_hour, int) or cents_per_hour < 0:
            raise ValueError("Hourly price must be non-negative integer cents")
        self.cents_per_hour = cents_per_hour

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        seconds = self._duration_seconds(ticket, exit_time)
        hours = math.ceil(seconds / 3600)
        return hours * self.cents_per_hour


class FlatPricing(PricingStrategy):
    """Charge one fixed amount for a parking stay, regardless of duration."""

    def __init__(self, fee_cents: int) -> None:
        if not isinstance(fee_cents, int) or fee_cents < 0:
            raise ValueError("Flat price must be non-negative integer cents")
        self.fee_cents = fee_cents

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        self._duration_seconds(ticket, exit_time)
        return self.fee_cents
