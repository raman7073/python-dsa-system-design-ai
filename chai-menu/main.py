from http.client import HTTPException

from fastapi import FastAPI
from fastapi.params import Query
from data import menu_items
from models import MenuItem, MenuResponse

app = FastAPI(
    title="Chai Point menu API",
    description="This is a sample Chai Point menu API. You can find out more about FastAPI at [https://fastapi.tiangolo.com/](https://fastapi.tiangolo.com/).", 
)

@app.get("/")
def root():
    return {"message": "Welcome to the Chai Point menu API!"}

#/menu endpoint to get the menu items
#/menu?in_stock=true to get only the items that are in stock
@app.get("/menu", response_model=MenuResponse)
def get_menu(in_stock: bool | None = Query(default=None, description="Filter menu items by stock availability")):
    if in_stock is not None:
        filtered_items = [item for item in menu_items if item["in_stock"] == in_stock]
        if not filtered_items:
            raise HTTPException(status_code=404, detail="No menu items found for the given stock availability")
        return MenuResponse(status="success", count=len(filtered_items), items=filtered_items)
    return MenuResponse(status="success", count=len(menu_items), items=menu_items)


@app.get("/menu/{item_id}", response_model=MenuItem)
def get_menu_item(item_id: int):
    item = next((item for item in menu_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return MenuItem(**item)