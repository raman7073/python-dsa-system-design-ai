from models.book import Book
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional

# Database table


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    email: str = Field(unique=True)
    college: str

    # Relationships
    books: list["Book"] = Relationship(back_populates="owner")


# request body to create a user
class UserCreate(SQLModel):
    name: str
    email: str
    college: str


# response body
class UserRead(SQLModel):
    id: int
    name: str
    email: str
    college: str


# avoid circular import by importing Book at the end of the file
User.model_rebuild()  # Rebuild the model to resolve forward references
