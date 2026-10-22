class CashPaymentStrategy(PaymentStrategy):
    method = PaymentMethod.CASH

    def __init__(self, tendered_cents: int | None = None) -> None:
        if tendered_cents is not None and (
            not isinstance(tendered_cents, int) or tendered_cents < 0
        ):
            raise ValueError("Cash tendered must be non-negative integer cents")
        self.tendered_cents = tendered_cents

    def process_payment(self, ticket_id: str, amount: int) -> str:
        # With no tendered amount, this in-memory example assumes exact cash.
        if self.tendered_cents is not None and self.tendered_cents < amount:
            return PaymentStatus.FAILED
        return PaymentStatus.SUCCESS

