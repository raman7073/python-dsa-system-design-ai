class PaymentFailedError(RuntimeError):
    """Equivalent to Java's PaymentFailedException."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)