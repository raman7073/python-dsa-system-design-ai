from datetime import datetime

from parking_lot_v5.ticket import Ticket
from shared.bill import Bill
from shared.charge import Charge
from shared.pricing_strategy import PricingStrategy


class FeeCalculator:
    """Pricing lives here, not on Ticket (Single Responsibility)."""

    def __init__(self, pricing: PricingStrategy) -> None:
        self.pricing: PricingStrategy = pricing

    def build_bill(self, t: Ticket, exit_time: datetime) -> Bill:
        charges: list[Charge] = []
        
        # Calculate parking charge using the pricing strategy
        parking_charge = self.pricing.parking_charge(t.vehicle.type, t.entry_time, exit_time)
        charges.append(parking_charge)
        
        # Add any extra charges from the ticket
        charges.extend(t.extra_charges())
        
        return Bill(t.id, charges)