class OrderItem:
    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity


class Order:
    def __init__(self, order_id):
        self.order_id = order_id
        self.__items = []

    def add_item(self, product, quantity):
        # The order creates and manages its own items.
        item = OrderItem(product, quantity)
        self.__items.append(item)

    def show_items(self):
        for item in self.__items:
            print(f"{item.product} × {item.quantity}")


order = Order("ORD101")

order.add_item("Keyboard", 1)
order.add_item("Mouse", 2)

order.show_items()
