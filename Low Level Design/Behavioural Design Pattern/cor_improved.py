"""
Chain of Responsibility: Expense Approval

An expense request passes along a chain of approvers. Each approver either
decides on it or passes it to the next one. The client only talks to the
head of the chain and doesn't know who actually handles the request.

    PolicyValidator -> Team Lead (<=1k) -> Manager (<=10k) -> Director (<=50k)

How each SOLID principle shows up here:
  S  Each handler has one job (check policy, or approve up to a limit).
     Handlers return a result. Printing is left to the client.
  O  To add a new approver (e.g. CFO), write or configure a new handler and
     put it in the chain. No existing class changes.
  L  Every handler can replace any other: same handle() signature, and it
     always returns an ApprovalResult or raises NoApproverFoundError.
  I  Subclasses implement only two small methods: can_handle() and process().
  D  The client depends on the abstract Approver, not on concrete classes.
     The chain is put together outside the handlers (build_chain).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


# --------------------------------------------------------------------------
# Domain objects
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpenseRequest:
    employee: str
    amount: float
    purpose: str


class Decision(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalResult:
    decision: Decision
    decided_by: str
    reason: str = ""


class NoApproverFoundError(Exception):
    """Raised when the request reaches the end of the chain unhandled."""

    def __init__(self, request: ExpenseRequest) -> None:
        super().__init__(
            f"No approver can handle {request.amount:,.2f} for '{request.purpose}'"
        )
        self.request = request


# --------------------------------------------------------------------------
# Abstract handler
# --------------------------------------------------------------------------

class Approver(ABC):
    """Base handler. The passing logic lives here once (Template Method),
    so subclasses can't forget to forward the request."""

    def __init__(self) -> None:
        self._next: Approver | None = None

    def set_next(self, approver: Approver) -> Approver:
        self._next = approver
        return approver  # allows fluent chaining: a.set_next(b).set_next(c)

    def handle(self, request: ExpenseRequest) -> ApprovalResult:
        if self.can_handle(request):
            return self.process(request)
        if self._next is None:
            raise NoApproverFoundError(request)
        return self._next.handle(request)

    @abstractmethod
    def can_handle(self, request: ExpenseRequest) -> bool: ...

    @abstractmethod
    def process(self, request: ExpenseRequest) -> ApprovalResult: ...


# --------------------------------------------------------------------------
# Concrete handlers
# --------------------------------------------------------------------------

class PolicyValidator(Approver):
    """Rejects requests that break company policy before any manager sees them."""

    def __init__(self, banned_purposes: Iterable[str]) -> None:
        super().__init__()
        self._banned = {p.lower() for p in banned_purposes}

    def can_handle(self, request: ExpenseRequest) -> bool:
        return request.amount <= 0 or request.purpose.lower() in self._banned

    def process(self, request: ExpenseRequest) -> ApprovalResult:
        if request.amount <= 0:
            reason = "amount must be positive"
        else:
            reason = f"'{request.purpose}' is not reimbursable"
        return ApprovalResult(Decision.REJECTED, "Policy", reason)


class LimitApprover(Approver):
    """Approves anything up to its spending limit.
    Team Lead, Manager and Director differ only in data, so one class
    with settings replaces three near-identical subclasses."""

    def __init__(self, title: str, limit: float) -> None:
        super().__init__()
        self.title = title
        self.limit = limit

    def can_handle(self, request: ExpenseRequest) -> bool:
        return request.amount <= self.limit

    def process(self, request: ExpenseRequest) -> ApprovalResult:
        return ApprovalResult(
            Decision.APPROVED, self.title, f"within limit of {self.limit:,.0f}"
        )


# --------------------------------------------------------------------------
# Chain assembly (kept outside the handlers)
# --------------------------------------------------------------------------

def build_chain(*approvers: Approver) -> Approver:
    """Links approvers in the order given and returns the head."""
    if not approvers:
        raise ValueError("A chain needs at least one approver.")
    for current, nxt in zip(approvers, approvers[1:]):
        current.set_next(nxt)
    return approvers[0]


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

def submit(chain: Approver, request: ExpenseRequest) -> None:
    prefix = f"{request.employee:<6} {request.amount:>11,.2f}  {request.purpose:<18}"
    try:
        result = chain.handle(request)
        print(f"{prefix} {result.decision.value.upper():<9} by {result.decided_by} ({result.reason})")
    except NoApproverFoundError as e:
        print(f"{prefix} ESCALATE  {e}")


if __name__ == "__main__":
    chain = build_chain(
        PolicyValidator(banned_purposes=["alcohol", "gambling"]),
        LimitApprover("Team Lead", 1_000),
        LimitApprover("Manager", 10_000),
        LimitApprover("Director", 50_000),
    )

    requests = [
        ExpenseRequest("Asha", 500, "Team lunch"),
        ExpenseRequest("Ravi", 7_500, "Conference"),
        ExpenseRequest("Meera", 42_000, "Team laptops"),
        ExpenseRequest("Karan", 120_000, "Office renovation"),
        ExpenseRequest("Dev", 300, "Alcohol"),
        ExpenseRequest("Neha", -50, "Taxi"),
    ]

    for req in requests:
        submit(chain, req)
