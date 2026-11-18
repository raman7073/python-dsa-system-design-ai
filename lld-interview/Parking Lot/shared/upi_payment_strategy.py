from decimal import Decimal

from shared.payment_strategy import PaymentStrategy


class UpiPayment(PaymentStrategy):
    def __init__(self, upi_id: str) -> None:
        self.upi_id: str = upi_id

    def pay(self, amount: Decimal) -> bool:
        return "@" in self.upi_id


class CashPayment(PaymentStrategy):
    def __init__(self, tendered: Decimal) -> None:
        self.tendered: Decimal = tendered

    def pay(self, amount: Decimal) -> bool:
        return self.tendered >= amount