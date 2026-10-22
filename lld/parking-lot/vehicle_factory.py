from collections.abc import Callable

from vehicle import Car, Motorcycle, Truck, Vehicle, VehicleKind, VehicleType


class VehicleFactory:
    """Create vehicles by kind using registered constructor functions."""

    def __init__(self) -> None:
        # A constructor takes a license plate and returns a Vehicle.
        # These are the built-in kinds; callers can register more kinds below.
        self._constructors: dict[VehicleKind, Callable[[str], Vehicle]] = {
            VehicleType.CAR: Car,
            VehicleType.MOTORCYCLE: Motorcycle,
            VehicleType.TRUCK: Truck,
        }

    def register(
        self, vehicle_kind: VehicleKind, constructor: Callable[[str], Vehicle]
    ) -> None:
        """Add a kind without changing create_vehicle or the built-in mapping."""
        if vehicle_kind in self._constructors:
            raise ValueError(f"Vehicle kind already registered: {vehicle_kind}")
        self._constructors[vehicle_kind] = constructor

    def create_vehicle(
        self, vehicle_type: VehicleKind, license_plate: str
    ) -> Vehicle:
        """Find the constructor for a kind and create its vehicle."""
        try:
            constructor = self._constructors[vehicle_type]
        except KeyError as error:
            raise ValueError(f"Unsupported vehicle type: {vehicle_type}") from error
        vehicle = constructor(license_plate)
        # Catch a misregistered constructor before returning the wrong kind.
        if vehicle.vehicle_type != vehicle_type:
            raise ValueError("Vehicle constructor returned the wrong type")
        return vehicle
