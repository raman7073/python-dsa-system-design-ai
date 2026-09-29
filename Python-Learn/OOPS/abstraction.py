from abc import ABC, abstractmethod


class PaymentMethod(ABC):
    @abstractmethod
    def pay(self, amount):
        pass


class UPIPayment(PaymentMethod):
    def pay(self, amount):
        # UPI-specific processing would happen here.
        print(f"Processing ₹{amount} through UPI")


class CardPayment(PaymentMethod):
    def pay(self, amount):
        # Card-specific processing would happen here.
        print(f"Processing ₹{amount} through a card")


def checkout(payment_method: PaymentMethod, amount):
    payment_method.pay(amount)


checkout(UPIPayment(), 500)
checkout(CardPayment(), 1000)
