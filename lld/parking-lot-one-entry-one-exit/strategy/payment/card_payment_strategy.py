class CardGateway:
    """A card processor can use ticket_id to avoid charging the same ticket twice."""

    def charge(self, ticket_id: str, amount: int) -> bool:
        raise NotImplementedError("A card gateway must implement charge()")


class CardPaymentStrategy(PaymentStrategy):
    method = PaymentMethod.CARD

    def __init__(self, gateway: CardGateway | None = None) -> None:
        self.gateway = gateway

    def process_payment(self, ticket_id: str, amount: int) -> str:
        # Without a gateway, use the same successful in-memory behavior as before.
        if self.gateway is None:
            return PaymentStatus.SUCCESS
        approved = self.gateway.charge(ticket_id, amount)
        if not isinstance(approved, bool):
            raise ValueError("Card gateway must return an approval boolean")
        return PaymentStatus.SUCCESS if approved else PaymentStatus.FAILED

