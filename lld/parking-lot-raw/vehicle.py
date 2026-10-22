class Vehicle:
    def __init__(self, license_plate: str, kind: str) -> None:
        if not isinstance(license_plate, str) or not license_plate.strip():
            raise ValueError("A vehicle needs a license plate")
        self.license_plate = license_plate.strip().upper()
        self.kind = kind


class Car(Vehicle):
    def __init__(self, license_plate: str) -> None:
        super().__init__(license_plate, "car")


class Motorcycle(Vehicle):
    def __init__(self, license_plate: str) -> None:
        super().__init__(license_plate, "motorcycle")


class Truck(Vehicle):
    def __init__(self, license_plate: str) -> None:
        super().__init__(license_plate, "truck")
