
from shared.paid_state import PaidState
from shared.ticket_state import TicketState
from shared.ticket_status import TicketStatus

class ActiveState(TicketState):
    def status(self):
        return TicketStatus.ACTIVE

    def can_pay(self):
        return True

    def pay(self, t):
        t.set_state(PaidState())

    def add_charge(self, t, c):
        t.add_charge_internal(c)