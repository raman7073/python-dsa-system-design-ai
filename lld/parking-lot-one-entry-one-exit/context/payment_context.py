class PaymentContext:
    """Select a payment strategy and record the result for each ticket."""

    def __init__(self) -> None:
        self.payments_by_ticket: dict[str, Payment] = {}
        self.payments_by_id: dict[str, Payment] = {}
        self.strategies: dict[str, PaymentStrategy] = {}
        self.register_strategy(CashPaymentStrategy())
        self.register_strategy(CardPaymentStrategy())

    def register_strategy(self, strategy: PaymentStrategy) -> None:
        self._check_strategy(strategy)
        self.strategies[strategy.method] = strategy

    def pay(
        self, ticket_id: str, amount: int, method: str | PaymentStrategy
    ) -> Payment:
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("Payment amount must be non-negative integer cents")
        if isinstance(method, str):
            strategy = self.strategies.get(method)
            if strategy is None:
                raise ValueError("Unknown payment method")
        else:
            self._check_strategy(method)
            strategy = method

        existing = self.payments_by_ticket.get(ticket_id)
        if existing is not None:
            if existing.amount != amount or existing.method != strategy.method:
                raise ValueError("This ticket already has a different payment")
            return existing

        status = strategy.process_payment(ticket_id, amount)
        if status == PaymentStatus.PENDING:
            raise ValueError("Pending payments are not supported by checkout")
        if status not in (PaymentStatus.SUCCESS, PaymentStatus.FAILED):
            raise ValueError("Payment strategy returned an unknown status")
        payment = Payment(ticket_id, amount, strategy.method, status)
        self.payments_by_id[payment.payment_id] = payment
        if status == PaymentStatus.SUCCESS:
            self.payments_by_ticket[ticket_id] = payment
        return payment

    def _check_strategy(self, strategy: PaymentStrategy) -> None:
        method = getattr(strategy, "method", None)
        if not isinstance(method, str) or not method or not callable(
            getattr(strategy, "process_payment", None)
        ):
            raise ValueError("A payment strategy needs a method and process_payment()")

    def verify(self, payment_id: str) -> str:
        payment = self.payments_by_id.get(payment_id)
        if payment is None:
            raise ValueError("Payment was not found")
        return payment.status


