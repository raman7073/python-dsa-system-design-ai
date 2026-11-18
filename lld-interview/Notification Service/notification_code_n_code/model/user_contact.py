from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UserContact:
    """Where to reach a user on each channel."""
    user_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    device_token: Optional[str] = None
