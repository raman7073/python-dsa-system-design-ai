from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

class TodoWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    description: str | None = Field(default=None, max_length=5000)
    completed: bool = False

class TodoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    description: str | None = Field(default=None, max_length=5000)
    completed: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field")
        for field in ("title", "completed"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

class TodoRead(TodoWrite):
    id: int
    created_at: datetime
    updated_at: datetime

class TodoPage(BaseModel):
    items: list[TodoRead]
    total: int
    offset: int
    limit: int
