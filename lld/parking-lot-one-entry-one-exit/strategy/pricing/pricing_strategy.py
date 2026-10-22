

from datetime import datetime
from parking_ticket import ParkingTicket

class PricingStrategy:
    """New pricing rules implement calculate_fee without changing checkout."""

    def calculate_fee(self, ticket: ParkingTicket, exit_time: datetime) -> int:
        """Return the ticket's fee in non-negative integer cents."""
        raise NotImplementedError("Subclasses must implement calculate_fee()")
