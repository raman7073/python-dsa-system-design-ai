from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from vehicle import Vehicle


class PricingStrategy(ABC):
    @abstractmethod
    def calculate_fee(
        self, entry_time: datetime, exit_time: datetime, vehicle: Vehicle
    ) -> Decimal:
        raise NotImplementedError


class HourlyPricingStrategy(PricingStrategy):
    def __init__(self, hourly_rate: Decimal) -> None:
        if not isinstance(hourly_rate, Decimal):
            raise TypeError("hourly_rate must be a Decimal")
        if not hourly_rate.is_finite() or hourly_rate < 0:
            raise ValueError("hourly_rate cannot be negative")
        self.hourly_rate = hourly_rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_fee(
        self, entry_time: datetime, exit_time: datetime, vehicle: Vehicle
    ) -> Decimal:
        del vehicle
        if (
            entry_time.tzinfo is None
            or entry_time.utcoffset() is None
            or exit_time.tzinfo is None
            or exit_time.utcoffset() is None
        ):
            raise ValueError("Parking timestamps must include a timezone")
        duration = exit_time - entry_time
        if duration < timedelta(0):
            raise ValueError("exit_time cannot be earlier than entry_time")
        duration_microseconds = (
            duration.days * 86_400_000_000
            + duration.seconds * 1_000_000
            + duration.microseconds
        )
        if duration_microseconds == 0:
            return Decimal("0.00")

        microseconds_per_hour = 3_600_000_000
        billable_hours = (
            duration_microseconds + microseconds_per_hour - 1
        ) // microseconds_per_hour
        fee = self.hourly_rate * billable_hours
        return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
