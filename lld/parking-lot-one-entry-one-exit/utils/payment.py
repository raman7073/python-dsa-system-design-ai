from datetime import datetime, timezone
from uuid import uuid4


class PaymentMethod:
    CASH: str = "CASH"
    CARD: str = "CARD"


class PaymentStatus:
    PENDING: str = "PENDING"
    SUCCESS: str = "SUCCESS"
    FAILED: str = "FAILED"


class Payment:
    def __init__(self, ticket_id: str, amount: int, method: str, status: str) -> None:
        self.payment_id: str = str(uuid4())
        self.ticket_id: str = ticket_id
        self.amount: int = amount
        self.method: str = method
        self.status: str = status
        self.created_at: datetime = datetime.now(timezone.utc)


