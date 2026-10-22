"""Create vehicles by type without changing callers for every new subclass."""

from collections.abc import Callable

from model.vehicle import Car, ElectricCar, Motorbike, Truck, Van, Vehicle, VehicleType


class VehicleFactory:
    """Keep a per-factory registry of vehicle constructors."""

    def __init__(self) -> None:
        self._constructors: dict[str, Callable[..., Vehicle]] = {
            VehicleType.CAR: Car,
            VehicleType.TRUCK: Truck,
            VehicleType.ELECTRIC_CAR: ElectricCar,
            VehicleType.MOTORCYCLE: Motorbike,
            VehicleType.VAN: Van,
        }

    def register(
        self,
        vehicle_type: str,
        constructor: Callable[..., Vehicle],
        *,
        replace: bool = False,
    ) -> None:
        self._check_type(vehicle_type)
        if not callable(constructor):
            raise TypeError("Vehicle constructor must be callable")
        if vehicle_type in self._constructors and not replace:
            raise ValueError("Vehicle type is already registered: " + vehicle_type)
        self._constructors[vehicle_type] = constructor

    def create_vehicle(
        self, vehicle_type: str, registration_no: str, **options: object
    ) -> Vehicle:
        self._check_type(vehicle_type)
        if not isinstance(registration_no, str) or not registration_no.strip():
            raise ValueError("A vehicle needs a registration number")
        try:
            constructor = self._constructors[vehicle_type]
        except KeyError as error:
            raise ValueError("Unknown vehicle type: " + vehicle_type) from error

        vehicle = constructor(registration_no, **options)
        if not isinstance(vehicle, Vehicle):
            raise TypeError("Vehicle constructor must return a Vehicle")
        if vehicle.get_vehicle_type() != vehicle_type:
            raise ValueError("Vehicle constructor returned the wrong type")
        return vehicle

    def _check_type(self, vehicle_type: str) -> None:
        if not isinstance(vehicle_type, str) or not vehicle_type.strip():
            raise ValueError("Vehicle type must be a non-empty string")
