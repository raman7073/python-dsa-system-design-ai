from decimal import Decimal

from shared.charge import Charge


class Bill:
    def __init__(self, ticket_id: str, charges: list[Charge]):
        self.ticket_id = ticket_id
        self.charges = charges

    def total(self) -> Decimal:
        # Replaces Java's stream().map(...).reduce(BigDecimal.ZERO, BigDecimal::add)
        return sum((c.amount() for c in self.charges), Decimal("0.00"))