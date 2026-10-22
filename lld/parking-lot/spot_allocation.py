from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Sequence

from parking_floor import ParkingFloor
from parking_spot import ParkingSpot
from vehicle import Vehicle


@dataclass(frozen=True)
class SpotAllocation:
    floor: ParkingFloor
    spot: ParkingSpot


class SpotAllocationStrategy(ABC):
    @abstractmethod
    def find_spot(
        self, floors: Sequence[ParkingFloor], vehicle: Vehicle
    ) -> Optional[SpotAllocation]:
        raise NotImplementedError


class FirstAvailableSpotAllocationStrategy(SpotAllocationStrategy):
    def find_spot(
        self, floors: Sequence[ParkingFloor], vehicle: Vehicle
    ) -> Optional[SpotAllocation]:
        for floor in floors:
            for spot in floor.spots:
                if not spot.is_occupied and spot.can_fit_vehicle(vehicle):
                    return SpotAllocation(floor=floor, spot=spot)
        return None
