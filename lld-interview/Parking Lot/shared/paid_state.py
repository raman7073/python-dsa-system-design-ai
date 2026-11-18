from shared.completed_state import CompletedState
from shared.ticket_state import TicketState
from shared.ticket_status import TicketStatus


class PaidState(TicketState):
    def status(self):
        return TicketStatus.PAID

    def exit(self, t):
        t.set_state(CompletedState())