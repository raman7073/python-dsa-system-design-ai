from enum import Enum
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

# OrderStatus Enum -> preparing,picked_up,in_transit,delivered,cancelled


class OrderStatus(str, Enum):
    PREPARING = "preparing"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

# Database table for Orders
# id (primary key), customer_name, delivery_address, items,status, created_at, updated_at


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_name: str
    delivery_address: str
    items: str  # Comma-separated list of items
    status: OrderStatus = Field(default=OrderStatus.PREPARING)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# Schema for creating a new order
class OrderCreate(SQLModel):
    customer_name: str
    delivery_address: str
    items: str  # Comma-separated list of items

# Schema for updating an existing order


class OrderUpdate(SQLModel):
    status: Optional[OrderStatus] = None
    delivery_address: Optional[str] = None

# Status Log table for tracking order status changes
# order_id (foreign key), old_status, new_status, changed_at(datetime)


class StatusLog(SQLModel):
    order_id: int
    old_status: OrderStatus
    new_status: OrderStatus
    changed_at: datetime
