class PaymentStrategy:
    """Collect a payment and return a final success or failure status."""

    method: str

    def process_payment(self, ticket_id: str, amount: int) -> str:
        """Return SUCCESS or FAILED; ticket_id identifies a repeated attempt."""
        raise NotImplementedError("Subclasses must implement process_payment()")
