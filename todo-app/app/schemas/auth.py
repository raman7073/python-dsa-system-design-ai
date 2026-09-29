from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

class Register(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-zA-Z0-9_]{3,50}$")]
    password: str = Field(min_length=12, max_length=128)

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900
