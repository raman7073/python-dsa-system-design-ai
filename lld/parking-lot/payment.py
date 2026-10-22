from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class PaymentMethod(Enum):
    CASH = "cash"
    CARD = "card"
    DIGITAL_WALLET = "digital_wallet"


@dataclass(frozen=True)
class Payment:
    payment_id: str
    amount: Decimal
    method: PaymentMethod
    transaction_id: str | None
    created_at: datetime
    change_due: Decimal = Decimal("0.00")


class PaymentStrategy(ABC):
    @abstractmethod
    def process_payment(self, amount: Decimal, idempotency_key: str) -> Payment:
        """Collect an amount once for a stable idempotency key."""


class PaymentDeclinedError(ValueError):
    """A known failure for which no money was collected."""


class CashPaymentStrategy(PaymentStrategy):
    def __init__(self, tendered: Decimal) -> None:
        if not isinstance(tendered, Decimal) or not tendered.is_finite() or tendered < 0:
            raise ValueError("Cash tendered must be a finite, non-negative Decimal")
        self._tendered = tendered

    def process_payment(self, amount: Decimal, idempotency_key: str) -> Payment:
        amount = _validate_amount(amount)
        tendered = _validate_amount(self._tendered)
        if tendered < amount:
            raise PaymentDeclinedError("Cash tendered is less than the amount due")
        return _new_payment(
            amount, PaymentMethod.CASH, None, idempotency_key, tendered - amount
        )


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, amount: Decimal, payment_token: str, idempotency_key: str) -> str:
        """Return the same charge reference when the key is retried."""


class _GatewayPaymentStrategy(PaymentStrategy):
    method: PaymentMethod

    def __init__(self, gateway: PaymentGateway, payment_token: str) -> None:
        if not isinstance(payment_token, str) or not payment_token.strip():
            raise ValueError("Payment requires a non-empty provider token")
        self._gateway = gateway
        self._payment_token = payment_token

    def process_payment(self, amount: Decimal, idempotency_key: str) -> Payment:
        amount = _validate_amount(amount)
        transaction_id = self._gateway.charge(
            amount, self._payment_token, idempotency_key
        )
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise RuntimeError("Payment gateway did not return a transaction reference")
        return _new_payment(amount, self.method, transaction_id, idempotency_key)


class CardPaymentStrategy(_GatewayPaymentStrategy):
    method = PaymentMethod.CARD


class DigitalWalletPaymentStrategy(_GatewayPaymentStrategy):
    method = PaymentMethod.DIGITAL_WALLET


def _validate_amount(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise ValueError("Payment amount must be a finite, non-negative Decimal")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Payment amount must be in whole cents")
    return amount


def _new_payment(
    amount: Decimal,
    method: PaymentMethod,
    transaction_id: str | None,
    idempotency_key: str,
    change_due: Decimal = Decimal("0.00"),
) -> Payment:
    return Payment(
        payment_id=idempotency_key,
        amount=amount,
        method=method,
        transaction_id=transaction_id,
        created_at=datetime.now(timezone.utc),
        change_due=change_due,
    )
