class VehicleType:
    CAR = "car"
    TRUCK = "truck"
    ELECTRIC_CAR = "electric_car"
    MOTORCYCLE = "motorcycle"
    VAN = "van"


class Vehicle:
    def __init__(self, registration_no: str, vehicle_type: str, accessible: bool = False) -> None:
        if not isinstance(registration_no, str) or not registration_no.strip():
            raise ValueError("A vehicle needs a registration number")

        self.registration_no: str = registration_no.strip().upper()
        self.vehicle_type: str = vehicle_type
        self.accessible: bool = accessible

    def get_vehicle_type(self) -> str:
        return self.vehicle_type

    def get_registration_no(self) -> str:
        return self.registration_no


class Car(Vehicle):
    def __init__(self, registration_no: str, accessible: bool = False) -> None:
        super().__init__(registration_no, VehicleType.CAR, accessible)


class Truck(Vehicle):
    def __init__(self, registration_no: str) -> None:
        super().__init__(registration_no, VehicleType.TRUCK)


class ElectricCar(Vehicle):
    def __init__(self, registration_no: str) -> None:
        super().__init__(registration_no, VehicleType.ELECTRIC_CAR)


class Motorbike(Vehicle):
    def __init__(self, registration_no: str) -> None:
        super().__init__(registration_no, VehicleType.MOTORCYCLE)


class Van(Vehicle):
    def __init__(self, registration_no: str) -> None:
        super().__init__(registration_no, VehicleType.VAN)
