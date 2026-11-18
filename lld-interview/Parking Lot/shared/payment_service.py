from shared.bill import Bill
from shared.payment_failed_exception import PaymentFailedError
from shared.payment_strategy import PaymentStrategy



class PaymentService:
    """The only place money is taken."""

    def collect(self, bill: Bill, method: PaymentStrategy) -> None:
        total_amount = bill.total()
        if not method.pay(total_amount):
            raise PaymentFailedError(f"Payment of Rs {total_amount} failed")