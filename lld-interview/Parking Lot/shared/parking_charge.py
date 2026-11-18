from decimal import Decimal
from shared.charge import Charge


class ParkingCharge(Charge):
    def __init__(self, hours: int, rate_per_hour: Decimal):
        self.hours = hours
        self.rate_per_hour = rate_per_hour

    def description(self) -> str:
        return f"Parking {self.hours}h"

    def amount(self) -> Decimal:
        return self.rate_per_hour * self.hours