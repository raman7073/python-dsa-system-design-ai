from shared.vehicle_type import VehicleType

class Vehicle:
    def __init__(self, plate: str, vehicle_type: VehicleType):
        self.plate = plate
        self.type = vehicle_type
