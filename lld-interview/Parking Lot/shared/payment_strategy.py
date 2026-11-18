from decimal import Decimal


class PaymentStrategy:
    """Interface for payment processing."""

    def pay(self, amount: Decimal) -> bool:
        """Real implementations call a payment gateway."""
        raise NotImplementedError("Subclasses must implement pay()")