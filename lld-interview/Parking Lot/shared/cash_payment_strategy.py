from decimal import Decimal

from shared.payment_strategy import PaymentStrategy


class CashPayment(PaymentStrategy):
    def __init__(self, tendered: Decimal) -> None:
        self.tendered: Decimal = tendered

    def pay(self, amount: Decimal) -> bool:
        return self.tendered >= amount