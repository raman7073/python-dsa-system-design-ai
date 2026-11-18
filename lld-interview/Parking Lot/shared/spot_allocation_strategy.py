from abc import ABC, abstractmethod

from shared.vehicle import Vehicle
from parking_lot_v5.parking_spot import ParkingSpot


class SpotAllocationStrategy(ABC):
    """Only CHOOSES a spot. Never mutates. The caller claims the spot it returns."""

    @abstractmethod
    def find_spot(self, v: Vehicle, spots: list[ParkingSpot]) -> ParkingSpot | None:
        pass