from vehicle import Vehicle, VehicleType


class ParkingSpotType:
    DISABLED = "disabled"
    COMPACT = "compact"
    LARGE = "large"
    MOTORCYCLE = "motorcycle"
    ELECTRIC_CAR = "electric_car"


class ParkingSpot:
    def __init__(self, spot_id: str, floor_id: str, spot_type: str) -> None:
        if not spot_id or not floor_id:
            raise ValueError("A spot needs both a spot ID and a floor ID")

        self.spot_id: str = spot_id
        self.floor_id: str = floor_id
        self.spot_type: str = spot_type
        self.vehicle: Vehicle | None = None

    def is_free(self) -> bool:
        return self.vehicle is None

    def can_fit(self, vehicle: Vehicle) -> bool:
        # Each concrete spot class decides which vehicles it accepts.
        raise NotImplementedError("Use a specific parking spot class")

    def park(self, vehicle: Vehicle) -> None:
        if not self.is_free():
            raise ValueError("Spot is already occupied")
        if not self.can_fit(vehicle):
            raise ValueError("Vehicle cannot park in this spot")
        self.vehicle = vehicle

    def vacate(self) -> None:
        if self.is_free():
            raise ValueError("Spot is already empty")
        self.vehicle = None


class CarSpot(ParkingSpot):
    def __init__(
        self, spot_id: str, floor_id: str, spot_type: str = ParkingSpotType.COMPACT
    ) -> None:
        if spot_type not in (ParkingSpotType.COMPACT, ParkingSpotType.LARGE):
            raise ValueError("A car spot must be compact or large")
        super().__init__(spot_id, floor_id, spot_type)

    def can_fit(self, vehicle: Vehicle) -> bool:
        vehicle_type = vehicle.get_vehicle_type()
        if self.spot_type == ParkingSpotType.COMPACT:
            return vehicle_type == VehicleType.CAR
        return vehicle_type in (VehicleType.CAR, VehicleType.TRUCK, VehicleType.VAN)


class DisabledSpot(ParkingSpot):
    def __init__(self, spot_id: str, floor_id: str) -> None:
        super().__init__(spot_id, floor_id, ParkingSpotType.DISABLED)

    def can_fit(self, vehicle: Vehicle) -> bool:
        return vehicle.get_vehicle_type() == VehicleType.CAR and vehicle.accessible


class ElectricCarSpot(ParkingSpot):
    def __init__(self, spot_id: str, floor_id: str) -> None:
        super().__init__(spot_id, floor_id, ParkingSpotType.ELECTRIC_CAR)

    def can_fit(self, vehicle: Vehicle) -> bool:
        return vehicle.get_vehicle_type() == VehicleType.ELECTRIC_CAR


class MotorcycleSpot(ParkingSpot):
    def __init__(self, spot_id: str, floor_id: str) -> None:
        super().__init__(spot_id, floor_id, ParkingSpotType.MOTORCYCLE)

    def can_fit(self, vehicle: Vehicle) -> bool:
        return vehicle.get_vehicle_type() == VehicleType.MOTORCYCLE
