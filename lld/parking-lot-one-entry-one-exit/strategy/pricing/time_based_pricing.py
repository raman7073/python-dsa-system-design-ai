from datetime import datetime
from parking_ticket import ParkingTicket
from pricing_strategy import PricingStrategy
from utils import billable_hours, stay_duration
from hourly_cost import HourlyCost

class TimeBasedPricingStrategy(PricingStrategy):
    """Price each started hour using the ticket's spot type."""

    def __init__(self, hourly_cost: HourlyCost) -> None:
        self.hourly_cost = hourly_cost

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        hours = billable_hours(ticket, exit_time)
        return self.hourly_cost.calculate(ticket.spot.spot_type, hours)
