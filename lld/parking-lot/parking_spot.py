from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from vehicle import Vehicle, VehicleKind, VehicleType


class SpotType(Enum):
    COMPACT = 1
    REGULAR = 2
    LARGE = 3


_DEFAULT_COMPATIBLE_SPOTS = {
    VehicleType.MOTORCYCLE: frozenset(SpotType),
    VehicleType.CAR: frozenset({SpotType.REGULAR, SpotType.LARGE}),
    VehicleType.TRUCK: frozenset({SpotType.LARGE}),
}


@dataclass(frozen=True)
class SpotFitPolicy:
    """Immutable vehicle-to-spot rules; extend with with_rule()."""

    _rules: Mapping[VehicleKind, frozenset[SpotType]] = field(
        init=False, repr=False, compare=False
    )

    def __init__(
        self, rules: Mapping[VehicleKind, frozenset[SpotType]] | None = None
    ) -> None:
        source = _DEFAULT_COMPATIBLE_SPOTS if rules is None else rules
        object.__setattr__(
            self,
            "_rules",
            MappingProxyType(
                {kind: frozenset(spot_types) for kind, spot_types in source.items()}
            ),
        )

    def with_rule(
        self, kind: VehicleKind, spot_types: set[SpotType] | frozenset[SpotType]
    ) -> "SpotFitPolicy":
        if not spot_types or not all(isinstance(spot, SpotType) for spot in spot_types):
            raise ValueError("A vehicle kind needs at least one valid spot type")
        return SpotFitPolicy({**self._rules, kind: frozenset(spot_types)})

    def can_fit(self, vehicle: Vehicle, spot_type: SpotType) -> bool:
        return spot_type in self._rules.get(vehicle.vehicle_type, frozenset())


@dataclass
class ParkingSpot:
    spot_id: str
    spot_type: SpotType
    vehicle: Optional[Vehicle] = None
    fit_policy: SpotFitPolicy = field(default_factory=SpotFitPolicy, repr=False)

    def __post_init__(self) -> None:
        if not self.spot_id.strip():
            raise ValueError("spot_id cannot be empty")
        if not isinstance(self.spot_type, SpotType):
            raise TypeError("spot_type must be a SpotType")
        if self.vehicle is not None and not self.can_fit_vehicle(self.vehicle):
            raise ValueError(f"Vehicle does not fit in parking spot {self.spot_id}")

    @property
    def is_occupied(self) -> bool:
        return self.vehicle is not None

    def can_fit_vehicle(self, vehicle: Vehicle) -> bool:
        return self.fit_policy.can_fit(vehicle, self.spot_type)

    def park(self, vehicle: Vehicle) -> None:
        if self.is_occupied:
            raise ValueError(f"Parking spot {self.spot_id} is already occupied")
        if not self.can_fit_vehicle(vehicle):
            raise ValueError(
                f"{getattr(vehicle.vehicle_type, 'name', vehicle.vehicle_type)} cannot fit in a "
                f"{self.spot_type.name} spot"
            )
        self.vehicle = vehicle

    def remove_vehicle(self) -> Optional[Vehicle]:
        vehicle = self.vehicle
        self.vehicle = None
        return vehicle
