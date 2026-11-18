
from shared.illegal_state_exception import IllegalStateError


class TicketState:
    """State pattern: each state allows only its legal moves. Everything else throws."""

    def status(self):
        raise NotImplementedError("Subclasses must implement status()")

    def can_pay(self):
        return False

    def pay(self, t):
        raise self._illegal("pay")

    def exit(self, t):
        raise self._illegal("exit")

    def add_charge(self, t, c):
        raise self._illegal("add a charge")

    def _illegal(self, action):
        return IllegalStateError(f"Cannot {action}: ticket is {self.status()}")