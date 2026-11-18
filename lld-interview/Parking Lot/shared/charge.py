from decimal import Decimal


class Charge:
    """One line on the bill. New kinds of charge = new classes; Bill never changes."""

    def description(self) -> str:
        raise NotImplementedError("Subclasses must implement description()")

    def amount(self) -> Decimal:
        raise NotImplementedError("Subclasses must implement amount()")