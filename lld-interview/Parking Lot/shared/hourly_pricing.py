from datetime import datetime
from decimal import Decimal

from shared.charge import Charge
from shared.parking_charge import ParkingCharge
from shared.pricing_strategy import PricingStrategy
from shared.vehicle_type import VehicleType


class HourlyPricing(PricingStrategy):
    """Per started hour, minimum 1 hour. 61 minutes = 2 hours."""

    def __init__(self, rate_per_hour: dict[VehicleType, Decimal]):
        self.rate_per_hour = rate_per_hour

    def parking_charge(self, vehicle_type: VehicleType, entry: datetime, exit_time: datetime) -> Charge:
        # Calculate duration in minutes using standard datetime subtraction
        duration_seconds = (exit_time - entry).total_seconds()
        minutes = int(duration_seconds // 60)
        
        # Round up to the next full hour, with a minimum of 1 hour
        hours = max(1, (minutes + 59) // 60)
        
        rate = self.rate_per_hour.get(vehicle_type)
        return ParkingCharge(hours, rate)