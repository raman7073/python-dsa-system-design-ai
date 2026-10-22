from datetime import datetime
from email import utils
from parking_ticket import ParkingTicket
from pricing_strategy import PricingStrategy
from utils import billable_hours, stay_duration    
class EventBasedPricingStrategy(PricingStrategy):
    """Charge a fixed event parking fee for each ticket, regardless of stay length."""

    def __init__(self, fee_cents: int) -> None:
        if not isinstance(fee_cents, int) or fee_cents < 0:
            raise ValueError("Event fee must be non-negative integer cents")
        self.fee_cents = fee_cents

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        stay_duration(ticket, exit_time)
        return self.fee_cents
