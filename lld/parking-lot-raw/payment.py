class Payment:
    def __init__(
        self,
        amount_cents: int,
        method: str,
        transaction_id: str | None = None,
        change_cents: int = 0,
    ) -> None:
        self.amount_cents = amount_cents
        self.method = method
        self.transaction_id = transaction_id
        self.change_cents = change_cents


class PaymentMethod:
    def pay(self, amount_cents: int, ticket_id: str) -> Payment:
        raise NotImplementedError("Subclasses must implement pay()")


class PaymentGateway:
    def charge(self, amount_cents: int, token: str, ticket_id: str) -> str:
        raise NotImplementedError("A gateway must implement charge()")


class CashPayment(PaymentMethod):
    def __init__(self, tendered_cents: int) -> None:
        self.tendered_cents = tendered_cents

    def pay(self, amount_cents: int, ticket_id: str) -> Payment:
        if not isinstance(self.tendered_cents, int) or self.tendered_cents < amount_cents:
            raise ValueError("Not enough cash was tendered")
        change = self.tendered_cents - amount_cents
        return Payment(amount_cents, "cash", change_cents=change)


class CardPayment(PaymentMethod):
    def __init__(self, gateway: PaymentGateway, token: str) -> None:
        self.gateway = gateway
        self.token = token

    def pay(self, amount_cents: int, ticket_id: str) -> Payment:
        # The ticket ID lets the gateway identify a repeated payment request.
        transaction_id = self.gateway.charge(amount_cents, self.token, ticket_id)
        return Payment(amount_cents, "card", transaction_id)


class WalletPayment(PaymentMethod):
    def __init__(self, gateway: PaymentGateway, token: str) -> None:
        self.gateway = gateway
        self.token = token

    def pay(self, amount_cents: int, ticket_id: str) -> Payment:
        transaction_id = self.gateway.charge(amount_cents, self.token, ticket_id)
        return Payment(amount_cents, "wallet", transaction_id)
