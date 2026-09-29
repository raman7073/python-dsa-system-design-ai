from models.user import User
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional

# Database table


class Book(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    author: str = Field(index=True)
    price: float
    is_sold: bool = Field(default=False)

    # foreign key to user table
    user_id: int = Field(foreign_key="user.id")
    # Relationships
    owner: "User" = Relationship(back_populates="books")


# Book Create
class BookCreate(SQLModel):
    title: str
    author: str
    price: int
    user_id: int

# Book Read


class BookRead(SQLModel):
    id: int
    title: str
    author: str
    price: float
    is_sold: bool
    user_id: int


class BookUpdate(SQLModel):
    price: Optional[float] = None
    is_sold: Optional[bool] = None


# to avoid circular dependency
Book.model_rebuild()
