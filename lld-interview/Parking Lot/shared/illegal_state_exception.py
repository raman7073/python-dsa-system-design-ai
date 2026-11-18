class IllegalStateError(RuntimeError):
    """Equivalent to Java's IllegalStateException."""
    def __init__(self, msg: str) -> None:
           super().__init__(msg)