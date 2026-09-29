from pydantic import BaseModel

class MenuItem(BaseModel):
    id: int
    name: str
    price: float
    in_stock: bool

class MenuResponse(BaseModel):
    status: str
    count: int
    items: list[MenuItem]