class ParkingFullError(RuntimeError):
    """Equivalent to Java's ParkingFullException."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)