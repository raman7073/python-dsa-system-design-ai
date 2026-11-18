from shared.ticket_state import TicketState
from shared.ticket_status import TicketStatus


class CompletedState(TicketState):
    """Terminal: every action throws."""

    def status(self):
        return TicketStatus.COMPLETED