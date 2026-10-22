from dataclasses import dataclass, field
from enum import Enum


class VehicleType(Enum):
    CAR = 1
    MOTORCYCLE = 2
    TRUCK = 3


VehicleKind = VehicleType | str


"""
WHAT IS frozen=True?
Normally, you can change a variable after creating an object:
    car = Car("ABC")
    car.license_plate = "XYZ"  <-- This works in a normal dataclass.

When you add `frozen=True`, the object becomes "locked" (read-only). 
If you try to do `car.license_plate = "XYZ"`, Python will crash with a 
`FrozenInstanceError`. 

Why use it? 
1. It prevents accidental bugs where a vehicle's plate is changed by mistake.
2. It makes the object "hashable", meaning you can use this Vehicle as a key 
   in a Python dictionary or store it in a Set.
"""
@dataclass(frozen=True)
class Vehicle:
    license_plate: str
    vehicle_type: VehicleKind

    def __post_init__(self) -> None:
        normalized_plate = self.license_plate.strip().upper()
        
        if not normalized_plate:
            raise ValueError("License plate cannot be empty")
        if not isinstance(self.vehicle_type, VehicleType) and (
            not isinstance(self.vehicle_type, str) or not self.vehicle_type.strip()
        ):
            raise TypeError("vehicle_type must be a VehicleType or non-empty string")
            
        """
        THE __post_init__ TRAP WITH FROZEN DATACLASSES:
        Because the dataclass is frozen, you are not allowed to write:
            self.license_plate = normalized_plate  <-- THIS WILL CRASH!
            
        The dataclass is already "locked" by the time __post_init__ runs. 
        To safely bypass this lock and update the license plate during this 
        initialization phase, we must use the low-level `object.__setattr__` method.
        """
        object.__setattr__(self, "license_plate", normalized_plate)


@dataclass(frozen=True)
class Car(Vehicle):
    vehicle_type: VehicleType = field(default=VehicleType.CAR, init=False)


@dataclass(frozen=True)
class Motorcycle(Vehicle):
    vehicle_type: VehicleType = field(default=VehicleType.MOTORCYCLE, init=False)


@dataclass(frozen=True)
class Truck(Vehicle):
    vehicle_type: VehicleType = field(default=VehicleType.TRUCK, init=False)
